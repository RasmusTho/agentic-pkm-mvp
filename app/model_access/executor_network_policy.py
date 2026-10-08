"""Configuration-driven, pre-completion paths to a logical remote executor.

Endpoint and authentication material are resolved from host-local environment
references. They never enter model policy or the logical path receipt.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from threading import Lock
from typing import Callable, Literal, Protocol
from uuid import uuid4

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.model_access.codex_remote_transport import (
    CodexRemoteTransport,
    RemoteCatalogError,
    RemoteCompletionError,
    RemotePreflightError,
)
from app.model_access.remote_contract import (
    CatalogRequest,
    CatalogResponse,
    CompletionCapabilityIntent,
    CompletionRequest,
    CompletionRouteIdentity,
    CompletionResponse,
    PreflightRequest,
    PreflightResponse,
)


DEFAULT_EXECUTOR_NETWORK_POLICY_PATH = Path(
    "config/model_access/executor_network_paths.yaml"
)
EXECUTOR_NETWORK_PROFILE = "profile.codex_remote_host"
_ENV_REFERENCE = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")
_REFERENCE = re.compile(r"^host_config\.[a-z][a-z0-9_]*$")
_PATH_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PATH_LOCAL_FAILURES = frozenset(
    {
        "PATH_UNAVAILABLE",
        "CONNECT_TIMEOUT",
        "PREFLIGHT_TIMEOUT",
        "PATH_AUTHENTICATION_FAILED",
    }
)


class ExecutorNetworkConfigurationError(RuntimeError):
    """A sanitized path-policy or host-local path configuration failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class _EndpointReference(_StrictConfig):
    endpoint_env: str

    @model_validator(mode="after")
    def _valid_env_reference(self) -> "_EndpointReference":
        if _ENV_REFERENCE.fullmatch(self.endpoint_env) is None:
            raise ValueError("endpoint environment reference is invalid")
        return self


class _AuthenticationProfile(_StrictConfig):
    mode: Literal["mutual_tls", "tailscale_serve_app_capability"]
    ca_bundle_env: str | None = None
    client_certificate_env: str | None = None
    client_key_env: str | None = None

    @model_validator(mode="after")
    def _authentication_references_match_mode(self) -> "_AuthenticationProfile":
        refs = (self.ca_bundle_env, self.client_certificate_env, self.client_key_env)
        if self.mode == "mutual_tls":
            if any(ref is None or _ENV_REFERENCE.fullmatch(ref) is None for ref in refs):
                raise ValueError("mutual TLS references are incomplete")
        elif any(ref is not None for ref in refs):
            raise ValueError("Tailscale Serve authentication must not declare TLS files")
        return self


class _PathProfile(_StrictConfig):
    adapter: Literal["private_https_ingress", "tailscale_serve_https"]
    endpoint_ref: str
    authentication_profile_ref: str
    caller_policy_ref: Literal["policy.vlan_mtls_authenticated_caller"]

    @model_validator(mode="after")
    def _valid_references(self) -> "_PathProfile":
        if not _REFERENCE.fullmatch(self.endpoint_ref):
            raise ValueError("endpoint reference is invalid")
        if not _REFERENCE.fullmatch(self.authentication_profile_ref):
            raise ValueError("authentication profile reference is invalid")
        return self


class _ExecutorPolicy(_StrictConfig):
    order: list[str] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def _unique_path_order(self) -> "_ExecutorPolicy":
        if any(_PATH_ID.fullmatch(path_id) is None for path_id in self.order):
            raise ValueError("path profile name is invalid")
        if len(self.order) != len(set(self.order)):
            raise ValueError("path order contains duplicates")
        return self


