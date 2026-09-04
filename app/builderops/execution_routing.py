"""Provider-neutral Builder execution routing contracts and pure Phase 1 policy.

The policy in this module is deliberately narrow: it resolves only the
``bounded_fast`` shadow/canary seam introduced by Builder execution-routing
Phase 1. It never claims work, launches a worker, mutates verification, or
authorizes lifecycle effects. Provider/model binding is a separate declared
configuration lookup.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Final, Literal, Sequence, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.builderops.delivery_orchestration_contracts import (
    CanonicalDeliveryContract,
    NonEmptyStr,
    Sha256,
    UtcTimestamp,
    canonical_hash,
)
from app.components.settings.providers_loader import ProviderCensus


ALLOCATION_OBSERVATION_VERSION: Final[
    Literal["builderops.execution-allocation-observation.v1"]
] = "builderops.execution-allocation-observation.v1"
EXECUTION_ROUTE_REQUEST_VERSION: Final[
    Literal["builderops.execution-route-request.v1"]
] = "builderops.execution-route-request.v1"
EXECUTION_ROUTE_DECISION_VERSION: Final[
    Literal["builderops.execution-route-decision.v1"]
] = "builderops.execution-route-decision.v1"
RESOLVED_EXECUTION_TARGET_VERSION: Final[
    Literal["builderops.resolved-execution-target.v1"]
] = "builderops.resolved-execution-target.v1"
EXECUTION_ATTEMPT_OBSERVATION_VERSION: Final[
    Literal["builderops.execution-attempt-observation.v1"]
] = (
    "builderops.execution-attempt-observation.v1"
)
EXECUTION_ROUTING_POLICY_VERSION: Final[
    Literal["builderops.execution-routing-policy.v1"]
] = "builderops.execution-routing-policy.v1"
PHASE2_CANARY_RECEIPT_VERSION: Final[
    Literal["builder_execution_routing_canary.v1"]
] = "builder_execution_routing_canary.v1"

WorkClass: TypeAlias = Literal[
    "deterministic",
    "bounded_fast",
    "general_delivery",
    "complex_delivery",
    "frontier_high_risk",
]
CapabilityTier: TypeAlias = Literal["spark", "luna", "terra", "sol"]
AllocationState: TypeAlias = Literal[
    "bonus_available",
    "economically_unavailable",
    "unknown",
]
TransitionKind: TypeAlias = Literal[
    "none",
    "capacity_fallback",
    "capability_escalation",
]
RouteTransitionReason: TypeAlias = Literal[
    "fresh_bonus_available",
    "allocation_observation_missing",
    "allocation_observation_stale",
    "allocation_economically_unavailable",
    "allocation_unknown",
]
AttemptTransitionReason: TypeAlias = Literal[
    "initial_route",
    "shadow_route_not_invoked",
    "spark_allocation_unavailable_at_launch",
    "capability_insufficient",
]
ReasoningEffort: TypeAlias = Literal[
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
]
def _parse_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")


class AllocationObservation(CanonicalDeliveryContract):
    """One explicit, scoped and expiring allocation observation."""

    contract_family: ClassVar[str] = "execution_routing"
    schema_version: Literal[
        "builderops.execution-allocation-observation.v1"
    ] = ALLOCATION_OBSERVATION_VERSION
    observation_id: NonEmptyStr
    capability: Literal["spark"]
    state: AllocationState
    observed_at: UtcTimestamp
    valid_until: UtcTimestamp
    source_kind: Literal["operator", "provider", "configuration"]
    source_ref: NonEmptyStr

    @model_validator(mode="after")
    def _validate_window(self) -> "AllocationObservation":
        if _parse_utc(self.valid_until) < _parse_utc(self.observed_at):
            raise ValueError("allocation observation validity must not precede observation")
        return self

    def is_fresh_at(self, decision_at: str) -> bool:
        instant = _parse_utc(decision_at)
        return _parse_utc(self.observed_at) <= instant <= _parse_utc(
            self.valid_until
        )


class ExecutionRouteRequest(CanonicalDeliveryContract):
    """Provider-free deterministic input for one bounded execution route."""

    contract_family: ClassVar[str] = "execution_routing"
    schema_version: Literal[
        "builderops.execution-route-request.v1"
    ] = EXECUTION_ROUTE_REQUEST_VERSION
    request_id: NonEmptyStr
    policy_version: Literal[
        "builderops.execution-routing-policy.v1"
    ] = EXECUTION_ROUTING_POLICY_VERSION
    issue_number: int = Field(gt=0)
    work_class: WorkClass
    risk: Literal["low", "medium", "high", "critical"]
    ambiguity: Literal["low", "medium", "high"]
    protected_surface: bool
    decision_at: UtcTimestamp
    context_pack_hash: Sha256
    authority_hash: Sha256
    verification_profile_hash: Sha256
    shadow_against_capability: CapabilityTier
    allocation_observation: AllocationObservation | None = None


class ExecutionRouteDecision(CanonicalDeliveryContract):
    """Provider-free authorized policy result; never a launch authorization."""

    contract_family: ClassVar[str] = "execution_routing"
    schema_version: Literal[
        "builderops.execution-route-decision.v1"
    ] = EXECUTION_ROUTE_DECISION_VERSION
    decision_id: NonEmptyStr
    route_lineage_id: NonEmptyStr
    request_id: NonEmptyStr
    request_hash: Sha256
    policy_version: Literal[
        "builderops.execution-routing-policy.v1"
    ] = EXECUTION_ROUTING_POLICY_VERSION
    work_class: Literal["bounded_fast"]
    requested_capability: Literal["spark"] = "spark"
    selected_capability: Literal["spark", "luna"]
    shadow_against_capability: CapabilityTier
    transition_kind: Literal["none", "capacity_fallback"]
    transition_reason: RouteTransitionReason
    allocation_observation_id: NonEmptyStr | None
    allocation_observation_hash: Sha256 | None
    context_pack_hash: Sha256
    authority_hash: Sha256
    verification_profile_hash: Sha256
    delivery_blocked: Literal[False] = False
    effect_authority: Literal["none-shadow-policy-only"] = "none-shadow-policy-only"

    @model_validator(mode="after")
    def _validate_transition(self) -> "ExecutionRouteDecision":
        fallback = self.transition_kind == "capacity_fallback"
        if fallback != (self.selected_capability == "luna"):
            raise ValueError("Luna selection must be an explicit capacity fallback")
        observation_fields = (
            self.allocation_observation_id,
            self.allocation_observation_hash,
        )
        if (observation_fields[0] is None) != (observation_fields[1] is None):
            raise ValueError("allocation observation identity and hash must travel together")
        has_observation = observation_fields[0] is not None
        if self.selected_capability == "spark":
            if self.transition_reason != "fresh_bonus_available" or not has_observation:
                raise ValueError(
                    "Spark selection requires a bound fresh bonus observation"
                )
        elif self.transition_reason == "fresh_bonus_available":
            raise ValueError("fresh bonus availability must select Spark")
        elif (self.transition_reason == "allocation_observation_missing") == has_observation:
            raise ValueError(
                "missing allocation evidence must be represented without an observation"
            )

        expected_lineage_id = f"execution-route:{self.request_hash}"
        if self.route_lineage_id != expected_lineage_id:
            raise ValueError("route lineage identity must bind the request hash")
        decision_identity_payload = {
            "request_hash": self.request_hash,
            "selected_capability": self.selected_capability,
            "transition_kind": self.transition_kind,
            "transition_reason": self.transition_reason,
            "allocation_observation_id": self.allocation_observation_id,
            "allocation_observation_hash": self.allocation_observation_hash,
        }
        expected_decision_id = (
            "execution-route-decision:"
            f"{canonical_hash(decision_identity_payload)}"
        )
        if self.decision_id != expected_decision_id:
            raise ValueError("decision identity must bind the routing result")
        return self


class ResolvedExecutionTarget(BaseModel):
    """Declared configuration binding for one provider-neutral capability tier."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal[
        "builderops.resolved-execution-target.v1"
    ] = RESOLVED_EXECUTION_TARGET_VERSION
    capability: CapabilityTier
    provider: NonEmptyStr
    model: NonEmptyStr
    reasoning_effort: ReasoningEffort
    configuration_ref: NonEmptyStr

    def receipt_fields(self) -> dict[str, str]:
        return {
            "capability": self.capability,
            "provider": self.provider,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "configuration_ref": self.configuration_ref,
        }


