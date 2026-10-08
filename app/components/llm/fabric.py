from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import os
import weakref
from typing import Any, Callable
from urllib.parse import urlsplit

from app.components.embeddings import (
    EmbeddingClientProtocol,
    EmbeddingIdentity,
    get_embedding_client,
    resolve_embedding_identity,
)
from app.components.llm.router import LLMRouteError, LLMRouter, LLMRoute, LLMTaskIntent
from app.components.settings.models_loader import load_models
from app.model_access.adapter_factory import ModelAccessAdapterFactory
from app.model_access.catalog import (
    CatalogCache,
    CatalogError,
    CatalogSelectionPolicy,
    select_latest_compatible,
)
from app.llm.preflight_fallback import (
    select_product_preflight_route,
)
from app.model_access.codex_remote_transport import (
    CodexRemoteTransport,
    RemoteCompletionError,
    RemoteEmbeddingError,
)
from app.model_access.executor_network_policy import (
    EXECUTOR_NETWORK_PROFILE,
    ExecutorNetworkPathRouter,
    ResolvedExecutorPath,
)
from app.model_access.remote_contract import (
    CompletionCapabilityIntent,
    CompletionRouteIdentity,
    ProductCatalogRequest,
    ProductCompletionRequest,
    ProductEmbeddingRequest,
    ProductPreflightRequest,
)
from app.model_access.router import ModelAccessRouter
from app.embedding_config import assert_embed_dim, l2_normalize
from app.llm.embeddings import _chunk_for_embedding, _embedding_max_input_chars, _mean_pool
from app.services.llm import LLMBackendTimeout, call_llm
from app.settings.runtime import get_settings_bundle
from llm_contract import (
    CapabilityProvenance,
    FallbackProvenance,
    FallbackRequirement,
    ModelAccessIntent,
    ModelAccessProfile,
    ModelAccessAdapterDescriptor,
    ModelAccessRoute,
    ModelCapabilities,
    ModelCapabilityRequirements,
    ModelResolutionRequest,
    ResolvedModelAccess,
)


@lru_cache(maxsize=1)
def _adapter_factory() -> ModelAccessAdapterFactory:
    return ModelAccessAdapterFactory.from_declared_sources()


@dataclass(frozen=True)
class AdapterRuntimeConfig:
    """Ephemeral adapter settings; never part of route intent or provenance."""

    base_url: str | None = field(default=None, repr=False)
    api_key: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.base_url is None:
            return
        parsed = urlsplit(self.base_url.strip())
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "adapter base URL must be absolute HTTP(S) without embedded credentials"
            )


class _SelectedProductTarget:
    """Adapt Product's existing route decision to the neutral resolver port."""

    def __init__(self, selected: ResolvedModelAccess) -> None:
        self._selected = selected

    def resolve(self, request, *, runtime: str, channel: str, consumer: str):
        if request != self._selected.request:
            raise ValueError("Product resolver received an unexpected model request")
        return self._selected

    def resolve_group(self, requests, *, runtime: str, channel: str, consumer: str):
        if len(requests) != 1 or requests[0] != self._selected.request:
            raise ValueError("Product resolver only supports this one selected target")
        return (self._selected,)


def _credential_ref(authentication_scheme: str, provider: str) -> str:
    if authentication_scheme == "provider_credential_ref":
        return f"{provider}.api-key"
    if authentication_scheme == "local_subscription_session":
        return f"{provider}.subscription-session"
    if authentication_scheme in {
        "executor_path_authentication",
        "tailscale_app_capability",
    }:
        return "executor.credential-ref"
    return f"{provider}.session-ref"


_PRODUCT_CATALOG_CACHE = CatalogCache()
_REMOTE_EXECUTOR_ADAPTERS = frozenset(
    {"codex_cli_tailscale", "ollama_http_tailscale"}
)


def _is_remote_executor_route(route: ModelAccessRoute) -> bool:
    return (
        route.execution_host_profile == EXECUTOR_NETWORK_PROFILE
        and route.execution_boundary
        in {"private_network_https", "private_tailnet_serve_https"}
    )


def _new_executor_path_router(
    *, executor_profile: str, timeout_seconds: float
) -> ExecutorNetworkPathRouter:
    def create_transport(path: ResolvedExecutorPath) -> CodexRemoteTransport:
        return CodexRemoteTransport(
            endpoint=path.endpoint,
            path_adapter=path.adapter,
            tls_verify=path.tls_verify,
            client_certificate=path.client_certificate,
            timeout_seconds=timeout_seconds,
        )

    return ExecutorNetworkPathRouter(
        executor_profile=executor_profile,
        timeout_seconds=timeout_seconds,
        transport_factory=create_transport,
    )


class _ProductPortalAdapterRegistry:
    """Keep provider capability facts while moving Product execution to the Mac host."""

    def __init__(self, factory: ModelAccessAdapterFactory) -> None:
        self._factory = factory

    def describe(
        self, adapter_id: str, *, provider: str, model: str
    ) -> ModelAccessAdapterDescriptor:
        descriptor = self._factory.describe(
            adapter_id, provider=provider, model=model
        )
        if provider == "mock":
            return descriptor
        return ModelAccessAdapterDescriptor(
            **{
                **descriptor.model_dump(),
                "execution_host_profile": EXECUTOR_NETWORK_PROFILE,
                "execution_boundary": "private_network_https",
                "authentication_scheme": "executor_path_authentication",
            }
        )


