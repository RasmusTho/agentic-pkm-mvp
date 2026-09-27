"""Strict, offline validation for the sanitized MARR macOS acceptance receipt."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.model_access.remote_contract import CompletionCapabilityIntent


_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,127}$")
_SENSITIVE_MODEL_ID = re.compile(
    r"(?:[a-z][a-z0-9+.-]*://|@|\bsk-(?:ant-)?[a-z0-9_-]{8,}\b|"
    r"\b(?:bearer|api[_-]?key|token|secret)\s*[:=])",
    re.IGNORECASE,
)
_CODEX_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.]+)?$")

PathProfile = Literal["ygg_vlan_primary", "tailscale_fallback"]
PathFailureCode = Literal[
    "PATH_UNAVAILABLE",
    "CONNECT_TIMEOUT",
    "PREFLIGHT_TIMEOUT",
    "PATH_AUTHENTICATION_FAILED",
]
CapabilityId = Literal[
    "text_generation",
    "structured_output",
    "native_tools",
    "system_prompt_channel",
    "deterministic_execution",
    "max_output_tokens",
]
CapabilityStatus = Literal["available", "degraded", "unavailable", "unknown"]
CapabilityFreshness = Literal["fresh", "stale", "unknown"]
_ERROR_CAPABILITY: dict[str, CapabilityId] = {
    "native_tools_unavailable": "native_tools",
    "structured_output_unavailable": "structured_output",
    "output_token_limit_unavailable": "max_output_tokens",
}
MissingPrerequisite = Literal[
    "vlan_path_unavailable",
    "tailscale_path_unconfigured",
    "executor_auth_unavailable",
    "codex_cli_unavailable",
    "catalog_snapshot_unavailable",
    "required_capability_unavailable",
    "loopback_backend_unverified",
    "product_authorization_unavailable",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AcceptanceRouteIdentity(_StrictModel):
    """The exact Codex route already selected by Product policy."""

    provider: Literal["openai"]
    model: str = Field(min_length=1, max_length=128)
    transport_id: Literal["codex_cli"]
    reasoning_effort: Literal["minimal", "low", "medium", "high", "xhigh", "max", "ultra"]
    capability_intent: CompletionCapabilityIntent

    @model_validator(mode="after")
    def _validate_model_id(self) -> "AcceptanceRouteIdentity":
        if not _MODEL_ID.fullmatch(self.model) or _SENSITIVE_MODEL_ID.search(self.model):
            raise ValueError("model identifier is not a safe logical ID")
        return self


class ExpectedAcceptanceRoute(_StrictModel):
    """Independently supplied route and catalog provenance to bind the receipt to."""

    route: AcceptanceRouteIdentity
    catalog_snapshot_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    executor_profile: Literal["product_codex_executor"]
    configured_path_profiles: tuple[PathProfile, ...] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def _validate_expected_profiles(self) -> "ExpectedAcceptanceRoute":
        if self.configured_path_profiles != (
            "ygg_vlan_primary",
            "tailscale_fallback",
        ):
            raise ValueError("expected path profiles must be VLAN-first")
        return self


class PathAuthorization(_StrictModel):
    path_profile: PathProfile
    channel_authorized: bool
    action_authorized: bool


class CapabilityObservation(_StrictModel):
    capability_id: CapabilityId
    status: CapabilityStatus
    freshness: CapabilityFreshness


class FallbackPreflightEvidence(_StrictModel):
    """A successful Tailscale preflight for the same route after typed VLAN failure."""

    route: AcceptanceRouteIdentity
    attempted_path_profiles: tuple[PathProfile, ...] = Field(min_length=2, max_length=2)
    selected_path_profile: Literal["tailscale_fallback"]
    failure_before_selection: PathFailureCode
    preflight_status: Literal["passed"]
    completion_dispatched: Literal[False]

    @model_validator(mode="after")
    def _validate_fallback_order(self) -> "FallbackPreflightEvidence":
        if self.attempted_path_profiles != (
            "ygg_vlan_primary",
            "tailscale_fallback",
        ):
            raise ValueError("fallback preflight must preserve VLAN-first path order")
        return self


class MacOsExecutorAcceptanceReceipt(_StrictModel):
    """Closed v3 receipt shape; no free-form prompt, endpoint, host, or CLI data."""

    receipt_type: Literal["model_access_router.macos_executor_acceptance.v3"]
    status: Literal["passed", "incomplete"]
    route: AcceptanceRouteIdentity
    catalog_snapshot_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    executor_profile: Literal["product_codex_executor"] | None = None
    configured_path_profiles: tuple[PathProfile, ...] = Field(default=(), max_length=2)
    selected_path_profile: PathProfile | None = None
    path_selection_reason: Literal["primary_reachable", "typed_vlan_failure", "not_selected"]
    path_failure_code: PathFailureCode | None = None
    backend_loopback_only: bool | None = None
    path_authorization: tuple[PathAuthorization, ...] = Field(default=(), max_length=2)
    same_product_channel_action_contract: bool | None = None
    fallback_preflight: FallbackPreflightEvidence | None = None
    codex_cli_version: str | None = None
    codex_auth_status: Literal["authenticated", "unauthenticated", "unknown"] | None = None
    required_capability_ids: tuple[CapabilityId, ...] = Field(default=(), max_length=6)
    capability_observations: tuple[CapabilityObservation, ...] = Field(default=(), max_length=6)
    unsupported_capability_rejected_pre_inference: bool | None = None
    unsupported_capability_error_code: (
        Literal[
            "native_tools_unavailable",
            "structured_output_unavailable",
            "literal_system_role_unavailable",
            "output_token_limit_unavailable",
        ]
        | None
    ) = None
    instruction_channel_mapping_id: (
        Literal["codex_developer_instructions_user_prompt_v1"] | None
    ) = None
    ambiguous_completion_no_retry: bool | None = None
    completion_dispatched: bool
    missing_prerequisites: tuple[MissingPrerequisite, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def _validate_receipt_state(self) -> "MacOsExecutorAcceptanceReceipt":
        path_ids = [item.path_profile for item in self.path_authorization]
        if len(path_ids) != len(set(path_ids)):
            raise ValueError("path authorization entries must be unique")
        if len(self.configured_path_profiles) != len(set(self.configured_path_profiles)):
            raise ValueError("configured path profiles must be unique")
        if len(self.required_capability_ids) != len(set(self.required_capability_ids)):
            raise ValueError("required capability IDs must be unique")
        observed_ids = [item.capability_id for item in self.capability_observations]
        if len(observed_ids) != len(set(observed_ids)):
            raise ValueError("capability observations must be unique")

        if self.codex_cli_version is not None and not _CODEX_VERSION.fullmatch(
            self.codex_cli_version
        ):
            raise ValueError("Codex CLI version must be a version token only")

        if self.status == "incomplete":
            if not self.missing_prerequisites or self.completion_dispatched:
                raise ValueError(
                    "incomplete acceptance must name missing prerequisites and not dispatch"
                )
            return self

        if self.missing_prerequisites or not self.completion_dispatched:
            raise ValueError("passed acceptance cannot have missing prerequisites")
        if self.catalog_snapshot_hash is None:
            raise ValueError("passed acceptance requires catalog provenance")
        if self.executor_profile != "product_codex_executor":
            raise ValueError("passed acceptance requires the Product executor profile")
        if self.configured_path_profiles != (
            "ygg_vlan_primary",
            "tailscale_fallback",
        ):
            raise ValueError("passed acceptance requires VLAN-first configured paths")
        if (
            self.selected_path_profile != "ygg_vlan_primary"
            or self.path_selection_reason != "primary_reachable"
            or self.path_failure_code is not None
        ):
            raise ValueError("passed acceptance requires a successful VLAN-primary completion")
        if self.fallback_preflight is None or self.fallback_preflight.route != self.route:
            raise ValueError("passed acceptance requires same-route fallback preflight evidence")
        if self.backend_loopback_only is not True:
            raise ValueError("passed acceptance requires a loopback-only backend")
        if self.same_product_channel_action_contract is not True:
            raise ValueError("both paths must prove the same Product authorization contract")
        if set(path_ids) != {"ygg_vlan_primary", "tailscale_fallback"} or any(
            not item.channel_authorized or not item.action_authorized
            for item in self.path_authorization
        ):
            raise ValueError("both path profiles must prove channel and action authorization")
        if not _CODEX_VERSION.fullmatch(self.codex_cli_version or ""):
            raise ValueError("passed acceptance requires a normalized Codex CLI version")
        if self.codex_auth_status != "authenticated":
            raise ValueError("passed acceptance requires interactive Codex authentication")
        if "text_generation" not in self.required_capability_ids:
            raise ValueError("text_generation must be a required capability")
        expected_capabilities = {"text_generation", "system_prompt_channel"}
        if self.route.capability_intent.structured_output:
            expected_capabilities.add("structured_output")
        if self.route.capability_intent.native_tools:
            expected_capabilities.add("native_tools")
        if self.route.capability_intent.max_output_tokens_required:
            expected_capabilities.add("max_output_tokens")
        if (
            self.route.capability_intent.native_tools
            or self.route.capability_intent.literal_system_role_required
            or self.route.capability_intent.max_output_tokens_required
        ):
            raise ValueError("Codex route cannot satisfy the requested capability intent")
        if set(self.required_capability_ids) != expected_capabilities:
            raise ValueError("required capability IDs must match route intent")
        observations = {item.capability_id: item for item in self.capability_observations}
        native_tools = observations.get("native_tools")
        if native_tools is not None and (
            native_tools.status != "unavailable" or native_tools.freshness != "fresh"
        ):
            raise ValueError("Codex executor must report native tools unavailable")
        if any(
            capability_id not in observations
            or observations[capability_id].status != "available"
            or observations[capability_id].freshness != "fresh"
            for capability_id in self.required_capability_ids
        ):
            raise ValueError("passed acceptance requires fresh required capabilities")
        if self.unsupported_capability_rejected_pre_inference is not True:
            raise ValueError("unsupported capability refusal must be proven before inference")
        if self.unsupported_capability_error_code is None:
            raise ValueError("unsupported capability refusal requires a safe error code")
        denied_capability = _ERROR_CAPABILITY.get(self.unsupported_capability_error_code)
        if denied_capability is not None:
            denied_observation = observations.get(denied_capability)
            if denied_observation is None or (
                denied_observation.status != "unavailable"
                or denied_observation.freshness != "fresh"
            ):
                raise ValueError("unsupported capability refusal must match fresh health")
        if self.instruction_channel_mapping_id != "codex_developer_instructions_user_prompt_v1":
            raise ValueError("passed acceptance requires the versioned instruction mapping")
        if self.ambiguous_completion_no_retry is not True:
            raise ValueError("passed acceptance requires ambiguous-completion no-retry evidence")
        return self


@dataclass(frozen=True)
class ReceiptValidationResult:
    status: Literal["passed", "incomplete"]
    missing_prerequisites: tuple[MissingPrerequisite, ...]


class ReceiptValidationError(RuntimeError):
    """A sanitized validator failure; the receipt payload is never included."""

    def __init__(
        self, code: Literal["receipt_invalid", "expected_route_invalid", "route_mismatch"]
    ):
        self.code = code
        super().__init__(code)


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject ambiguous JSON objects before schema validation can discard keys."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _parse_model(model: type[BaseModel], value: object, *, error_code: str) -> BaseModel:
    try:
        if isinstance(value, (str, bytes, bytearray)):
            json.loads(value, object_pairs_hook=_reject_duplicate_json_keys)
            return model.model_validate_json(value)
        return model.model_validate(value)
    except (TypeError, ValueError, ValidationError, RecursionError):
        raise ReceiptValidationError(error_code) from None  # type: ignore[arg-type]


def validate_acceptance_receipt(
    receipt: object,
    expected_route: object,
) -> ReceiptValidationResult:
    """Validate a sanitized receipt against independent Product route provenance.

    This function is pure: it performs no filesystem writes, host/network probes,
    CLI calls, or inference. All validation failures use payload-free error codes.
    """

    expected = _parse_model(
        ExpectedAcceptanceRoute, expected_route, error_code="expected_route_invalid"
    )
    candidate = _parse_model(MacOsExecutorAcceptanceReceipt, receipt, error_code="receipt_invalid")
    assert isinstance(expected, ExpectedAcceptanceRoute)
    assert isinstance(candidate, MacOsExecutorAcceptanceReceipt)

    if candidate.route != expected.route:
        raise ReceiptValidationError("route_mismatch")
    if (
        candidate.executor_profile is not None
        and candidate.executor_profile != expected.executor_profile
    ):
        raise ReceiptValidationError("route_mismatch")
    if candidate.status == "passed":
        if candidate.configured_path_profiles != expected.configured_path_profiles:
            raise ReceiptValidationError("route_mismatch")
    else:
        ordered_subset = tuple(
            profile
            for profile in expected.configured_path_profiles
            if profile in candidate.configured_path_profiles
        )
        if candidate.configured_path_profiles != ordered_subset:
            raise ReceiptValidationError("route_mismatch")
        missing = set(candidate.missing_prerequisites)
        if (
            (
                "ygg_vlan_primary" not in candidate.configured_path_profiles
                and "vlan_path_unavailable" not in missing
            )
            or (
                "tailscale_fallback" not in candidate.configured_path_profiles
                and "tailscale_path_unconfigured" not in missing
            )
            or (
                "tailscale_fallback" in candidate.configured_path_profiles
                and "tailscale_path_unconfigured" in missing
            )
        ):
            raise ReceiptValidationError("receipt_invalid")
        if (candidate.catalog_snapshot_hash is None) != ("catalog_snapshot_unavailable" in missing):
            raise ReceiptValidationError("receipt_invalid")
    if (
        candidate.fallback_preflight is not None
        and candidate.fallback_preflight.route != expected.route
    ):
        raise ReceiptValidationError("route_mismatch")
    if (
        candidate.catalog_snapshot_hash is not None
        and candidate.catalog_snapshot_hash != expected.catalog_snapshot_hash
    ):
        raise ReceiptValidationError("route_mismatch")
    if (
        candidate.status == "passed"
        and candidate.catalog_snapshot_hash != expected.catalog_snapshot_hash
    ):
        raise ReceiptValidationError("route_mismatch")
    return ReceiptValidationResult(
        status=candidate.status,
        missing_prerequisites=tuple(candidate.missing_prerequisites),
    )


__all__ = [
    "AcceptanceRouteIdentity",
    "ExpectedAcceptanceRoute",
    "MacOsExecutorAcceptanceReceipt",
    "ReceiptValidationError",
    "ReceiptValidationResult",
    "validate_acceptance_receipt",
]