class ExecutionAttemptObservation(CanonicalDeliveryContract):
    """Evidence for one shadow/canary carrier attempt outside WorkerContextPack."""

    contract_family: ClassVar[str] = "execution_routing"
    schema_version: Literal[
        "builderops.execution-attempt-observation.v1"
    ] = EXECUTION_ATTEMPT_OBSERVATION_VERSION
    attempt_id: NonEmptyStr
    route_lineage_id: NonEmptyStr
    route_decision_id: NonEmptyStr
    route_decision_hash: Sha256
    attempt_number: int = Field(gt=0)
    mode: Literal["shadow", "canary", "active"]
    requested_capability: CapabilityTier
    actual_capability: CapabilityTier
    provider: NonEmptyStr
    model: NonEmptyStr
    reasoning_effort: ReasoningEffort
    transition_kind: TransitionKind
    transition_reason: AttemptTransitionReason
    triggering_attempt_id: NonEmptyStr | None = None
    triggering_attempt_hash: Sha256 | None = None
    context_pack_hash: Sha256
    authority_hash: Sha256
    verification_profile_hash: Sha256
    outcome: Literal[
        "not_invoked",
        "started",
        "succeeded",
        "failed",
        "allocation_unavailable",
    ]
    observed_at: UtcTimestamp

    @model_validator(mode="after")
    def _validate_attempt_transition(self) -> "ExecutionAttemptObservation":
        triggering_fields = (
            self.triggering_attempt_id,
            self.triggering_attempt_hash,
        )
        if (triggering_fields[0] is None) != (triggering_fields[1] is None):
            raise ValueError("triggering attempt identity and hash must travel together")
        if self.mode == "shadow" and (
            self.outcome != "not_invoked"
            or self.transition_kind != "none"
            or self.transition_reason != "shadow_route_not_invoked"
        ):
            raise ValueError(
                "shadow attempts are non-invoked observations and cannot transition"
            )
        if self.transition_kind == "capacity_fallback":
            if self.actual_capability != "luna":
                raise ValueError("capacity fallback target must be luna")
            if (
                self.requested_capability != "spark"
                or self.transition_reason
                != "spark_allocation_unavailable_at_launch"
            ):
                raise ValueError(
                    "capacity fallback must bind Spark allocation unavailability"
                )
            if self.attempt_number < 2 or self.triggering_attempt_id is None:
                raise ValueError(
                    "capacity fallback must reference a prior attempt and increment identity"
                )
        elif self.transition_kind == "capability_escalation":
            raise ValueError(
                "capability escalation is not authorized by the Phase 1 contract"
            )
        elif self.triggering_attempt_id is not None:
            raise ValueError("only a transition may reference a triggering attempt")
        elif self.actual_capability != self.requested_capability:
            raise ValueError(
                "an attempt without a transition must use the selected capability"
            )
        elif self.mode != "shadow" and self.transition_reason != "initial_route":
            raise ValueError("an initial attempt must use the initial_route reason")
        if self.transition_kind == "capability_escalation" and self.mode == "shadow":
            raise ValueError("Phase 1 shadow observations cannot authorize escalation")
        identity_payload = {
            "route_decision_hash": self.route_decision_hash,
            "attempt_number": self.attempt_number,
            "actual_capability": self.actual_capability,
            "provider": self.provider,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "transition_kind": self.transition_kind,
            "triggering_attempt_id": self.triggering_attempt_id,
            "triggering_attempt_hash": self.triggering_attempt_hash,
        }
        expected_attempt_id = f"execution-attempt:{canonical_hash(identity_payload)}"
        if self.attempt_id != expected_attempt_id:
            raise ValueError("attempt identity must bind the canonical carrier inputs")
        return self