def _product_adapter_id(
    provider: str,
    model: str,
    *,
    factory: ModelAccessAdapterFactory,
    model_kind: str = "chat",
) -> str:
    """Resolve only a declared model adapter, preferring its Mac-path binding."""
    model_descriptor = next(
        (
            descriptor
            for descriptor in load_models().values()
            if descriptor.provider == provider
            and descriptor.model == model
            and descriptor.kind == model_kind
        ),
        None,
    )
    if model_descriptor is not None:
        remote_allowed = tuple(
            adapter_id
            for adapter_id in model_descriptor.allowed_transports
            if adapter_id in _REMOTE_EXECUTOR_ADAPTERS
        )
        if len(remote_allowed) > 1:
            raise LLMRouteError("Product model has ambiguous Mac portal adapters")
        if remote_allowed:
            return remote_allowed[0]
    return factory.default_adapter_id(provider)


def _capability_intersection(
    declared: ModelCapabilities, discovered: ModelCapabilities
) -> ModelCapabilities:
    return ModelCapabilities(
        structured_output=declared.structured_output and discovered.structured_output,
        native_tools=declared.native_tools and discovered.native_tools,
        system_prompt_channel=(
            declared.system_prompt_channel and discovered.system_prompt_channel
        ),
        deterministic_execution=(
            declared.deterministic_execution and discovered.deterministic_execution
        ),
        embedding_dimension=discovered.embedding_dimension,
    )


def _latest_product_catalog_target(
    selected: LLMRoute,
    *,
    adapter_id: str,
    intent: LLMTaskIntent,
    remote_transport: ExecutorNetworkPathRouter | CodexRemoteTransport | None,
    catalog_cache: CatalogCache,
):
    """Select only within an explicitly registered Product model family."""
    if adapter_id not in _REMOTE_EXECUTOR_ADAPTERS or selected.provider != "openai":
        return None
    models = load_models()
    pinned = next(
        (
            model
            for model in models.values()
            if model.provider == selected.provider and model.model == selected.model
        ),
        None,
    )
    if (
        pinned is None
        or not pinned.selection_group
        or adapter_id not in pinned.allowed_transports
    ):
        return None
    accepted_models = tuple(
        sorted(
            model.model
            for model in models.values()
            if model.provider == selected.provider
            and model.kind == "chat"
            and model.selection_group == pinned.selection_group
            and adapter_id in model.allowed_transports
        )
    )
    if selected.model not in accepted_models:
        raise ValueError("pinned Product model is not in its declared selection group")
    if remote_transport is None:
        raise CatalogError("catalog_unavailable")

    def load_snapshot(_now):
        try:
            request = ProductCatalogRequest(
                provider=selected.provider,
                model=selected.model,
            )
            product_catalog = getattr(remote_transport, "product_catalog", None)
            catalog_response = (
                product_catalog(request)
                if callable(product_catalog)
                else remote_transport.catalog(request)
            )
            snapshot = catalog_response.snapshot
        except Exception as exc:
            code = getattr(exc, "code", None)
            if code == "catalog_unavailable":
                catalog_code = "catalog_unavailable"
            elif code in {
                "PATH_UNAVAILABLE",
                "CONNECT_TIMEOUT",
                "PREFLIGHT_TIMEOUT",
                "PATH_AUTHENTICATION_FAILED",
            }:
                catalog_code = "catalog_unavailable"
            elif code == "catalog_auth_failed":
                catalog_code = "catalog_auth_failed"
            elif code == "catalog_stale":
                catalog_code = "catalog_stale"
            else:
                # A malformed, oversized, or transport-mismatched response is
                # invalid data, not an outage that can authorize stale routing.
                catalog_code = "catalog_invalid"
            raise CatalogError(catalog_code) from exc
        if snapshot.transport_id != "codex_cli":
            raise CatalogError("catalog_invalid")
        return snapshot

    snapshot = catalog_cache.get(
        provider=selected.provider,
        transport_id="codex_cli",
        loader=load_snapshot,
    )
    policy = CatalogSelectionPolicy(
        provider=selected.provider,
        accepted_models=accepted_models,
        accepted_transports=("codex_cli",),
        required_capabilities=ModelCapabilityRequirements(
            structured_output=intent.json_schema_required,
            native_tools=intent.native_tools_required,
            literal_system_role_required=intent.literal_system_role_required,
            deterministic_execution=intent.determinism_required,
        ),
        reasoning_effort=selected.reasoning_effort or "low",
        pinned_model=selected.model,
    )
    return snapshot, select_latest_compatible(snapshot, policy)


def _exact_product_model_route(
    intent: LLMTaskIntent, model_id: str, *, factory: ModelAccessAdapterFactory,
    transport_id: str | None = None
) -> LLMRoute:
    """Resolve one explicit model only through Product's declared registry."""
    matches = [
        descriptor
        for descriptor in load_models().values()
        if descriptor.kind == "chat" and descriptor.model == model_id
    ]
    if len(matches) != 1:
        raise LLMRouteError(
            "explicit model must resolve to exactly one declared Product chat model"
        )
    descriptor = matches[0]
    allowed = tuple(descriptor.allowed_transports) or (
        factory.default_adapter_id(descriptor.provider),
    )
    default_adapter = factory.default_adapter_id(descriptor.provider)
    if transport_id is not None:
        admitted = allowed + tuple(descriptor.explicit_eval_transports) if intent.task_kind == "eval" else allowed
        if transport_id not in admitted:
            raise LLMRouteError("explicit transport is not allowed for the Product model")
        adapter_id = transport_id
    elif default_adapter in allowed:
        adapter_id = default_adapter
    elif len(allowed) == 1:
        adapter_id = allowed[0]
    else:
        raise LLMRouteError(
            "explicit Product model has multiple allowed transports and no declared default"
        )
    try:
        factory.describe(adapter_id, provider=descriptor.provider, model=model_id)
    except ValueError as exc:
        raise LLMRouteError("explicit Product model transport is not declared") from exc
    return LLMRoute(
        provider=descriptor.provider,
        model=model_id,
        mode="chat",
        reason=f"explicit-model:{intent.task_kind}",
        transport_id=adapter_id,
    )


