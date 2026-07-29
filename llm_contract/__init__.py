"""Provider-neutral model access contracts shared across runtime authorities.

This package is deliberately a leaf: it owns immutable data contracts, protocols,
closed vocabularies, and side-effect-free validation only. Product and Builder
runtimes retain their own policy, registries, credentials, transports, and stores.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
CapabilityTier = Literal["economy", "standard", "frontier"]
ReasoningEffort = Literal["minimal", "low", "medium", "high", "xhigh"]
IndependenceRequirement = Literal["none", "distinct_effective_target"]
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
    deterministic_execution: bool = False
    embedding_dimension: int | None = Field(default=None, ge=1)


class ModelCapabilities(_StrictFrozenModel):
    """Capabilities attested for one effective model target."""

    structured_output: bool = False
    native_tools: bool = False
    system_prompt_channel: bool = False
    deterministic_execution: bool = False
    embedding_dimension: int | None = Field(default=None, ge=1)


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
    credential_identity_ref: NonEmptyString
    degraded: bool = False
    degradation_reason: NonEmptyString | None = None

    @model_validator(mode="after")
    def _validate_capabilities_and_degradation(self) -> "ResolvedModelAccess":
        required = self.request.requirements
        capabilities = self.capabilities
        boolean_requirements = {
            "structured_output": (
                required.structured_output or self.request.intent.output_schema_ref is not None
            ),
            "native_tools": required.native_tools,
            "system_prompt_channel": required.system_prompt_channel,
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
        return self


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
    "CapabilityTier",
    "FallbackRequirement",
    "IndependenceRequirement",
    "ModelAccessIntent",
    "ModelAccessResolver",
    "ModelCapabilities",
    "ModelCapabilityRequirements",
    "ModelResolutionRequest",
    "ModelTurnAdapter",
    "ReasoningEffort",
    "ResolvedModelAccess",
    "SchemaValidationError",
    "SchemaValidator",
    "validate_adapter_failure_class",
    "validate_resolved_group",
    "validate_schema_payload",
)