def resolve_bounded_fast_route(
    request: ExecutionRouteRequest,
) -> ExecutionRouteDecision:
    """Resolve the Phase 1 bounded-fast route without provider/model knowledge."""

    if (
        request.work_class != "bounded_fast"
        or request.risk != "low"
        or request.ambiguity != "low"
        or request.protected_surface
    ):
        raise ValueError(
            "bounded_fast route refused: work must be low-risk, low-ambiguity, and unprotected"
        )

    observation = request.allocation_observation
    selected: Literal["spark", "luna"] = "luna"
    transition: Literal["none", "capacity_fallback"] = "capacity_fallback"
    reason: RouteTransitionReason = "allocation_observation_missing"
    if observation is not None:
        if not observation.is_fresh_at(request.decision_at):
            reason = "allocation_observation_stale"
        elif observation.state == "bonus_available":
            selected = "spark"
            transition = "none"
            reason = "fresh_bonus_available"
        elif observation.state == "economically_unavailable":
            reason = "allocation_economically_unavailable"
        else:
            reason = "allocation_unknown"

    request_hash = request.content_hash
    lineage = f"execution-route:{request_hash}"
    decision_payload = {
        "request_hash": request_hash,
        "selected_capability": selected,
        "transition_kind": transition,
        "transition_reason": reason,
        "allocation_observation_id": (
            observation.observation_id if observation is not None else None
        ),
        "allocation_observation_hash": (
            observation.content_hash if observation is not None else None
        ),
    }
    return ExecutionRouteDecision(
        decision_id=f"execution-route-decision:{canonical_hash(decision_payload)}",
        route_lineage_id=lineage,
        request_id=request.request_id,
        request_hash=request_hash,
        work_class="bounded_fast",
        selected_capability=selected,
        shadow_against_capability=request.shadow_against_capability,
        transition_kind=transition,
        transition_reason=reason,
        allocation_observation_id=(
            observation.observation_id if observation is not None else None
        ),
        allocation_observation_hash=(
            observation.content_hash if observation is not None else None
        ),
        context_pack_hash=request.context_pack_hash,
        authority_hash=request.authority_hash,
        verification_profile_hash=request.verification_profile_hash,
    )


