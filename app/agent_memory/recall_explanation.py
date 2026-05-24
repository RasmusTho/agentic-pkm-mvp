"""Explainable recall surfaces for agentic memory artifacts (AGENT-MEMORY-04).

This module builds inspectable recall explanations from reviewed/promotion
records. It does not implement retrieval, activation engines, or UI rendering.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from app.agent_memory.candidate import ReviewState
from app.agent_memory.promotion import PromotedMemory


class RecallUseRight(str, Enum):
    ACTIVATABLE = "activatable"
    INSTRUCTIONAL = "instructional"
    ACTION_AUTHORIZING = "action_authorizing"


class ActivationReason(str, Enum):
    EXPLICIT_REFERENCE = "explicit_reference"
    CONTEXTUAL_RELEVANCE = "contextual_relevance"
    POLICY_APPLICABILITY = "policy_applicability"
    RESUME_CONTINUITY = "resume_continuity"
    AUTHORITY_SIGNAL = "authority_signal"


class MemoryLifecycleState(str, Enum):
    PROMOTED = "promoted"
    REVISED = "revised"
    REJECTED = "rejected"


class SourceProvenance(BaseModel):
    source_refs: list[str] = Field(default_factory=list)
    derived_from: Optional[str] = None
    generated_by: Optional[str] = None


class RecallExplanation(BaseModel):
    artifact_id: str
    title: str
    artifact_class: str
    artifact_type: Optional[str] = None
    memory_type: str
    use_right: RecallUseRight
    lifecycle_state: MemoryLifecycleState
    review_state: ReviewState
    activation_reason: ActivationReason
    why_now: str
    bundle_reference: Optional[str] = None
    source_provenance: SourceProvenance
    authority_limits: list[str] = Field(default_factory=list)
    behavioral_claim: Optional[str] = None
    action_scope: Optional[str] = None
    authority_source: Optional[str] = None
    receipt_reference: Optional[str] = None


def _lifecycle_state(promoted: PromotedMemory) -> MemoryLifecycleState:
    if promoted.outcome is ReviewState.REVISED:
        return MemoryLifecycleState.REVISED
    if promoted.outcome is ReviewState.REJECTED:
        return MemoryLifecycleState.REJECTED
    return MemoryLifecycleState.PROMOTED


def _authority_limits(promoted: PromotedMemory, use_right: RecallUseRight) -> list[str]:
    limits: list[str] = [
        "memory_is_supporting_input_not_source_of_truth",
    ]

    if use_right is not RecallUseRight.ACTION_AUTHORIZING:
        limits.append("does_not_authorize_writeback")

    if promoted.candidate.review_state is not ReviewState.ACCEPTED:
        limits.append("requires_accepted_review_state_for_instructional_use")

    if promoted.candidate.inferred:
        limits.append("inferred_memory_requires_review_visibility")

    if promoted.outcome is ReviewState.REJECTED:
        limits.append("rejected_memory_is_non_authoritative")

    if promoted.outcome is ReviewState.REVISED:
        limits.append("revised_memory_requires_current_revision_for_authority")

    return limits

def _effective_review_state(promoted: PromotedMemory) -> ReviewState:
    if promoted.outcome is ReviewState.ACCEPTED:
        return ReviewState.ACCEPTED
    return promoted.candidate.review_state


def build_recall_explanation(
    promoted: PromotedMemory,
    *,
    use_right: RecallUseRight,
    activation_reason: ActivationReason,
    why_now: str,
    bundle_reference: Optional[str] = None,
    behavioral_claim: Optional[str] = None,
    action_scope: Optional[str] = None,
    authority_source: Optional[str] = None,
    receipt_reference: Optional[str] = None,
) -> RecallExplanation:
    """Create a recall explanation for a promoted/reviewed memory artifact.

    Enforces minimum explanation requirements from context-activation semantics:
    instructional recalls must carry accepted review state + behavioral claim;
    action-authorizing recalls must also carry explicit action scope,
    authority source, and receipt reference.
    """

    effective_review_state = _effective_review_state(promoted)

    if use_right is RecallUseRight.INSTRUCTIONAL:
        if effective_review_state is not ReviewState.ACCEPTED:
            raise ValueError(
                "instructional recall requires review_state=accepted"
            )
        if not behavioral_claim:
            raise ValueError("instructional recall requires a behavioral_claim")

    if use_right is RecallUseRight.ACTION_AUTHORIZING:
        if effective_review_state is not ReviewState.ACCEPTED:
            raise ValueError(
                "action_authorizing recall requires review_state=accepted"
            )
        if not behavioral_claim or not action_scope or not authority_source or not receipt_reference:
            raise ValueError(
                "action_authorizing recall requires behavioral_claim, action_scope, authority_source, and receipt_reference"
            )

    return RecallExplanation(
        artifact_id=promoted.candidate.candidate_id,
        title=promoted.candidate.title,
        artifact_class=promoted.candidate.artifact_class,
        artifact_type=promoted.candidate.artifact_type,
        memory_type=promoted.candidate.memory_type.value,
        use_right=use_right,
        lifecycle_state=_lifecycle_state(promoted),
        review_state=effective_review_state,
        activation_reason=activation_reason,
        why_now=why_now,
        bundle_reference=bundle_reference,
        source_provenance=SourceProvenance(
            source_refs=list(promoted.candidate.source_refs),
            derived_from=promoted.candidate.derived_from,
            generated_by=promoted.candidate.generated_by,
        ),
        authority_limits=_authority_limits(promoted, use_right),
        behavioral_claim=behavioral_claim,
        action_scope=action_scope,
        authority_source=authority_source,
        receipt_reference=receipt_reference,
    )