class _ExecutorNetworkPolicy(_StrictConfig):
    version: Literal[1]
    endpoint_references: dict[str, _EndpointReference]
    authentication_profiles: dict[str, _AuthenticationProfile]
    path_profiles: dict[str, _PathProfile]
    executor_path_policies: dict[str, _ExecutorPolicy]

    @model_validator(mode="after")
    def _references_are_closed(self) -> "_ExecutorNetworkPolicy":
        if not self.endpoint_references or not self.authentication_profiles:
            raise ValueError("host-local references must be declared")
        if any(_PATH_ID.fullmatch(path_id) is None for path_id in self.path_profiles):
            raise ValueError("path profile name is invalid")
        for profile in self.path_profiles.values():
            endpoint_key = profile.endpoint_ref.removeprefix("host_config.")
            auth_key = profile.authentication_profile_ref.removeprefix("host_config.")
            endpoint = self.endpoint_references.get(endpoint_key)
            authentication = self.authentication_profiles.get(auth_key)
            if endpoint is None or authentication is None:
                raise ValueError("path profile refers to undeclared host configuration")
            if profile.adapter == "private_https_ingress" and authentication.mode != "mutual_tls":
                raise ValueError("private VLAN ingress requires mutual TLS")
            if (
                profile.adapter == "tailscale_serve_https"
                and authentication.mode != "tailscale_serve_app_capability"
            ):
                raise ValueError("Tailscale path requires Serve application capability auth")
        if not self.executor_path_policies:
            raise ValueError("executor path policy is missing")
        for executor_policy in self.executor_path_policies.values():
            if any(path_id not in self.path_profiles for path_id in executor_policy.order):
                raise ValueError("executor path order refers to an undeclared profile")
        return self


@dataclass(frozen=True)
class ResolvedExecutorPath:
    path_profile: str
    adapter: Literal["private_https_ingress", "tailscale_serve_https"]
    endpoint: str = field(repr=False)
    ca_bundle_path: str | None = field(default=None, repr=False)
    client_certificate_path: str | None = field(default=None, repr=False)
    client_key_path: str | None = field(default=None, repr=False)

    @property
    def tls_verify(self) -> bool | str:
        return self.ca_bundle_path or True

    @property
    def client_certificate(self) -> tuple[str, str] | None:
        if self.client_certificate_path is None or self.client_key_path is None:
            return None
        return self.client_certificate_path, self.client_key_path


@dataclass(frozen=True)
class ExecutorPathReceipt:
    """One-use, request-bound evidence; excludes host and auth material."""

    executor_profile: str
    selected_path_profile: str
    route: CompletionRouteIdentity
    reasoning_effort: str | None
    capability_intent: CompletionCapabilityIntent
    failure_before_selection: str | None = None
    receipt_id: str = field(default_factory=lambda: uuid4().hex, repr=False)

    def matches(self, request: CompletionRequest) -> bool:
        return (
            self.route == request.route
            and self.reasoning_effort == request.reasoning_effort
            and self.capability_intent == request.capability_intent
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "executor_profile": self.executor_profile,
            "failure_before_selection": self.failure_before_selection,
            "selected_path_profile": self.selected_path_profile,
            "route": self.route.model_dump(mode="json"),
            "reasoning_effort": self.reasoning_effort,
            "capability_intent": self.capability_intent.model_dump(mode="json"),
        }


@dataclass(frozen=True)
class ExecutorPathPreflight:
    response: PreflightResponse
    receipt: ExecutorPathReceipt


class _RemotePathTransport(Protocol):
    def preflight(self, request: PreflightRequest) -> PreflightResponse: ...

    def catalog(self, request: CatalogRequest) -> CatalogResponse: ...

    def complete(self, request: CompletionRequest) -> CompletionResponse: ...

    def close(self) -> None: ...


TransportFactory = Callable[[ResolvedExecutorPath], _RemotePathTransport]


def _load_policy(path: Path) -> _ExecutorNetworkPolicy:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return _ExecutorNetworkPolicy.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError, ValueError, TypeError):
        raise ExecutorNetworkConfigurationError("path_policy_invalid") from None