def validate_route_decision(
    request: ExecutionRouteRequest,
    decision: ExecutionRouteDecision,
) -> None:
    """Replay the pure resolver and require an exact request-bound decision."""

    expected = resolve_bounded_fast_route(request)
    if decision != expected:
        raise ValueError("route decision must exactly replay from its bound request")


def admit_phase2_canary(
    request: ExecutionRouteRequest,
    *,
    opt_in: bool,
    sample_index: int,
    sample_limit: int,
) -> ExecutionRouteDecision:
    """Admit exactly one explicit, low-risk Phase 2 canary candidate."""

    if opt_in is not True:
        raise ValueError("Phase 2 canary requires explicit opt-in")
    if isinstance(sample_index, bool) or isinstance(sample_limit, bool):
        raise ValueError("Phase 2 canary sample values must be integers")
    if sample_limit != 1:
        raise ValueError("Phase 2 canary admits one candidate only")
    if sample_index != 1:
        raise ValueError("Phase 2 canary candidate is outside the bounded sample")
    return resolve_bounded_fast_route(request)


def resolve_execution_target(
    census: ProviderCensus,
    *,
    channel: str,
    capability: CapabilityTier,
) -> ResolvedExecutionTarget:
    """Late-bind a capability tier through the declared Builder census."""

    profiles = census.runtime_channels.builder_execution.get(channel)
    if profiles is None:
        raise ValueError("declared census has no Builder execution channel")
    profile = profiles.get(capability)
    if profile is None or profile.capability_tier != capability:
        raise ValueError("declared census has no matching Builder execution capability")
    provider = census.provider(profile.provider)
    if not any(model.id == profile.model for model in provider.models):
        raise ValueError("Builder execution profile references an undeclared model")
    return ResolvedExecutionTarget(
        capability=capability,
        provider=profile.provider,
        model=profile.model,
        reasoning_effort=profile.reasoning_effort,
        configuration_ref=(
            "docs/settings/models/providers.yaml"
            f"#builder_execution.{channel}.{capability}"
        ),
    )


