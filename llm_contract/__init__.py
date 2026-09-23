"""Provider-neutral model access contracts shared across runtime authorities.

This package is deliberately a leaf: it owns immutable data contracts, protocols,
closed vocabularies, and side-effect-free validation only. Product and Builder
runtimes retain their own policy, registries, credentials, transports, and stores.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import ipaddress
import re
from typing import Annotated, Any, Literal, Protocol, runtime_checkable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError as _JsonSchemaError
from jsonschema.exceptions import ValidationError as _JsonSchemaViolation
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from referencing import Registry
from referencing.exceptions import Unresolvable as _UnresolvableSchemaReference


NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
LogicalProfileRef = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^profile\.[a-z][a-z0-9_]*$",
    ),
]
CatalogSnapshotRef = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^catalog\.[a-z][a-z0-9_]*$",
    ),
]
Sha256Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
TransportId = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$"),
]
ScopeIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[a-z][a-z0-9_.-]{0,127}$",
    ),
]
ProviderId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[a-z][a-z0-9_-]{0,63}$",
    ),
]
AdapterId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[a-z][a-z0-9._:-]{0,127}$",
    ),
]
RouteModelId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}$",
    ),
]
CredentialIdentityRef = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[a-z][a-z0-9_-]*\.(?:api-key|api_key|credential-ref|credential_ref|subscription-session|subscription_session|session-ref|session_ref)$",
    ),
]
CapabilityTier = Literal["economy", "standard", "frontier"]
ReasoningEffort = Literal["minimal", "low", "medium", "high", "xhigh"]
ExecutionBoundary = Literal[
    "in_process",
    "local_subprocess",
    "local_http",
    "provider_https",
    "private_tailnet_serve_https",
]
AuthenticationScheme = Literal[
    "none",
    "provider_credential_ref",
    "local_subscription_session",
    "tailscale_app_capability",
]
PreflightStatus = Literal["not_run", "passed", "failed", "unavailable", "skipped"]
PreflightFailureCode = Literal[
    "adapter_unavailable",
    "executor_unreachable",
    "cli_missing",
    "authentication_unavailable",
    "session_expired",
    "model_unavailable",
    "capability_mismatch",
    "catalog_unavailable",
    "unsupported_profile",
]
FallbackReasonCode = Literal[
    "adapter_unavailable",
    "executor_unreachable",
    "cli_missing",
    "authentication_unavailable",
    "session_expired",
    "model_unavailable",
    "catalog_unavailable",
]
RouteDegradationCode = Literal[
    "policy_selected_compatible_route",
    "preflight_fallback",
    "capability_preserving_fallback",
    "stale_catalog_pinned_target",
]
IndependenceRequirement = Literal["none", "distinct_effective_target"]

_SENSITIVE_ROUTE_VALUE = re.compile(
    r"https?://|@|(?:\d{1,3}\.){3}\d{1,3}|"
    r"\bsk-(?:ant-)?(?:api\d+-)?[a-z0-9_-]{6,}\b|"
    r"\bAIza[0-9A-Za-z_-]{20,}\b|\b(?:ghp_|github_pat_|xox[baprs]-)[A-Za-z0-9_-]{12,}\b|"
    r"tskey-|tscap-|"
    r"\b(?:bearer|authorization|api[_-]?key|token|password|secret)\s*[:=]|"
    r"(?:^|/)(?:users|home|private|var|tmp)/|"
    r"(?:^|[/@])(?:[a-z0-9-]+\.)+(?:ts\.net|local|lan|localhost|internal)(?:[:/]|$)|"
    r"\b(?:ignore|override|disregard|reveal|exfiltrate)_[a-z0-9_]*"
    r"(?:safety|system|developer|instruction|prompt|secret|credential)(?:_|\b)",
    re.IGNORECASE,
)
_ENVIRONMENT_ASSIGNMENT = re.compile(r"\b[A-Z][A-Z0-9_]{1,63}\s*[:=]")
_IPV6_ADDRESS_CANDIDATE = re.compile(r"(?<![\w:])([0-9a-f:]+)(?![\w:])", re.IGNORECASE)


def _contains_ipv6_address(value: str) -> bool:
    for candidate in _IPV6_ADDRESS_CANDIDATE.findall(value):
        if candidate.count(":") < 2:
            continue
        try:
            ipaddress.IPv6Address(candidate)
        except ValueError:
            continue
        return True
    return False


def _contains_sensitive_route_value(value: str) -> bool:
    return bool(
        _SENSITIVE_ROUTE_VALUE.search(value)
        or _ENVIRONMENT_ASSIGNMENT.search(value)
        or _contains_ipv6_address(value)
    )


FallbackRequirement = Literal[
    "fallback_forbidden",
    "fallback_same_identity",
    "fallback_compatible_identity",
    "fallback_policy_selected",
    "human_decision_required",
]

FALLBACK_REQUIREMENTS: frozenset[FallbackRequirement] = frozenset(
    {
        "fallback_forbidden",
        "fallback_same_identity",
        "fallback_compatible_identity",
        "fallback_policy_selected",
        "human_decision_required",
    }
)

ADAPTER_FAILURE_CLASSES = frozenset(
    {
        "command_exit_nonzero",
        "command_timeout",
        "stdout_empty",
        "stdout_oversize",
        "stdout_unavailable",
        "output_contains_allowed_environment",
        "unexpected_adapter_error",
        "credential_unavailable",
        "session_expired",
    }
)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ModelAccessIntent(_StrictFrozenModel):
    """The seven provider-free fields declared by a model caller."""

    capability_tier: CapabilityTier
    reasoning_effort: ReasoningEffort
    determinism_required: bool
    output_schema_ref: NonEmptyString | None
    independence: IndependenceRequirement
    fallback_requirement: FallbackRequirement
    side_effect_class: NonEmptyString


class ModelCapabilityRequirements(_StrictFrozenModel):
    """Capabilities a selected target must satisfy before execution."""

    structured_output: bool = False
    native_tools: bool = False
    system_prompt_channel: bool = False
    literal_system_role_required: bool = False
    deterministic_execution: bool = False
    embedding_dimension: int | None = Field(default=None, ge=1)


class ModelCapabilities(_StrictFrozenModel):
    """Capabilities attested for one effective model target."""

    structured_output: bool = False
    native_tools: bool = False
    system_prompt_channel: bool = False
    deterministic_execution: bool = False
    embedding_dimension: int | None = Field(default=None, ge=1)


class CapabilityProvenance(_StrictFrozenModel):
    """Secret-free source reference for the declared capability set."""

    source: Literal[
        "owner_resolver",
        "catalog_snapshot",
        "adapter_attestation",
        "policy_registry",
    ]
    source_ref: LogicalProfileRef | CatalogSnapshotRef | AdapterId


class TrustedInstructionMapping(_StrictFrozenModel):
    """Versioned channel mapping; it carries no instruction or prompt text."""

    mapping_ref: LogicalProfileRef
    trusted_channel: Literal["system", "developer_instructions"]
    untrusted_channel: Literal["user"]


class FallbackProvenance(_StrictFrozenModel):
    """One owner-authorized, pre-inference target selection, never a retry."""

    used: bool = False
    phase: Literal["preflight"] | None = None
    reason_code: FallbackReasonCode | None = None
    source_transport_id: TransportId | None = None
    selected_transport_id: TransportId | None = None
    policy_authority: LogicalProfileRef | None = None
    source_effective_identity: RouteModelId | None = None
    selected_effective_identity: RouteModelId | None = None

    @model_validator(mode="after")
    def _validate_preflight_only_fallback(self) -> "FallbackProvenance":
        values = (
            self.phase,
            self.reason_code,
            self.source_transport_id,
            self.selected_transport_id,
            self.policy_authority,
            self.source_effective_identity,
            self.selected_effective_identity,
        )
        if self.used:
            if any(value is None for value in values):
                raise ValueError(
                    "used fallback requires preflight phase, reason, transports, policy, and source/selected identities"
                )
            for identity in (
                self.source_effective_identity,
                self.selected_effective_identity,
            ):
                if identity is not None and _contains_sensitive_route_value(identity):
                    raise ValueError("fallback identities must be logical target references")
        elif any(value is not None for value in values):
            raise ValueError("unused fallback cannot carry fallback provenance")
        return self


def _validate_fallback_requirement_semantics(
    requirement: FallbackRequirement,
    provenance: FallbackProvenance,
    effective_identity: str,
) -> None:
    """Enforce neutral fallback limits; compatible selection stays owner-owned."""
    if not provenance.used:
        return
    if requirement == "fallback_forbidden":
        raise ValueError("fallback_forbidden intent cannot carry fallback provenance")
    if requirement == "human_decision_required":
        raise ValueError(
            "human_decision_required intent cannot select a fallback without decision provenance"
        )
    if requirement == "fallback_same_identity" and (
        provenance.source_effective_identity
        != provenance.selected_effective_identity
    ):
        raise ValueError(
            "fallback_same_identity requires matching source and selected effective identities"
        )
    if provenance.selected_effective_identity != effective_identity:
        raise ValueError(
            "fallback selected identity must match the resolved effective identity"
        )


class ModelAccessProfile(_StrictFrozenModel):
    """Caller-supplied owner context; it names policy but does not implement it."""

    profile_id: LogicalProfileRef
    runtime: ScopeIdentifier
    channel: ScopeIdentifier
    consumer: ScopeIdentifier
    caller_profile: LogicalProfileRef
    catalog_snapshot_ref: CatalogSnapshotRef | None = None
    catalog_snapshot_hash: Sha256Digest | None = None
    capability_provenance: CapabilityProvenance

    @model_validator(mode="after")
    def _validate_profile_provenance(self) -> "ModelAccessProfile":
        if (self.catalog_snapshot_ref is None) != (self.catalog_snapshot_hash is None):
            raise ValueError("catalog snapshot reference and hash must be supplied together")
        if self.capability_provenance.source == "catalog_snapshot":
            if self.capability_provenance.source_ref != self.catalog_snapshot_ref:
                raise ValueError(
                    "catalog capability provenance must match the selected snapshot"
                )
        if self.capability_provenance.source in {"owner_resolver", "policy_registry"}:
            if self.capability_provenance.source_ref != self.profile_id:
                raise ValueError(
                    "resolver capability provenance must match the selected profile"
                )
        return self


class ModelAccessAdapterDescriptor(_StrictFrozenModel):
    """Non-secret adapter facts needed to bind a resolved target to a transport."""

    adapter_id: AdapterId
    provider: ProviderId
    model: NonEmptyString
    transport_id: TransportId
    supported_capabilities: ModelCapabilities
    execution_host_profile: LogicalProfileRef
    execution_boundary: ExecutionBoundary
    authentication_scheme: AuthenticationScheme
    trusted_instruction_mapping: TrustedInstructionMapping | None = None


@runtime_checkable
class ModelAccessAdapterRegistry(Protocol):
    """Lookup-only adapter registry port; it does not execute a model turn."""

    def describe(self, adapter_id: str) -> ModelAccessAdapterDescriptor: ...


class ModelResolutionRequest(_StrictFrozenModel):
    """One neutral role request within a caller-defined resolution group."""

    intent: ModelAccessIntent
    role_profile: NonEmptyString
    resolution_group_id: NonEmptyString
    requirements: ModelCapabilityRequirements = Field(
        default_factory=ModelCapabilityRequirements
    )


class ResolvedModelAccess(_StrictFrozenModel):
    """Validated target identity, capability, credential-reference, and provenance."""

    request: ModelResolutionRequest
    provider: NonEmptyString
    model: NonEmptyString
    adapter_id: NonEmptyString
    effective_identity: NonEmptyString
    capabilities: ModelCapabilities
    credential_identity_ref: CredentialIdentityRef
    degraded: bool = False
    degradation_reason: NonEmptyString | None = None
    fallback_provenance: FallbackProvenance = Field(default_factory=FallbackProvenance)

    @model_validator(mode="after")
    def _validate_capabilities_and_degradation(self) -> "ResolvedModelAccess":
        for field_name in (
            "provider",
            "model",
            "adapter_id",
            "effective_identity",
            "credential_identity_ref",
        ):
            if _contains_sensitive_route_value(getattr(self, field_name)):
                raise ValueError(
                    f"{field_name} must be a logical reference, not sensitive data"
                )
        if self.degradation_reason is not None and _contains_sensitive_route_value(
            self.degradation_reason
        ):
            raise ValueError("degradation_reason must not contain sensitive data")

        required = self.request.requirements
        capabilities = self.capabilities
        boolean_requirements = {
            "structured_output": (
                required.structured_output or self.request.intent.output_schema_ref is not None
            ),
            "native_tools": required.native_tools,
            "system_prompt_channel": (
                required.system_prompt_channel or required.literal_system_role_required
            ),
            "deterministic_execution": (
                required.deterministic_execution
                or self.request.intent.determinism_required
            ),
        }
        missing = sorted(
            name
            for name, is_required in boolean_requirements.items()
            if is_required and not getattr(capabilities, name)
        )
        if missing:
            raise ValueError(
                "resolved target does not satisfy required capabilities: "
                + ", ".join(missing)
            )
        if (
            required.embedding_dimension is not None
            and capabilities.embedding_dimension != required.embedding_dimension
        ):
            raise ValueError(
                "resolved target does not satisfy required embedding_dimension "
                f"{required.embedding_dimension}"
            )
        if self.degraded and self.degradation_reason is None:
            raise ValueError("degradation_reason is required when degraded is true")
        if not self.degraded and self.degradation_reason is not None:
            raise ValueError("degradation_reason is forbidden when degraded is false")
        if self.fallback_provenance.used:
            _validate_fallback_requirement_semantics(
                self.request.intent.fallback_requirement,
                self.fallback_provenance,
                self.effective_identity,
            )
            if not self.degraded:
                raise ValueError("a selected fallback route must be visibly degraded")
        return self


class ModelAccessRoute(ResolvedModelAccess):
    """One exact resolved target plus safe transport and execution provenance."""

    provider: ProviderId
    model: RouteModelId
    adapter_id: AdapterId
    effective_identity: RouteModelId
    credential_identity_ref: CredentialIdentityRef
    degradation_reason: RouteDegradationCode | None = None
    policy_profile: LogicalProfileRef
    transport_id: TransportId
    catalog_snapshot_ref: CatalogSnapshotRef | None = None
    catalog_snapshot_hash: Sha256Digest | None = None
    preflight_status: PreflightStatus = "not_run"
    preflight_failure_code: PreflightFailureCode | None = None
    execution_host_profile: LogicalProfileRef
    execution_boundary: ExecutionBoundary
    authentication_scheme: AuthenticationScheme
    caller_profile: LogicalProfileRef
    capability_provenance: CapabilityProvenance
    trusted_instruction_mapping: TrustedInstructionMapping | None = None

    @property
    def requested_capabilities(self) -> ModelCapabilityRequirements:
        return self.request.requirements

    @property
    def resolved_capabilities(self) -> ModelCapabilities:
        return self.capabilities

    @model_validator(mode="after")
    def _validate_route_provenance(self) -> "ModelAccessRoute":
        if (self.catalog_snapshot_ref is None) != (self.catalog_snapshot_hash is None):
            raise ValueError("catalog snapshot reference and hash must be supplied together")
        if self.preflight_status in {"failed", "unavailable"}:
            if self.preflight_failure_code is None:
                raise ValueError(
                    "preflight_failure_code is required for failed or unavailable preflight"
                )
        elif self.preflight_failure_code is not None:
            raise ValueError(
                "preflight_failure_code is forbidden unless preflight failed or is unavailable"
            )
        if self.capability_provenance.source == "catalog_snapshot":
            if self.capability_provenance.source_ref != self.catalog_snapshot_ref:
                raise ValueError(
                    "catalog capability provenance must match the selected snapshot"
                )
        if self.capability_provenance.source in {"owner_resolver", "policy_registry"}:
            if self.capability_provenance.source_ref != self.policy_profile:
                raise ValueError(
                    "resolver capability provenance must match the selected profile"
                )
        if self.capability_provenance.source == "adapter_attestation":
            if self.capability_provenance.source_ref != self.adapter_id:
                raise ValueError(
                    "adapter capability provenance must match the selected adapter"
                )
        if self.capabilities.system_prompt_channel and (
            self.trusted_instruction_mapping is None
        ):
            raise ValueError(
                "system_prompt_channel requires a declared trusted-instruction mapping"
            )
        if self.request.requirements.literal_system_role_required and (
            self.trusted_instruction_mapping is None
            or self.trusted_instruction_mapping.trusted_channel != "system"
        ):
            raise ValueError(
                "literal system role requirement needs a literal system-channel mapping"
            )
        if self.fallback_provenance.used:
            _validate_fallback_requirement_semantics(
                self.request.intent.fallback_requirement,
                self.fallback_provenance,
                self.effective_identity,
            )
            if self.fallback_provenance.selected_transport_id != self.transport_id:
                raise ValueError("fallback selected transport must match the resolved route")
            if self.fallback_provenance.policy_authority != self.policy_profile:
                raise ValueError("fallback policy authority must match the resolved policy profile")
            if not self.degraded:
                raise ValueError("a selected fallback route must be visibly degraded")

        # Target identifiers are routing metadata, never an alternate channel
        # for endpoints, prompt text, host identity, credentials, or raw grants.
        for field_name in (
            "provider",
            "model",
            "adapter_id",
            "effective_identity",
            "credential_identity_ref",
        ):
            if _contains_sensitive_route_value(getattr(self, field_name)):
                raise ValueError(f"{field_name} must be a logical reference, not sensitive data")
        request_identifiers = [
            self.request.role_profile,
            self.request.resolution_group_id,
            self.request.intent.side_effect_class,
        ]
        if self.request.intent.output_schema_ref is not None:
            request_identifiers.append(self.request.intent.output_schema_ref)
        for value in request_identifiers:
            if (
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}", value)
                or _contains_sensitive_route_value(value)
            ):
                raise ValueError("route request metadata must contain logical identifiers only")
        return self


class ModelAccessReceipt(_StrictFrozenModel):
    """Serializable route-resolution receipt with no prompt or execution payload."""

    schema_version: Literal["model_access_route_receipt.v1"] = (
        "model_access_route_receipt.v1"
    )
    route: ModelAccessRoute


@dataclass(frozen=True)
class AdapterResult:
    response_text: str
    provider_request_id: str | None = None


@runtime_checkable
class ModelTurnAdapter(Protocol):
    @property
    def adapter_id(self) -> str: ...

    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    def execute(self, request: Mapping[str, Any]) -> AdapterResult: ...


@runtime_checkable
class ModelAccessResolver(Protocol):
    """Runtime-owned resolution port; the kernel provides no implementation."""

    def resolve(
        self,
        request: ModelResolutionRequest,
        *,
        runtime: str,
        channel: str,
        consumer: str,
    ) -> ResolvedModelAccess: ...

    def resolve_group(
        self,
        requests: Sequence[ModelResolutionRequest],
        *,
        runtime: str,
        channel: str,
        consumer: str,
    ) -> tuple[ResolvedModelAccess, ...]: ...


class SchemaValidationError(ValueError):
    """A referenced schema or payload failed neutral validation."""

    def __init__(self, *, schema_ref: str, reason: str) -> None:
        super().__init__(f"schema validation failed for {schema_ref!r}: {reason}")
        self.schema_ref = schema_ref
        self.reason = reason


@runtime_checkable
class SchemaValidator(Protocol):
    def validate(
        self,
        schema_ref: str,
        schema: Mapping[str, Any],
        payload: Any,
    ) -> Mapping[str, Any]: ...


def _validate_local_schema_references(schema_ref: str, value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in {"$ref", "$dynamicRef"} and (
                not isinstance(nested, str) or not nested.startswith("#")
            ):
                raise SchemaValidationError(
                    schema_ref=schema_ref,
                    reason=(
                        f"non-local {key} is forbidden; "
                        "only same-document fragment references are allowed"
                    ),
                )
            _validate_local_schema_references(schema_ref, nested)
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for nested in value:
            _validate_local_schema_references(schema_ref, nested)


def validate_schema_payload(
    schema_ref: str,
    schema: Mapping[str, Any],
    payload: Any,
) -> dict[str, Any]:
    """Validate an object against a self-contained caller-supplied JSON Schema."""

    if not schema_ref.strip():
        raise SchemaValidationError(schema_ref=schema_ref, reason="schema_ref is empty")
    normalized_schema = dict(schema)
    _validate_local_schema_references(schema_ref, normalized_schema)
    try:
        Draft202012Validator.check_schema(normalized_schema)
    except _JsonSchemaError as exc:
        raise SchemaValidationError(
            schema_ref=schema_ref,
            reason=f"invalid schema: {exc.message}",
        ) from exc
    if not isinstance(payload, Mapping):
        raise SchemaValidationError(
            schema_ref=schema_ref,
            reason=f"payload is not an object (got {type(payload).__name__})",
        )
    normalized_payload = dict(payload)
    try:
        Draft202012Validator(
            normalized_schema,
            registry=Registry(),
        ).validate(normalized_payload)
    except _JsonSchemaViolation as exc:
        raise SchemaValidationError(
            schema_ref=schema_ref,
            reason=f"schema violation: {exc.message}",
        ) from exc
    except _UnresolvableSchemaReference as exc:
        raise SchemaValidationError(
            schema_ref=schema_ref,
            reason=f"unresolvable local schema reference: {exc}",
        ) from exc
    return normalized_payload


def validate_adapter_failure_class(failure_class: str) -> str:
    """Reject values outside the one closed adapter failure vocabulary."""

    if failure_class not in ADAPTER_FAILURE_CLASSES:
        raise ValueError(f"unknown adapter failure class: {failure_class!r}")
    return failure_class


def validate_resolved_group(
    requests: Sequence[ModelResolutionRequest],
    resolutions: Sequence[ResolvedModelAccess],
) -> tuple[ResolvedModelAccess, ...]:
    """Validate request/result correspondence and grouped target independence.

    Runtime resolvers call this after target resolution and before obtaining or
    invoking adapters. The function is validation only; it performs no policy,
    credential, registry, or transport work.
    """

    request_tuple = tuple(requests)
    resolution_tuple = tuple(resolutions)
    if not request_tuple:
        raise ValueError("resolution group must contain at least one request")
    if len(request_tuple) != len(resolution_tuple):
        raise ValueError("resolution group request/result counts do not match")
    group_ids = {request.resolution_group_id for request in request_tuple}
    if len(group_ids) != 1:
        raise ValueError("resolution group requests must share resolution_group_id")
    for request, resolution in zip(request_tuple, resolution_tuple, strict=True):
        if resolution.request != request:
            raise ValueError("resolved access does not correspond to its request")

    if any(
        request.intent.independence == "distinct_effective_target"
        for request in request_tuple
    ):
        targets = [
            (result.provider, result.model, result.effective_identity)
            for result in resolution_tuple
        ]
        if len(targets) != len(set(targets)):
            raise ValueError(
                "distinct_effective_target requires unique "
                "(provider, model, effective_identity) tuples"
            )
    return resolution_tuple


__all__ = (
    "ADAPTER_FAILURE_CLASSES",
    "FALLBACK_REQUIREMENTS",
    "AdapterResult",
    "AdapterId",
    "AuthenticationScheme",
    "CapabilityProvenance",
    "CapabilityTier",
    "CatalogSnapshotRef",
    "CredentialIdentityRef",
    "ExecutionBoundary",
    "FallbackProvenance",
    "FallbackRequirement",
    "FallbackReasonCode",
    "IndependenceRequirement",
    "LogicalProfileRef",
    "ModelAccessIntent",
    "ModelAccessAdapterDescriptor",
    "ModelAccessAdapterRegistry",
    "ModelAccessProfile",
    "ModelAccessReceipt",
    "ModelAccessRoute",
    "ModelAccessResolver",
    "ModelCapabilities",
    "ModelCapabilityRequirements",
    "ModelResolutionRequest",
    "ModelTurnAdapter",
    "PreflightFailureCode",
    "PreflightStatus",
    "ProviderId",
    "ReasoningEffort",
    "ResolvedModelAccess",
    "RouteModelId",
    "RouteDegradationCode",
    "SchemaValidationError",
    "SchemaValidator",
    "Sha256Digest",
    "ScopeIdentifier",
    "TrustedInstructionMapping",
    "TransportId",
    "validate_adapter_failure_class",
    "validate_resolved_group",
    "validate_schema_payload",
)