def _required_host_value(
    environment: Mapping[str, str], variable: str, *, code: str = "path_configuration_missing"
) -> str:
    value = environment.get(variable, "").strip()
    if not value:
        raise ExecutorNetworkConfigurationError(code)
    return value


def _require_file_reference(environment: Mapping[str, str], variable: str) -> str:
    value = _required_host_value(environment, variable)
    if not Path(value).is_file():
        raise ExecutorNetworkConfigurationError("path_configuration_missing")
    return value


def resolve_executor_paths(
    executor_profile: str,
    *,
    policy_path: Path = DEFAULT_EXECUTOR_NETWORK_POLICY_PATH,
    environment: Mapping[str, str] | None = None,
) -> tuple[ResolvedExecutorPath, ...]:
    """Resolve one logical executor's ordered paths without exposing their values."""

    policy = _load_policy(policy_path)
    executor_policy = policy.executor_path_policies.get(executor_profile)
    if executor_policy is None:
        raise ExecutorNetworkConfigurationError("path_policy_missing")
    host_environment = os.environ if environment is None else environment
    resolved: list[ResolvedExecutorPath] = []
    for path_id in executor_policy.order:
        profile = policy.path_profiles[path_id]
        endpoint_ref = profile.endpoint_ref.removeprefix("host_config.")
        auth_ref = profile.authentication_profile_ref.removeprefix("host_config.")
        endpoint_env = policy.endpoint_references[endpoint_ref].endpoint_env
        endpoint = _required_host_value(host_environment, endpoint_env)
        authentication = policy.authentication_profiles[auth_ref]
        ca_bundle: str | None
        certificate: str | None
        key: str | None
        if authentication.mode == "mutual_tls":
            assert authentication.ca_bundle_env is not None
            assert authentication.client_certificate_env is not None
            assert authentication.client_key_env is not None
            ca_bundle = _require_file_reference(host_environment, authentication.ca_bundle_env)
            certificate = _require_file_reference(
                host_environment, authentication.client_certificate_env
            )
            key = _require_file_reference(host_environment, authentication.client_key_env)
        else:
            ca_bundle = certificate = key = None
        resolved.append(
            ResolvedExecutorPath(
                path_profile=path_id,
                adapter=profile.adapter,
                endpoint=endpoint,
                ca_bundle_path=ca_bundle,
                client_certificate_path=certificate,
                client_key_path=key,
            )
        )
    return tuple(resolved)


def _default_transport_factory(
    *, timeout_seconds: float
) -> TransportFactory:
    def create(path: ResolvedExecutorPath) -> _RemotePathTransport:
        return CodexRemoteTransport(
            endpoint=path.endpoint,
            path_adapter=path.adapter,
            tls_verify=path.tls_verify,
            client_certificate=path.client_certificate,
            timeout_seconds=timeout_seconds,
        )

    return create