def create_execution_attempt(
    *,
    request: ExecutionRouteRequest,
    decision: ExecutionRouteDecision,
    target: ResolvedExecutionTarget,
    attempt_number: int,
    mode: Literal["shadow", "canary", "active"],
    outcome: Literal[
        "not_invoked",
        "started",
        "succeeded",
        "failed",
        "allocation_unavailable",
    ],
    observed_at: str,
    transition_kind: TransitionKind = "none",
    transition_reason: AttemptTransitionReason = "initial_route",
    triggering_attempt: ExecutionAttemptObservation | None = None,
) -> ExecutionAttemptObservation:
    """Create a distinct attempt identity without changing semantic worker hashes."""

    validate_route_decision(request, decision)

    if triggering_attempt is not None and (
        triggering_attempt.context_pack_hash != decision.context_pack_hash
        or triggering_attempt.authority_hash != decision.authority_hash
        or triggering_attempt.verification_profile_hash
        != decision.verification_profile_hash
    ):
        raise ValueError(
            "triggering attempt semantic hashes must match the route decision"
        )

    if transition_kind == "capacity_fallback":
        if target.capability != "luna":
            raise ValueError("capacity fallback target must be luna")
        if (
            triggering_attempt is None
            or triggering_attempt.route_decision_hash != decision.content_hash
            or triggering_attempt.route_lineage_id != decision.route_lineage_id
            or triggering_attempt.actual_capability != "spark"
            or triggering_attempt.outcome != "allocation_unavailable"
            or triggering_attempt.mode == "shadow"
            or mode != triggering_attempt.mode
            or attempt_number != triggering_attempt.attempt_number + 1
        ):
            raise ValueError(
                "capacity fallback must bind the immediately prior unavailable Spark attempt"
            )
    elif transition_kind == "capability_escalation":
        raise ValueError(
            "capability escalation is not authorized by the Phase 1 contract"
        )
    elif triggering_attempt is not None:
        raise ValueError("an initial or shadow attempt cannot bind a triggering attempt")

    identity_payload = {
        "route_decision_hash": decision.content_hash,
        "attempt_number": attempt_number,
        "actual_capability": target.capability,
        "provider": target.provider,
        "model": target.model,
        "reasoning_effort": target.reasoning_effort,
        "transition_kind": transition_kind,
        "triggering_attempt_id": (
            triggering_attempt.attempt_id if triggering_attempt is not None else None
        ),
        "triggering_attempt_hash": (
            triggering_attempt.content_hash if triggering_attempt is not None else None
        ),
    }
    return ExecutionAttemptObservation(
        attempt_id=f"execution-attempt:{canonical_hash(identity_payload)}",
        route_lineage_id=decision.route_lineage_id,
        route_decision_id=decision.decision_id,
        route_decision_hash=decision.content_hash,
        attempt_number=attempt_number,
        mode=mode,
        requested_capability=decision.selected_capability,
        actual_capability=target.capability,
        provider=target.provider,
        model=target.model,
        reasoning_effort=target.reasoning_effort,
        transition_kind=transition_kind,
        transition_reason=transition_reason,
        triggering_attempt_id=(
            triggering_attempt.attempt_id if triggering_attempt is not None else None
        ),
        triggering_attempt_hash=(
            triggering_attempt.content_hash if triggering_attempt is not None else None
        ),
        context_pack_hash=decision.context_pack_hash,
        authority_hash=decision.authority_hash,
        verification_profile_hash=decision.verification_profile_hash,
        outcome=outcome,
        observed_at=observed_at,
    )