def _global_route_enforcement_active() -> bool:
    if os.getenv("LLM_FORCE_PROVIDER", "").strip() or os.getenv(
        "LLM_FORCE_MODEL", ""
    ).strip():
        return True
    return os.getenv("LLM_PROVIDER_ENFORCE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _matches_enforced_route(enforced: LLMRoute, selected: LLMRoute) -> bool:
    if (enforced.provider, enforced.model) != (selected.provider, selected.model):
        return False
    if enforced.transport_id and enforced.transport_id != selected.transport_id:
        return False
    if (
        enforced.reasoning_effort
        and enforced.reasoning_effort != selected.reasoning_effort
    ):
        return False
    return True


def _resolve_product_access_route(
    intent: LLMTaskIntent,
    selected: LLMRoute,
    *,
    adapter_factory: ModelAccessAdapterFactory | None = None,
    remote_transport: ExecutorNetworkPathRouter | CodexRemoteTransport | None = None,
    catalog_cache: CatalogCache | None = None,
    fallback_requirement: FallbackRequirement = "fallback_forbidden",
    fallback_provenance: FallbackProvenance | None = None,
    allow_catalog_promotion: bool = True,
    allow_explicit_eval_transport: bool = False,
) -> ModelAccessRoute:
    factory = adapter_factory or _adapter_factory()
    adapter_id = selected.transport_id or _product_adapter_id(
        selected.provider,
        selected.model,
        factory=factory,
    )
    if adapter_id == "codex_cli":
        raise LLMRouteError(
            "Product chat facade cannot execute the local codex_cli transport"
        )
    product_descriptor = next(
        (
            model
            for model in load_models().values()
            if model.kind == "chat"
            and model.provider == selected.provider
            and model.model == selected.model
        ),
        None,
    )
    if (
        product_descriptor is not None
        and product_descriptor.allowed_transports
        and adapter_id not in product_descriptor.allowed_transports
        and not (
            allow_explicit_eval_transport
            and intent.task_kind == "eval"
            and adapter_id in product_descriptor.explicit_eval_transports
        )
    ):
        raise LLMRouteError("selected transport is not allowed for the Product model")
    # Validate the pinned target before any catalog discovery. A catalog adapter
    # must not become an oracle for an unknown provider/model/transport pair.
    pinned_adapter = factory.describe(
        adapter_id, provider=selected.provider, model=selected.model
    )
    catalog_result = (
        _latest_product_catalog_target(
            selected,
            adapter_id=adapter_id,
            intent=intent,
            remote_transport=remote_transport,
            catalog_cache=catalog_cache or _PRODUCT_CATALOG_CACHE,
        )
        if allow_catalog_promotion
        else None
    )
    selected_model = selected.model
    catalog_snapshot = None
    discovered_capabilities = None
    if catalog_result is not None:
        catalog_snapshot, catalog_target = catalog_result
        selected_model = catalog_target.model
        discovered_capabilities = catalog_target.capabilities
    descriptor = (
        pinned_adapter
        if selected_model == selected.model
        else factory.describe(adapter_id, provider=selected.provider, model=selected_model)
    )
    reasoning_effort = selected.reasoning_effort or "low"
    access_intent = ModelAccessIntent(
        capability_tier=(
            "frontier"
            if intent.risk == "high" or intent.complexity_hint == "high"
            else "standard"
        ),
        reasoning_effort=reasoning_effort,
        determinism_required=intent.determinism_required,
        output_schema_ref=("product.inline_output_schema" if intent.json_schema_required else None),
        independence="none",
        fallback_requirement=fallback_requirement,
        side_effect_class="model_completion",
    )
    request = ModelResolutionRequest(
        intent=access_intent,
        role_profile=intent.task_kind,
        resolution_group_id=f"product.{intent.task_kind}",
        requirements=ModelCapabilityRequirements(
            structured_output=intent.json_schema_required,
            native_tools=intent.native_tools_required,
            literal_system_role_required=intent.literal_system_role_required,
            deterministic_execution=intent.determinism_required,
        ),
    )
    selected_target = ResolvedModelAccess(
        request=request,
        provider=selected.provider,
        model=selected_model,
        adapter_id=adapter_id,
        effective_identity=f"{selected.provider}/{selected_model}",
        capabilities=(
            _capability_intersection(
                descriptor.supported_capabilities, discovered_capabilities
            )
            if discovered_capabilities is not None
            else descriptor.supported_capabilities
        ),
        credential_identity_ref=(
            "executor.credential-ref"
            if selected.provider != "mock"
            else _credential_ref(descriptor.authentication_scheme, selected.provider)
        ),
        degraded=selected.degraded,
        degradation_reason=(
            "policy_selected_compatible_route" if selected.degraded else None
        ),
        fallback_provenance=fallback_provenance or FallbackProvenance(),
    )
    capability_provenance = CapabilityProvenance(
        source=(
            "catalog_snapshot" if catalog_snapshot is not None else "adapter_attestation"
        ),
        source_ref=(
            catalog_snapshot.snapshot_ref if catalog_snapshot is not None else adapter_id
        ),
    )
    profile = ModelAccessProfile(
        profile_id="profile.product_runtime",
        runtime="product",
        channel="runtime",
        consumer="product.chat",
        caller_profile="profile.product_chat_client",
        catalog_snapshot_ref=(
            catalog_snapshot.snapshot_ref if catalog_snapshot is not None else None
        ),
        catalog_snapshot_hash=(
            catalog_snapshot.snapshot_hash if catalog_snapshot is not None else None
        ),
        capability_provenance=capability_provenance,
    )
    return ModelAccessRouter(
        adapter_registry=_ProductPortalAdapterRegistry(factory)
    ).resolve(
        request,
        resolver=_SelectedProductTarget(selected_target),
        profile=profile,
    )


def _product_completion_request(
    route: ModelAccessRoute,
    pack: dict[str, Any],
    *,
    response_format: dict[str, Any] | str | None,
    max_output_tokens: int | None = None,
) -> ProductCompletionRequest:
    output_schema: dict[str, Any] | None
    if isinstance(response_format, dict):
        output_schema = response_format
    elif response_format == "json":
        output_schema = {"type": "object"}
    else:
        output_schema = None
    if not _is_remote_executor_route(route):
        raise ValueError("selected route is not bound to the Product portal")
    reasoning_effort = (
        route.request.intent.reasoning_effort if route.provider == "openai" else None
    )
    return ProductCompletionRequest(
        provider=route.provider,
        model=route.model,
        reasoning_effort=reasoning_effort,
        capability_intent=CompletionCapabilityIntent(
            structured_output=output_schema is not None,
            native_tools=route.request.requirements.native_tools,
            literal_system_role_required=(
                route.request.requirements.literal_system_role_required
            ),
            max_output_tokens_required=max_output_tokens is not None,
        ),
        trusted_instructions=str(pack.get("system", "")),
        user_input=str(pack.get("user", "")),
        output_schema=output_schema,
        max_output_tokens=max_output_tokens,
    )


def _product_preflight_request(
    route: ModelAccessRoute,
    *,
    response_format: dict[str, Any] | str | None,
    max_output_tokens: int | None = None,
) -> ProductPreflightRequest:
    completion = _product_completion_request(
        route,
        {"system": "", "user": "preflight"},
        response_format=response_format,
        max_output_tokens=max_output_tokens,
    )
    return ProductPreflightRequest(
        provider=completion.provider,
        model=completion.model,
        reasoning_effort=completion.reasoning_effort,
        capability_intent=completion.capability_intent,
    )


def _bind_product_host_route(
    route: ModelAccessRoute, host_route: CompletionRouteIdentity
) -> ModelAccessRoute:
    if (route.provider, route.model) != (host_route.provider, host_route.model):
        raise LLMRouteError("Mac portal preflight returned a different Product model")
    if host_route.catalog_snapshot_ref is None or host_route.catalog_snapshot_hash is None:
        raise LLMRouteError("Mac portal preflight did not bind a fresh catalog snapshot")
    return ModelAccessRoute(
        **{
            **route.model_dump(),
            "transport_id": host_route.transport_id,
            "catalog_snapshot_ref": host_route.catalog_snapshot_ref,
            "catalog_snapshot_hash": host_route.catalog_snapshot_hash,
            "capability_provenance": {
                "source": "catalog_snapshot",
                "source_ref": host_route.catalog_snapshot_ref,
            },
            "preflight_status": "passed",
            "preflight_failure_code": None,
        }
    )


def _same_route_target(left: LLMRoute, right: LLMRoute) -> bool:
    return (
        left.provider,
        left.model,
        left.transport_id,
        left.reasoning_effort,
    ) == (
        right.provider,
        right.model,
        right.transport_id,
        right.reasoning_effort,
    )


def _explicit_remote_ollama_fallback(
    candidates: list[LLMRoute], *, factory: ModelAccessAdapterFactory
) -> LLMRoute | None:
    """Return only a registry-approved, explicitly remote Ollama alternative."""
    models = load_models()
    for candidate in candidates[1:]:
        if candidate.provider != "ollama":
            continue
        adapter_id = candidate.transport_id or _product_adapter_id(
            candidate.provider,
            candidate.model,
            factory=factory,
        )
        if adapter_id != "ollama_http_tailscale":
            continue
        descriptor = next(
            (
                model
                for model in models.values()
                if model.provider == candidate.provider
                and model.model == candidate.model
                and model.kind == "chat"
            ),
            None,
        )
        if descriptor is None or adapter_id not in descriptor.allowed_transports:
            continue
        return LLMRoute(
            provider=candidate.provider,
            model=candidate.model,
            mode=candidate.mode,
            reason=candidate.reason,
            degraded=True,
            timeout_seconds=candidate.timeout_seconds,
            temperature=candidate.temperature,
            transport_id=adapter_id,
            reasoning_effort=None,
        )
    return None


def _preflight_transport_observation(receipt: Any) -> dict[str, str]:
    """Reduce a private path receipt to provider- and path-neutral status."""
    if receipt is None:
        return {"status": "unknown", "reason_code": "transport_unknown"}
    if getattr(receipt, "failure_before_selection", None):
        return {
            "status": "degraded",
            "reason_code": "transport_fallback_used",
        }
    return {"status": "available", "reason_code": "transport_reachable"}


def _select_and_bind_product_preflight(
    primary: ModelAccessRoute,
    *,
    fallback: ModelAccessRoute | None,
    remote_transport: ExecutorNetworkPathRouter,
    response_format: dict[str, Any] | str | None,
    max_output_tokens: int | None,
) -> tuple[ModelAccessRoute, Any]:
    primary_request = _product_preflight_request(
        primary,
        response_format=response_format,
        max_output_tokens=max_output_tokens,
    )
    fallback_request = None
    if fallback is not None:
        fallback_request = ProductPreflightRequest(
            provider=fallback.provider,
            model=fallback.model,
            capability_intent=primary_request.capability_intent,
        )
    allow_fallback = bool(
        fallback is not None
        and not primary.fallback_provenance.used
        and primary.adapter_id == "codex_cli_tailscale"
        and fallback.adapter_id == "ollama_http_tailscale"
    )
    selection = select_product_preflight_route(
        primary_request,
        fallback_request=fallback_request,
        fallback_requirement=primary.request.intent.fallback_requirement,
        policy_authority="profile.product_runtime",
        transport=remote_transport,
        allow_codex_to_ollama_fallback=allow_fallback,
    )
    selected = primary
    if selection.fallback_provenance.used:
        assert fallback is not None
        selected = _bind_product_host_route(
            fallback, selection.response.route
        )
        selected = ModelAccessRoute(
            **{
                **selected.model_dump(),
                "fallback_provenance": selection.fallback_provenance,
            }
        )
        return selected, selection
    return _bind_product_host_route(selected, selection.response.route), selection


@dataclass
class ChatClient:
    route: LLMRoute
    model_access_route: ModelAccessRoute | None = None
    last_execution_route: CompletionRouteIdentity | None = None
    remote_transport: ExecutorNetworkPathRouter | CodexRemoteTransport | None = None
    _preflight_transport_observation: dict[str, str] | None = field(
        default=None, repr=False, compare=False
    )
    _intent: LLMTaskIntent | None = field(default=None, repr=False, compare=False)
    _output_limit_route_resolved: bool = field(default=False, repr=False, compare=False)
    _adapter_runtime_config: AdapterRuntimeConfig | None = field(
        default=None, repr=False, compare=False
    )
    _fallback_access_route: ModelAccessRoute | None = field(
        default=None, repr=False, compare=False
    )
    _fallback_route: LLMRoute | None = field(default=None, repr=False, compare=False)

    @property
    def preflight_transport_observation(self) -> dict[str, str] | None:
        """Return path reachability status without exposing the selected path."""
        if self._preflight_transport_observation is None:
            return None
        return dict(self._preflight_transport_observation)

    def _resolve_output_limit_route(self, max_tokens: int) -> None:
        """Preflight the caller's token cap without re-resolving its bound model."""
        route = self.model_access_route
        if route is None or self._intent is None:
            raise ValueError("a remote output-token limit needs its bound Product route")
        transport = self.remote_transport
        owns_transport = transport is None
        if transport is None:
            transport = _new_executor_path_router(
                executor_profile=route.execution_host_profile,
                timeout_seconds=self.route.timeout_seconds or 1_260.0,
            )
        try:
            bound_route, selection = _select_and_bind_product_preflight(
                route,
                fallback=(
                    self._fallback_access_route
                    if not route.fallback_provenance.used
                    else None
                ),
                remote_transport=transport,
                response_format=(
                    {"type": "object"} if self._intent.json_schema_required else None
                ),
                max_output_tokens=max_tokens,
            )
            discard_receipt = getattr(transport, "discard_product_path_receipt", None)
            if callable(discard_receipt):
                discard_receipt(selection.executor_path_receipt)
            self.model_access_route = bound_route
            if selection.fallback_provenance.used:
                assert self._fallback_route is not None
                self.route = LLMRoute.from_model_access_route(
                    bound_route,
                    mode=self._fallback_route.mode,
                    reason=self._fallback_route.reason,
                    timeout_seconds=self._fallback_route.timeout_seconds,
                    temperature=self._fallback_route.temperature,
                )
            else:
                self.route = LLMRoute.from_model_access_route(
                    bound_route,
                    mode=self.route.mode,
                    reason=self.route.reason,
                    embedding_identity=self.route.embedding_identity,
                    timeout_seconds=self.route.timeout_seconds,
                    temperature=self.route.temperature,
                )
            self._output_limit_route_resolved = True
        finally:
            if owns_transport:
                transport.close()

    def chat(
        self,
        name: str,
        pack: dict[str, Any],
        *,
        agent: str | None = None,
        kind: str | None = None,
        trace_id: str | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | str | None = None,
        usage_observer: Callable[[dict[str, Any]], None] | None = None,
        record_content: bool = True,
    ) -> str:
        if (
            self.model_access_route is not None
            and _is_remote_executor_route(self.model_access_route)
            and max_tokens is not None
            and not self._output_limit_route_resolved
        ):
            self._resolve_output_limit_route(max_tokens)

        if self.model_access_route is not None and _is_remote_executor_route(
            self.model_access_route
        ):
            route = self.model_access_route
            transport = self.remote_transport
            owns_transport = transport is None
            if transport is None:
                transport = _new_executor_path_router(
                    executor_profile=route.execution_host_profile,
                    timeout_seconds=self.route.timeout_seconds or 1_260.0,
                )
            try:
                if route.request.requirements.structured_output and not (
                    isinstance(response_format, dict) or response_format == "json"
                ):
                    raise ValueError(
                        "the selected route requires a structured-output schema"
                    )
                if (
                    (isinstance(response_format, dict) or response_format == "json")
                    and not route.capabilities.structured_output
                ):
                    raise ValueError(
                        "the selected route does not attest structured output"
                    )
                bound_route, selection = _select_and_bind_product_preflight(
                    route,
                    fallback=(
                        self._fallback_access_route
                        if not route.fallback_provenance.used
                        else None
                    ),
                    remote_transport=transport,
                    response_format=response_format,
                    max_output_tokens=max_tokens,
                )
                if selection.fallback_provenance.used:
                    assert self._fallback_route is not None
                    self.route = LLMRoute.from_model_access_route(
                        bound_route,
                        mode=self._fallback_route.mode,
                        reason=self._fallback_route.reason,
                        timeout_seconds=self._fallback_route.timeout_seconds,
                        temperature=self._fallback_route.temperature,
                    )
                else:
                    self.route = LLMRoute.from_model_access_route(
                        bound_route,
                        mode=self.route.mode,
                        reason=self.route.reason,
                        embedding_identity=self.route.embedding_identity,
                        timeout_seconds=self.route.timeout_seconds,
                        temperature=self.route.temperature,
                    )
                self.model_access_route = bound_route
                request = _product_completion_request(
                    bound_route,
                    pack,
                    response_format=response_format,
                    max_output_tokens=max_tokens,
                )
                complete_selected = getattr(
                    transport, "complete_product_selected_path", None
                )
                self.last_execution_route = None
                if callable(complete_selected):
                    response = complete_selected(
                        request,
                        receipt=selection.executor_path_receipt,
                    )
                else:
                    response = transport.complete(request)
                if not response.route.same_execution_target(selection.response.route):
                    raise RemoteCompletionError(
                        "executor_route_mismatch", indeterminate=True
                    )
                self.last_execution_route = response.route
                if usage_observer is not None:
                    usage = response.usage
                    usage_observer(
                        {
                            "model": usage.model if usage is not None else None,
                            "usage": (
                                usage.usage.model_dump(mode="json", exclude_none=True)
                                if usage is not None and usage.usage is not None
                                else None
                            ),
                            "service_tier": (
                                usage.service_tier if usage is not None else None
                            ),
                        }
                    )
                return response.content
            finally:
                if owns_transport:
                    transport.close()
        evidence_options: dict[str, Any] = {}
        if usage_observer is not None or not record_content:
            evidence_options = {"usage_observer": usage_observer, "record_content": record_content}
        return call_llm(
            name,
            pack,
            agent=agent,
            kind=kind,
            trace_id=trace_id,
            **evidence_options,
            provider_override=self.route.provider,
            model_override=self.route.model,
            timeout_seconds=self.route.timeout_seconds,
            temperature=self.route.temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            base_url_override=(
                self._adapter_runtime_config.base_url
                if self._adapter_runtime_config is not None
                else None
            ),
            api_key_override=(
                self._adapter_runtime_config.api_key
                if self._adapter_runtime_config is not None
                else None
            ),
        )


def get_chat_client(
    intent: LLMTaskIntent,
    *,
    model_id: str | None = None,
    transport_id: str | None = None,
    adapter_runtime_config: AdapterRuntimeConfig | None = None,
) -> ChatClient:
    """Bind a Product intent to its temporary route behind one thin facade."""
    if transport_id is not None and (model_id is None or intent.task_kind != "eval"):
        raise LLMRouteError("explicit transport requires an exact evaluation model")
    if model_id is None:
        return get_chat_client_for_route(
            intent, adapter_runtime_config=adapter_runtime_config
        )
    selected = _exact_product_model_route(
        intent, model_id, factory=_adapter_factory(), transport_id=transport_id
    )
    return get_chat_client_for_route(
        intent,
        selected_route=selected,
        adapter_runtime_config=adapter_runtime_config,
        allow_catalog_promotion=False,
        allow_fallback=intent.task_kind != "eval",
        allow_explicit_eval_transport=transport_id is not None,
    )


def get_chat_client_for_route(
    intent: LLMTaskIntent,
    *,
    selected_route: LLMRoute | None = None,
    max_output_tokens: int | None = None,
    adapter_runtime_config: AdapterRuntimeConfig | None = None,
    allow_catalog_promotion: bool = True,
    allow_fallback: bool = True,
    allow_explicit_eval_transport: bool = False,
) -> ChatClient:
    """Bind one already-resolved Product policy route to the shared access facade."""
    if allow_explicit_eval_transport and (intent.task_kind != "eval" or selected_route is None):
        raise LLMRouteError("evaluation-only admission requires an explicit eval route")
    router = LLMRouter()
    route_candidates = getattr(router, "candidate_routes", None)
    candidates = route_candidates(intent) if route_candidates is not None else []
    selected = selected_route or (candidates[0] if candidates else router.route(intent))
    if selected_route is not None and candidates and not _same_route_target(
        candidates[0], selected_route
    ):
        if _global_route_enforcement_active() and not _matches_enforced_route(
            candidates[0], selected_route
        ):
            raise LLMRouteError(
                "explicit Product route conflicts with active global route enforcement"
            )
        candidates = [selected_route]
    elif not candidates:
        candidates = [selected]

    factory = _adapter_factory()
    if selected.transport_id == "codex_cli":
        raise LLMRouteError(
            "Product chat facade cannot execute the local codex_cli transport"
        )
    selected_adapter_id = selected.transport_id or _product_adapter_id(
        selected.provider,
        selected.model,
        factory=factory,
    )
    fallback = (
        _explicit_remote_ollama_fallback(candidates, factory=factory)
        if allow_fallback and selected_adapter_id == "codex_cli_tailscale"
        else None
    )
    remote_transport = None
    owns_remote_transport = False
    if selected.provider != "mock":
        remote_transport = _new_executor_path_router(
            executor_profile=EXECUTOR_NETWORK_PROFILE,
            timeout_seconds=selected.timeout_seconds or 1_260.0,
        )
        owns_remote_transport = True
    fallback_access_route = None
    transport_observation = None
    try:
        model_access_route = _resolve_product_access_route(
            intent,
            selected,
            adapter_factory=factory,
            remote_transport=remote_transport,
            fallback_requirement=(
                "fallback_policy_selected" if fallback is not None else "fallback_forbidden"
            ),
            allow_catalog_promotion=allow_catalog_promotion,
            allow_explicit_eval_transport=allow_explicit_eval_transport,
        )
        if remote_transport is not None:
            if fallback is not None:
                fallback_access_route = _resolve_product_access_route(
                    intent,
                    fallback,
                    adapter_factory=factory,
                    fallback_requirement="fallback_policy_selected",
                    allow_catalog_promotion=allow_catalog_promotion,
                )
            model_access_route, selection = _select_and_bind_product_preflight(
                model_access_route,
                fallback=fallback_access_route,
                remote_transport=remote_transport,
                response_format=(
                    {"type": "object"} if intent.json_schema_required else None
                ),
                max_output_tokens=max_output_tokens,
            )
            transport_observation = _preflight_transport_observation(
                selection.executor_path_receipt
            )
            discard_receipt = getattr(
                remote_transport, "discard_product_path_receipt", None
            )
            if callable(discard_receipt):
                discard_receipt(selection.executor_path_receipt)
        route = LLMRoute.from_model_access_route(
            model_access_route,
            mode=(
                fallback.mode
                if model_access_route.fallback_provenance.used and fallback
                else selected.mode
            ),
            reason=(
                fallback.reason
                if model_access_route.fallback_provenance.used and fallback
                else selected.reason
            ),
            embedding_identity=selected.embedding_identity,
            timeout_seconds=(
                fallback.timeout_seconds
                if model_access_route.fallback_provenance.used and fallback
                else selected.timeout_seconds
            ),
            temperature=(
                fallback.temperature
                if model_access_route.fallback_provenance.used and fallback
                else selected.temperature
            ),
        )
        return ChatClient(
            route=route,
            model_access_route=model_access_route,
            _preflight_transport_observation=(
                transport_observation if remote_transport is not None else None
            ),
            _intent=intent,
            _output_limit_route_resolved=max_output_tokens is not None,
            _adapter_runtime_config=adapter_runtime_config,
            _fallback_access_route=fallback_access_route,
            _fallback_route=fallback,
        )
    finally:
        if (
            owns_remote_transport
            and remote_transport is not None
        ):
            remote_transport.close()


def get_embeddings_client(intent: LLMTaskIntent) -> EmbeddingClientProtocol:
    router = LLMRouter()
    route = router.route(intent)
    identity = route.embedding_identity
    if identity is None:
        raise LLMRouteError("Product embedding route has no resolved identity")
    return _product_embedding_client_for_identity(identity, router=router)


def get_product_embedding_client(
    *,
    profile: str = "default",
    override_model: str | None = None,
    override_provider: str | None = None,
) -> EmbeddingClientProtocol:
    """Resolve a Product embedding client without exposing local provider execution.

    The ordinary default follows the clone-local Product routing profile. Explicit
    legacy profile/model overrides are first resolved to one identity, then validated
    against the shared registry before the Mac portal is used.
    """
    if (
        (profile or "default").strip().lower() == "default"
        and override_model is None
        and override_provider is None
    ):
        return get_embeddings_client(
            LLMTaskIntent(task_kind="embed", strict_identity_required=True)
        )
    normalized_profile = (profile or "default").strip().lower()
    if normalized_profile not in {"default", "deterministic", "test", "offline"}:
        bundle = get_settings_bundle()
        embedding_profiles = getattr(bundle, "embedding_profiles", None)
        declared_profiles = {
            str(name).strip().lower()
            for name in getattr(embedding_profiles, "profiles", {})
        }
        if normalized_profile not in declared_profiles:
            raise LLMRouteError("Product embedding profile is not declared")
    identity = resolve_embedding_identity(
        profile=profile,
        override_model=override_model,
        override_provider=override_provider,
    )
    return get_product_embedding_client_for_identity(identity)


def get_product_embedding_client_for_identity(
    identity: EmbeddingIdentity,
) -> EmbeddingClientProtocol:
    """Use the Mac portal for one already-selected Product embedding identity."""
    return _product_embedding_client_for_identity(identity, router=LLMRouter())


def _product_embedding_client_for_identity(
    identity: EmbeddingIdentity,
    *,
    router: LLMRouter,
) -> EmbeddingClientProtocol:
    if identity.provider in {"mock", "deterministic"}:
        return get_embedding_client(resolved_identity=identity)

    descriptor = next(
        (
            model
            for model in load_models().values()
            if model.kind == "embedding"
            and model.provider == identity.provider
            and model.model == identity.model
        ),
        None,
    )
    if descriptor is None:
        raise LLMRouteError(
            "Product embedding route must resolve to a declared registry model"
        )
    if descriptor.dims is not None and descriptor.dims != identity.dim:
        raise LLMRouteError(
            "Product embedding identity dimension conflicts with its registry model"
        )
    adapter_factory = _adapter_factory()
    try:
        expected_transport = adapter_factory.adapter_id_for(
            identity.provider,
            descriptor.model,
            model_kind="embedding",
        )
        adapter_factory.describe(
            expected_transport,
            provider=identity.provider,
            model=descriptor.model,
            model_kind="embedding",
        )
    except (KeyError, ValueError) as exc:
        raise LLMRouteError(
            "Product embedding route is not declared by the Mac portal adapter registry"
        ) from exc

    remote_transport = _new_executor_path_router(
        executor_profile=EXECUTOR_NETWORK_PROFILE,
        timeout_seconds=(
            getattr(
                getattr(getattr(router, "_settings", None), "llm_routing", None),
                "timeout_seconds",
                None,
            )
            or 1_260.0
        ),
    )
    return _RemoteProductEmbeddingClient(
        identity=identity,
        request_model=descriptor.model,
        expected_transport=expected_transport,
        remote_transport=remote_transport,
    )


class _RemoteProductEmbeddingClient:
    """Embedding client whose provider calls terminate only at the Mac Product API."""

    def __init__(
        self,
        *,
        identity: EmbeddingIdentity,
        request_model: str,
        expected_transport: str,
        remote_transport: ExecutorNetworkPathRouter,
    ) -> None:
        self.identity = identity
        self._request_model = request_model
        self._expected_transport = expected_transport
        self._remote_transport = remote_transport
        self._finalizer = weakref.finalize(self, remote_transport.close)
        self._route_provenance: dict[str, str] | None = None

    @property
    def route_provenance(self) -> dict[str, str] | None:
        """Latest safe route evidence returned by the Mac host; contains no secrets."""
        return dict(self._route_provenance) if self._route_provenance else None

    def close(self) -> None:
        if self._finalizer.alive:
            self._finalizer()

    def _embed_one(self, text: str) -> tuple[float, ...]:
        request = ProductEmbeddingRequest(
            provider=self.identity.provider,
            model=self._request_model,
            dimensions=self.identity.dim,
            input_text=text,
        )
        path_result = self._remote_transport.embed_product(request)
        response = getattr(path_result, "response", path_result)
        route = response.route
        if (
            route.provider != self.identity.provider
            or route.model != self._request_model
            or route.transport_id != self._expected_transport
            or response.dimensions != self.identity.dim
            or len(response.vector) != self.identity.dim
        ):
            raise RemoteEmbeddingError(
                "embedding_route_or_dimension_mismatch", indeterminate=True
            )
        self._route_provenance = {
            "provider": route.provider,
            "model": route.model,
            "transport_id": route.transport_id,
            "execution_host": EXECUTOR_NETWORK_PROFILE,
            "selected_path_profile": str(
                getattr(path_result, "selected_path_profile", "unknown")
            ),
            "catalog_snapshot_ref": str(route.catalog_snapshot_ref or ""),
            "catalog_snapshot_hash": str(route.catalog_snapshot_hash or ""),
            "fallback_phase": "none",
        }
        assert_embed_dim(response.vector, expected=self.identity.dim)
        return tuple(response.vector)

    def embed_text(self, text: str) -> list[float]:
        if not text:
            return [0.0 for _ in range(self.identity.dim)]
        chunks = _chunk_for_embedding(text, _embedding_max_input_chars())
        vectors = [self._embed_one(chunk) for chunk in chunks]
        pooled = list(_mean_pool(vectors, self.identity.dim))
        return l2_normalize(pooled) if self.identity.normalize else pooled

    def embed_texts(self, texts) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]

    def embed_batches(self, texts, batch_size: int = 32):
        batch: list[str] = []
        for text in texts:
            batch.append(text)
            if len(batch) >= batch_size:
                yield self.embed_texts(batch)
                batch = []
        if batch:
            yield self.embed_texts(batch)


