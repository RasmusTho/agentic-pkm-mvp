"""Deterministic Expansion Activation Gate function (#2025).

Implements two deterministic predicates as a single, inspectable, fail-loud
module:

1. The **inbound admit-by predicate** defined by
   ``docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md`` (#2023): given a candidate
   context/memory item and a *declared consuming authority*, return
   ``admit`` / ``exclude-with-reason`` across the four admission axes
   (sphere/scope, memory class, provenance/trust + review state, consuming
   authority) composed conjunctively and least-privilege ("stricter-boundary
   wins").

2. The **dormant->active activation decision** defined by the "Expansion
   Activation Gate" section of ``docs/EMERGENT_FEATURES_MODEL.md`` (#2024):
   given a capability's declared activation posture plus its candidate context,
   return ``activatable`` / ``blocked-with-reason`` and emit a decision receipt.

This is the **INPUT** side. It does **not** re-implement the **OUTBOUND**
authority enforcement (``AuthorityFlags`` in ``app/context_bundles/schema.py``;
``app/agent_memory/authority_guard.py``). An item admitted to the ``action``
tier here still passes those existing checks before any write. Introducing this
gate changes **no** existing capability behavior — nothing consults it on a live
path yet (first activation is #2026, owner-gated).

Determinism: the *decision* is a pure function of its declared inputs. Only the
receipt's ``receipt_id`` / ``created_at`` are non-decision metadata and may be
injected for reproducible tests. The gate is deterministic even though the
cognition it gates may be adaptive.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from app.agent_memory.candidate import ContradictionState, MemoryType, ReviewState


class AdmissionTier(str, Enum):
    """The influence tier an item is admitted to (least -> most permissive)."""

    NONE = "none"
    READ = "read"
    CITED_PROPOSAL = "cited-proposal"
    ACTION = "action"


_TIER_RANK: dict[AdmissionTier, int] = {
    AdmissionTier.NONE: 0,
    AdmissionTier.READ: 1,
    AdmissionTier.CITED_PROPOSAL: 2,
    AdmissionTier.ACTION: 3,
}


def _min_tier(a: AdmissionTier, b: AdmissionTier) -> AdmissionTier:
    """Return the more restrictive (lower-ranked) of two tiers."""

    return a if _TIER_RANK[a] <= _TIER_RANK[b] else b


class ConsumingAuthority(str, Enum):
    """Declared authority of the consuming use (``docs/CAPABILITY_CONTRACT_MODEL.md``)."""

    READ_ONLY = "read-only"
    PROPOSAL = "proposal"
    GOVERNED_EXECUTION = "governed-execution"


_CONSUMER_CEILING: dict[ConsumingAuthority, AdmissionTier] = {
    ConsumingAuthority.READ_ONLY: AdmissionTier.READ,
    ConsumingAuthority.PROPOSAL: AdmissionTier.CITED_PROPOSAL,
    ConsumingAuthority.GOVERNED_EXECUTION: AdmissionTier.ACTION,
}


class TrustArchetype(str, Enum):
    """Trust archetypes (``docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md``)."""

    HUMAN_AUTHORED_ACCEPTED = "human_authored_accepted"
    HUMAN_AUTHORED_RAW = "human_authored_raw"
    IMPORTED_EXTERNAL = "imported_external"
    MACHINE_PROPOSED = "machine_proposed"


# Per-class maximum admissible tier (Axis 2). PREFERENCE/POLICY reach ACTION only
# as a *necessary, not sufficient* condition — Axis 3 (accepted review) and the
# existing outbound authority_guard escalation still apply downstream.
_MEMORY_CLASS_CEILING: dict[MemoryType, AdmissionTier] = {
    MemoryType.WORKING_CONTEXT: AdmissionTier.CITED_PROPOSAL,
    MemoryType.EPISODIC_MEMORY: AdmissionTier.CITED_PROPOSAL,
    MemoryType.SEMANTIC_MEMORY: AdmissionTier.CITED_PROPOSAL,
    MemoryType.PROSPECTIVE_MEMORY: AdmissionTier.CITED_PROPOSAL,
    MemoryType.PROCEDURAL_MEMORY: AdmissionTier.CITED_PROPOSAL,
    MemoryType.PREFERENCE_MEMORY: AdmissionTier.ACTION,
    MemoryType.POLICY_MEMORY: AdmissionTier.ACTION,
}


# --- machine-readable reason codes -----------------------------------------

# admit reasons
REASON_SAME_SCOPE = "same_scope"
REASON_CROSS_SPHERE_ALLOWED = "cross_sphere_allowed"
REASON_CLASS_CEILING = "memory_class_ceiling"
REASON_NOT_MEMORY = "not_memory_item"
REASON_PROVENANCE_OK = "provenance_admitted"
REASON_CONSUMER_CEILING = "consumer_authority_ceiling"
# exclude / restrict reasons
REASON_SCOPE_UNRESOLVED = "scope_unresolved"
REASON_CROSS_SPHERE_NO_ALLOWANCE = "cross_sphere_no_allowance"
REASON_MEMORY_CLASS_UNKNOWN = "memory_class_unknown"
REASON_PROVENANCE_UNVERIFIED = "provenance_unverified"
REASON_CONTRADICTED_OR_REJECTED = "contradicted_or_rejected"
REASON_REVISED_READ_ONLY = "revised_read_only"
REASON_INFERRED_NO_ACTION = "inferred_or_unreviewed_no_action"
REASON_UNDECLARED_CONSUMER = "undeclared_consumer"
# activation blocked reasons
REASON_ADMISSIBILITY_UNDECLARED = "admissibility_undeclared"
REASON_LOOP_PRECONDITION_NOT_GREEN = "loop_precondition_not_green"
REASON_NO_REVERSIBLE_WRITE_PATH = "no_reversible_write_path"
REASON_NOT_OBSERVABLE = "not_observable"
REASON_NO_ADMISSIBLE_CONTEXT = "no_admissible_context"
REASON_ACTIVATABLE = "all_gate_inputs_green"


class CandidateContext(BaseModel):
    """A single candidate context/memory item being evaluated for admission."""

    artifact_id: str
    sphere: Optional[str] = None
    # memory-class axis applies only when the item is memory
    is_memory: bool = False
    memory_class: Optional[MemoryType] = None
    # provenance / trust axis
    trust_archetype: Optional[TrustArchetype] = None
    review_state: Optional[ReviewState] = None
    contradiction_state: ContradictionState = ContradictionState.CLEAR
    inferred: bool = False
    has_provenance: bool = False
    # sphere-crossing allowances
    shared_participation: bool = False
    cross_scope_allowance: bool = False


class ConsumingContext(BaseModel):
    """The declared consuming use an item is being admitted *into*."""

    capability_id: str
    authority: Optional[ConsumingAuthority] = None
    scope: Optional[str] = None


class AxisOutcome(BaseModel):
    """Per-axis admission outcome with the deciding tier and a reason code."""

    axis: str
    admitted: bool
    tier: AdmissionTier
    reason: str


class AdmissibilityDecision(BaseModel):
    """The composed admit/exclude-with-reason decision for one candidate item.

    Input-side analogue of ``AuthorityFlags`` (``app/context_bundles/schema.py``).
    """

    artifact_id: str
    admitted: bool
    admitted_tier: AdmissionTier
    consuming_authority: Optional[ConsumingAuthority]
    axes: list[AxisOutcome]
    reason: str


# --- axis evaluators (each returns the max tier that axis admits) -----------


def _axis_sphere(candidate: CandidateContext, consuming: ConsumingContext) -> AxisOutcome:
    if consuming.scope is None or candidate.sphere is None:
        return AxisOutcome(
            axis="sphere", admitted=False, tier=AdmissionTier.NONE, reason=REASON_SCOPE_UNRESOLVED
        )
    if candidate.sphere == consuming.scope:
        return AxisOutcome(
            axis="sphere", admitted=True, tier=AdmissionTier.ACTION, reason=REASON_SAME_SCOPE
        )
    if candidate.shared_participation or candidate.cross_scope_allowance:
        return AxisOutcome(
            axis="sphere", admitted=True, tier=AdmissionTier.ACTION, reason=REASON_CROSS_SPHERE_ALLOWED
        )
    return AxisOutcome(
        axis="sphere",
        admitted=False,
        tier=AdmissionTier.NONE,
        reason=REASON_CROSS_SPHERE_NO_ALLOWANCE,
    )


def _axis_memory_class(candidate: CandidateContext) -> AxisOutcome:
    if not candidate.is_memory:
        # non-memory context: this axis is not binding
        return AxisOutcome(
            axis="memory_class", admitted=True, tier=AdmissionTier.ACTION, reason=REASON_NOT_MEMORY
        )
    if candidate.memory_class is None:
        return AxisOutcome(
            axis="memory_class",
            admitted=True,
            tier=AdmissionTier.READ,
            reason=REASON_MEMORY_CLASS_UNKNOWN,
        )
    ceiling = _MEMORY_CLASS_CEILING[candidate.memory_class]
    return AxisOutcome(
        axis="memory_class", admitted=True, tier=ceiling, reason=REASON_CLASS_CEILING
    )


def _axis_provenance(candidate: CandidateContext) -> AxisOutcome:
    rejected = (
        candidate.contradiction_state in {ContradictionState.CONTRADICTED, ContradictionState.REJECTED}
        or candidate.review_state is ReviewState.REJECTED
    )
    if rejected:
        return AxisOutcome(
            axis="provenance",
            admitted=False,
            tier=AdmissionTier.NONE,
            reason=REASON_CONTRADICTED_OR_REJECTED,
        )
    if candidate.review_state is ReviewState.REVISED or candidate.contradiction_state is ContradictionState.REVISED:
        return AxisOutcome(
            axis="provenance", admitted=True, tier=AdmissionTier.READ, reason=REASON_REVISED_READ_ONLY
        )
    accepted = (
        candidate.trust_archetype is TrustArchetype.HUMAN_AUTHORED_ACCEPTED
        or candidate.review_state is ReviewState.ACCEPTED
    )
    if accepted and not candidate.inferred:
        return AxisOutcome(
            axis="provenance", admitted=True, tier=AdmissionTier.ACTION, reason=REASON_PROVENANCE_OK
        )
    # inferred / raw / external / unreviewed -> read + cited-proposal, never action
    if (
        candidate.inferred
        or candidate.trust_archetype
        in {
            TrustArchetype.HUMAN_AUTHORED_RAW,
            TrustArchetype.IMPORTED_EXTERNAL,
            TrustArchetype.MACHINE_PROPOSED,
        }
        or candidate.review_state in {ReviewState.UNREVIEWED, ReviewState.REVIEWED}
    ):
        return AxisOutcome(
            axis="provenance",
            admitted=True,
            tier=AdmissionTier.CITED_PROPOSAL,
            reason=REASON_INFERRED_NO_ACTION,
        )
    # stricter-boundary-wins: unverifiable provenance -> read only
    return AxisOutcome(
        axis="provenance", admitted=True, tier=AdmissionTier.READ, reason=REASON_PROVENANCE_UNVERIFIED
    )


def _axis_consumer(consuming: ConsumingContext) -> AxisOutcome:
    if consuming.authority is None:
        return AxisOutcome(
            axis="consumer",
            admitted=False,
            tier=AdmissionTier.NONE,
            reason=REASON_UNDECLARED_CONSUMER,
        )
    return AxisOutcome(
        axis="consumer",
        admitted=True,
        tier=_CONSUMER_CEILING[consuming.authority],
        reason=REASON_CONSUMER_CEILING,
    )


def evaluate_admissibility(
    candidate: CandidateContext, consuming: ConsumingContext
) -> AdmissibilityDecision:
    """Evaluate the inbound admit-by predicate for one candidate item.

    Conjunctive + least-privilege: the admitted tier is the most restrictive
    tier returned by any axis; if any axis excludes (``NONE``), the item is
    excluded. Fail-loud on malformed input.
    """

    if not candidate.artifact_id:
        raise ValueError("CandidateContext.artifact_id must be non-empty (fail-loud).")
    if not consuming.capability_id:
        raise ValueError("ConsumingContext.capability_id must be non-empty (fail-loud).")

    axes = [
        _axis_sphere(candidate, consuming),
        _axis_memory_class(candidate),
        _axis_provenance(candidate),
        _axis_consumer(consuming),
    ]

    tier = AdmissionTier.ACTION
    for outcome in axes:
        tier = _min_tier(tier, outcome.tier)

    admitted = tier is not AdmissionTier.NONE
    if admitted:
        reason = REASON_CONSUMER_CEILING
    else:
        # surface the first excluding axis's reason
        reason = next(o.reason for o in axes if o.tier is AdmissionTier.NONE)

    return AdmissibilityDecision(
        artifact_id=candidate.artifact_id,
        admitted=admitted,
        admitted_tier=tier,
        consuming_authority=consuming.authority,
        axes=axes,
        reason=reason,
    )


class ActivationPosture(BaseModel):
    """The declared activation posture for a Cognitive Expansion capability.

    Mirrors the gate inputs in the "Expansion Activation Gate" section of
    ``docs/EMERGENT_FEATURES_MODEL.md`` (#2024).
    """

    capability_id: str
    declared_authority: ConsumingAuthority
    admissibility_declared: bool = False
    loop_precondition_green: bool = False
    reversible_write_path: bool = False
    # Fail-closed: observability must be explicitly declared green. An undeclared
    # posture is treated as not-observable and blocks activation
    # (REASON_NOT_OBSERVABLE), consistent with the other gate inputs that default
    # False.
    observable: bool = False
    scope: Optional[str] = None


class GateDecisionReceipt(BaseModel):
    """Inspectable receipt emitted per gate evaluation."""

    receipt_id: str
    capability_id: str
    consuming_authority: ConsumingAuthority
    outcome: str  # "activatable" | "blocked"
    blocked_reasons: list[str] = Field(default_factory=list)
    evaluated: list[AdmissibilityDecision] = Field(default_factory=list)
    admitted_artifact_ids: list[str] = Field(default_factory=list)
    created_at: datetime


class ActivationDecision(BaseModel):
    """The dormant->active flip decision plus its decision receipt."""

    capability_id: str
    activatable: bool
    blocked_reasons: list[str]
    admitted_artifact_ids: list[str]
    receipt: GateDecisionReceipt


def evaluate_activation(
    posture: ActivationPosture,
    candidates: list[CandidateContext],
    *,
    receipt_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> ActivationDecision:
    """Evaluate the deterministic dormant->active activation decision.

    Returns ``activatable`` only when every gate input is declared and green and
    at least one candidate is admissible at the declared authority. Otherwise
    returns ``blocked`` with structured, inspectable reasons. Never silently
    activates (no "activate anyway" path). Fail-loud on malformed input.
    """

    if not posture.capability_id:
        raise ValueError("ActivationPosture.capability_id must be non-empty (fail-loud).")

    consuming = ConsumingContext(
        capability_id=posture.capability_id,
        authority=posture.declared_authority,
        scope=posture.scope,
    )
    evaluated = [evaluate_admissibility(c, consuming) for c in candidates]
    # Require admission AT the declared authority's tier, not merely any non-NONE
    # tier: a candidate admitted only at a lower tier (e.g. READ) must not satisfy
    # a GOVERNED_EXECUTION (ACTION) activation. Fail-closed at the declared ceiling.
    declared_ceiling = _CONSUMER_CEILING[posture.declared_authority]
    admitted_ids = [
        d.artifact_id
        for d in evaluated
        if d.admitted and _TIER_RANK[d.admitted_tier] >= _TIER_RANK[declared_ceiling]
    ]

    blocked: list[str] = []
    if not posture.admissibility_declared:
        blocked.append(REASON_ADMISSIBILITY_UNDECLARED)
    if not posture.loop_precondition_green:
        blocked.append(REASON_LOOP_PRECONDITION_NOT_GREEN)
    if posture.declared_authority is ConsumingAuthority.GOVERNED_EXECUTION and not posture.reversible_write_path:
        blocked.append(REASON_NO_REVERSIBLE_WRITE_PATH)
    if not posture.observable:
        blocked.append(REASON_NOT_OBSERVABLE)
    if candidates and not admitted_ids:
        blocked.append(REASON_NO_ADMISSIBLE_CONTEXT)

    activatable = len(blocked) == 0
    outcome = "activatable" if activatable else "blocked"

    receipt = GateDecisionReceipt(
        receipt_id=receipt_id if receipt_id is not None else uuid4().hex,
        capability_id=posture.capability_id,
        consuming_authority=posture.declared_authority,
        outcome=outcome,
        blocked_reasons=blocked,
        evaluated=evaluated,
        admitted_artifact_ids=admitted_ids,
        created_at=now if now is not None else datetime.now(tz=timezone.utc),
    )

    return ActivationDecision(
        capability_id=posture.capability_id,
        activatable=activatable,
        blocked_reasons=blocked,
        admitted_artifact_ids=admitted_ids,
        receipt=receipt,
    )