def build_execution_routing_canary_receipt(
    *,
    request: ExecutionRouteRequest,
    decision: ExecutionRouteDecision,
    attempts: Sequence[ExecutionAttemptObservation],
    accepted_delivery_verification: Literal["passed", "failed", "not_run"],
) -> dict[str, object]:
    """Build redaction-safe evidence for one bounded Phase 2 canary outcome.

    This receipt is observational only. It deliberately omits allocation source
    details and never carries lifecycle, pickup, verification-waiver, merge, or
    closure authority.
    """

    validate_route_decision(request, decision)
    if not 1 <= len(attempts) <= 2:
        raise ValueError("Phase 2 canary permits at most one bounded Spark/Luna fallback")
    first = attempts[0]
    if (
        first.mode != "canary"
        or first.route_decision_hash != decision.content_hash
        or first.context_pack_hash != decision.context_pack_hash
        or first.authority_hash != decision.authority_hash
        or first.verification_profile_hash != decision.verification_profile_hash
    ):
        raise ValueError("canary attempt must bind the exact route semantic hashes")
    if decision.selected_capability == "spark":
        if first.actual_capability != "spark":
            raise ValueError("Spark canary must begin with the selected Spark capability")
        if len(attempts) == 2:
            fallback = attempts[1]
            if (
                first.outcome != "allocation_unavailable"
                or fallback.mode != "canary"
                or fallback.transition_kind != "capacity_fallback"
                or fallback.actual_capability != "luna"
                or fallback.triggering_attempt_id != first.attempt_id
                or fallback.triggering_attempt_hash != first.content_hash
                or fallback.context_pack_hash != first.context_pack_hash
                or fallback.authority_hash != first.authority_hash
                or fallback.verification_profile_hash
                != first.verification_profile_hash
            ):
                raise ValueError("canary fallback must be one typed Luna fallback")
    elif len(attempts) != 1 or first.actual_capability != "luna":
        raise ValueError("Luna canary fallback route permits one Luna attempt")

    return {
        "schema_version": PHASE2_CANARY_RECEIPT_VERSION,
        "candidate": {"issue_number": request.issue_number, "work_class": request.work_class},
        "route": {
            "route_lineage_id": decision.route_lineage_id,
            "requested_capability": decision.requested_capability,
            "selected_capability": decision.selected_capability,
            "allocation_state": decision.transition_reason,
        },
        "semantic_hashes": {
            "context_pack_hash": decision.context_pack_hash,
            "authority_hash": decision.authority_hash,
            "verification_profile_hash": decision.verification_profile_hash,
        },
        "attempt_count": len(attempts),
        "attempts": [
            {
                "attempt_id": attempt.attempt_id,
                "attempt_number": attempt.attempt_number,
                "requested_capability": attempt.requested_capability,
                "actual_capability": attempt.actual_capability,
                "transition_kind": attempt.transition_kind,
                "transition_reason": attempt.transition_reason,
                "outcome": attempt.outcome,
            }
            for attempt in attempts
        ],
        "accepted_delivery_verification": accepted_delivery_verification,
        "lifecycle_authority": "none",
        "verification_waiver_authority": "none",
        "merge_authority": "none",
        "closure_authority": "none",
    }


__all__ = [
    "ALLOCATION_OBSERVATION_VERSION",
    "AllocationObservation",
    "CapabilityTier",
    "EXECUTION_ATTEMPT_OBSERVATION_VERSION",
    "EXECUTION_ROUTE_DECISION_VERSION",
    "EXECUTION_ROUTE_REQUEST_VERSION",
    "ExecutionAttemptObservation",
    "ExecutionRouteDecision",
    "ExecutionRouteRequest",
    "PHASE2_CANARY_RECEIPT_VERSION",
    "RESOLVED_EXECUTION_TARGET_VERSION",
    "ResolvedExecutionTarget",
    "WorkClass",
    "admit_phase2_canary",
    "build_execution_routing_canary_receipt",
    "create_execution_attempt",
    "resolve_bounded_fast_route",
    "resolve_execution_target",
    "validate_route_decision",
]