def describe_default_routes() -> dict[str, dict[str, str]]:
    router = LLMRouter()
    intents = [intent for intent in router.verification_intents() if intent.task_kind in {"embed", "decide", "plan"}]
    routes = router.default_routes(intents)
    return {
        key: {
            "provider": route.provider,
            "model": route.model,
            "transport_id": (
                route.transport_id
                or (
                    _adapter_factory().default_adapter_id(route.provider)
                    if route.mode != "embeddings"
                    else ""
                )
            ),
            "reasoning_effort": route.reasoning_effort or "",
            "mode": route.mode,
            "reason": route.reason,
            "degraded": str(route.degraded),
        }
        for key, route in routes.items()
    }


def describe_default_route_policies() -> dict[str, dict[str, object]]:
    router = LLMRouter()
    policies = router.describe_routes(router.capability_health_intents())
    factory = _adapter_factory()
    for task_kind, policy in policies.items():
        if task_kind == "embed":
            continue
        for key in ("effective", "preferred"):
            route = policy.get(key)
            if not isinstance(route, dict):
                continue
            provider = str(route.get("provider") or "")
            if provider:
                route["transport_id"] = route.get("transport_id") or factory.default_adapter_id(provider)
                route["reasoning_effort"] = route.get("reasoning_effort") or "low"
    return policies


__all__ = [
    "AdapterRuntimeConfig",
    "LLMTaskIntent",
    "LLMRoute",
    "LLMBackendTimeout",
    "ChatClient",
    "get_chat_client",
    "get_chat_client_for_route",
    "get_embeddings_client",
    "describe_default_routes",
    "describe_default_route_policies",
]