class ExecutorNetworkPathRouter:
    """Select configured network paths before inference; never retry completion."""

    def __init__(
        self,
        *,
        executor_profile: str = EXECUTOR_NETWORK_PROFILE,
        policy_path: Path = DEFAULT_EXECUTOR_NETWORK_POLICY_PATH,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: float = 1_260.0,
        transport_factory: TransportFactory | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("executor path timeout must be positive")
        paths = resolve_executor_paths(
            executor_profile,
            policy_path=policy_path,
            environment=environment,
        )
        factory = transport_factory or _default_transport_factory(
            timeout_seconds=timeout_seconds
        )
        self.executor_profile = executor_profile
        self._ordered_path_ids = tuple(path.path_profile for path in paths)
        self._transports: dict[str, _RemotePathTransport] = {}
        self._receipt_lock = Lock()
        self._pending_receipts: dict[str, ExecutorPathReceipt] = {}
        try:
            for path in paths:
                self._transports[path.path_profile] = factory(path)
        except Exception:
            self.close()
            raise ExecutorNetworkConfigurationError("path_configuration_invalid") from None

    def preflight(self, request: PreflightRequest) -> ExecutorPathPreflight:
        failure_before_selection: str | None = None
        for path_id in self._ordered_path_ids:
            try:
                response = self._transports[path_id].preflight(request)
            except RemotePreflightError as exc:
                if exc.code not in _PATH_LOCAL_FAILURES:
                    if exc.code == "preflight_unavailable":
                        # Keep an unclassified path adapter failure terminal so it
                        # cannot authorize a different provider.
                        raise RemotePreflightError(
                            "path_preflight_unclassified"
                        ) from None
                    raise
                failure_before_selection = exc.code
                continue
            if response.route != request.route:
                raise RemotePreflightError("preflight_route_mismatch")
            receipt = ExecutorPathReceipt(
                executor_profile=self.executor_profile,
                selected_path_profile=path_id,
                route=request.route,
                reasoning_effort=request.reasoning_effort,
                capability_intent=request.capability_intent,
                failure_before_selection=failure_before_selection,
            )
            with self._receipt_lock:
                self._pending_receipts[receipt.receipt_id] = receipt
            return ExecutorPathPreflight(
                response=response,
                receipt=receipt,
            )
        raise RemotePreflightError(failure_before_selection or "PATH_UNAVAILABLE")

    def discard_path_receipt(self, receipt: ExecutorPathReceipt | None) -> None:
        """Revoke a preflight receipt when it was used only for route selection."""
        if receipt is None:
            return
        with self._receipt_lock:
            if self._pending_receipts.get(receipt.receipt_id) == receipt:
                self._pending_receipts.pop(receipt.receipt_id, None)

    def catalog(self, request: CatalogRequest) -> CatalogResponse:
        failure_before_selection: str | None = None
        for path_id in self._ordered_path_ids:
            try:
                response = self._transports[path_id].catalog(request)
            except RemoteCatalogError as exc:
                if exc.code not in _PATH_LOCAL_FAILURES:
                    raise
                failure_before_selection = exc.code
                continue
            if response.snapshot.transport_id != request.transport_id:
                raise RemoteCatalogError("catalog_transport_mismatch")
            return response
        raise RemoteCatalogError(failure_before_selection or "PATH_UNAVAILABLE")

    def complete_selected_path(
        self,
        request: CompletionRequest,
        *,
        receipt: ExecutorPathReceipt | None,
    ) -> CompletionResponse:
        """Dispatch exactly once on the preflighted path; there is no path fallback."""

        if (
            receipt is None
            or receipt.executor_profile != self.executor_profile
            or receipt.selected_path_profile not in self._transports
        ):
            raise RemoteCompletionError("executor_path_preflight_required")
        with self._receipt_lock:
            pending_receipt = self._pending_receipts.pop(receipt.receipt_id, None)
        if pending_receipt is None:
            raise RemoteCompletionError("executor_path_preflight_required")
        if pending_receipt != receipt or not receipt.matches(request):
            raise RemoteCompletionError("executor_path_preflight_mismatch")
        response = self._transports[receipt.selected_path_profile].complete(request)
        if response.route != request.route:
            raise RemoteCompletionError("executor_route_mismatch", indeterminate=True)
        return response

    def close(self) -> None:
        with self._receipt_lock:
            self._pending_receipts.clear()
        closed: set[int] = set()
        for transport in self._transports.values():
            if id(transport) in closed:
                continue
            closed.add(id(transport))
            try:
                transport.close()
            except Exception:
                continue


__all__ = [
    "DEFAULT_EXECUTOR_NETWORK_POLICY_PATH",
    "EXECUTOR_NETWORK_PROFILE",
    "ExecutorNetworkConfigurationError",
    "ExecutorNetworkPathRouter",
    "ExecutorPathPreflight",
    "ExecutorPathReceipt",
    "ResolvedExecutorPath",
    "resolve_executor_paths",
]
