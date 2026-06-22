"""MemoryRecord-shaped adapters for current agent-memory paths (#2360)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from app.agent_memory.candidate import MemoryCandidate, ReviewState
from app.agent_memory.promotion import PromotedMemory
from app.agent_memory.review_queue import ReviewEntry, ReviewStatus

MemoryRecordUnavailableReason = Literal[
    "not_captured_by_current_path",
    "not_implemented_in_current_lifecycle",
]


class UnavailableMemoryRecordField(BaseModel):
    field: str
    reason: MemoryRecordUnavailableReason


class MemoryRecallCandidate(Protocol):
    promoted: PromotedMemory
    artifact_path: str | None
    receipt_id: str | None


class MemoryRecordScope(BaseModel):
    active_context_ref: str | None = None
    vault_id: str | None = None
    artifact_path: str | None = None


class MemoryRecordSource(BaseModel):
    source_refs: list[str] = Field(default_factory=list)
    derived_from: str | None = None
    generated_by: str | None = None
    artifact_path: str | None = None
    promotion_receipt_id: str | None = None


class MemoryRecordReview(BaseModel):
    state: str
    status: str
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    decision_notes: str | None = None


class MemoryRecordAuthority(BaseModel):
    may_recall: bool
    may_answer: bool
    may_propose: bool
    may_write: bool = False


class MemoryRecordLifecycle(BaseModel):
    observed_at: datetime
    promoted_at: datetime | None = None
    archived_at: datetime | None = None
    forgotten_at: datetime | None = None
    correction_of: str | None = None
    contradiction_state: str
    contradiction_notes: str | None = None


class MemoryRecordStaleness(BaseModel):
    state: Literal["fresh", "stale", "unknown"] = "unknown"
    reason: str


class MemoryRecordForgetting(BaseModel):
    state: Literal["not_requested", "unavailable"] = "unavailable"
    receipt_id: str | None = None
    reason: str


class MemoryRecordPromotion(BaseModel):
    requires_gov: bool = True
    target: str = "GOV/HKA"
    hidden_in_mem: bool = False
    receipt_id: str | None = None


class MemoryRecord(BaseModel):
    record_id: str
    memory_class: str
    status: str
    title: str
    content: str | None = None
    inferred: bool
    confidence: str | None = None
    scope: MemoryRecordScope
    source: MemoryRecordSource
    review: MemoryRecordReview
    authority: MemoryRecordAuthority
    lifecycle: MemoryRecordLifecycle
    staleness: MemoryRecordStaleness
    forgetting: MemoryRecordForgetting
    promotion: MemoryRecordPromotion
    unavailable_fields: list[UnavailableMemoryRecordField] = Field(default_factory=list)


def memory_record_from_review_entry(
    entry: ReviewEntry,
    *,
    scope: MemoryRecordScope | None = None,
    artifact_path: str | None = None,
    promotion_receipt_id: str | None = None,
) -> MemoryRecord:
    """Project a review-queue entry into the target MemoryRecord envelope."""
    candidate = entry.candidate
    return _memory_record_from_candidate(
        candidate,
        status=entry.status.value,
        review=MemoryRecordReview(
            state=_review_state_for_status(entry.status).value,
            status=entry.status.value,
            reviewed_by=entry.decided_by,
            reviewed_at=entry.decided_at,
            decision_notes=entry.decision_notes,
        ),
        authority=_authority_for_status(entry.status),
        promoted_at=entry.decided_at if entry.status is ReviewStatus.PROMOTED else None,
        scope=scope,
        artifact_path=artifact_path,
        promotion_receipt_id=promotion_receipt_id,
    )


def memory_record_from_promoted(
    promoted: PromotedMemory,
    *,
    scope: MemoryRecordScope | None = None,
    artifact_path: str | None = None,
    promotion_receipt_id: str | None = None,
) -> MemoryRecord:
    """Project a promoted memory lifecycle record into a MemoryRecord envelope."""
    candidate = promoted.candidate
    return _memory_record_from_candidate(
        candidate,
        status=promoted.outcome.value,
        review=MemoryRecordReview(
            state=_effective_review_state(promoted).value,
            status=promoted.outcome.value,
            reviewed_by=promoted.decided_by,
            reviewed_at=promoted.decided_at,
            decision_notes=promoted.decision_notes,
        ),
        authority=MemoryRecordAuthority(
            may_recall=promoted.outcome is ReviewState.ACCEPTED,
            may_answer=promoted.outcome is ReviewState.ACCEPTED,
            may_propose=promoted.outcome is ReviewState.ACCEPTED,
            may_write=False,
        ),
        promoted_at=(
            promoted.promoted_at
            if promoted.outcome is ReviewState.ACCEPTED
            else None
        ),
        scope=scope,
        artifact_path=artifact_path,
        promotion_receipt_id=promotion_receipt_id or promoted.promotion_id,
    )


def memory_record_from_recall_candidate(
    candidate: MemoryRecallCandidate,
    *,
    scope: MemoryRecordScope | None = None,
) -> MemoryRecord:
    """Project the current promoted-memory recall output into MemoryRecord shape."""
    return memory_record_from_promoted(
        candidate.promoted,
        scope=scope,
        artifact_path=candidate.artifact_path,
        promotion_receipt_id=candidate.receipt_id or candidate.promoted.promotion_id,
    )


def _memory_record_from_candidate(
    candidate: MemoryCandidate,
    *,
    status: str,
    review: MemoryRecordReview,
    authority: MemoryRecordAuthority,
    promoted_at: datetime | None,
    scope: MemoryRecordScope | None,
    artifact_path: str | None,
    promotion_receipt_id: str | None,
) -> MemoryRecord:
    resolved_scope = scope or MemoryRecordScope(artifact_path=artifact_path)
    unavailable = _unavailable_fields(resolved_scope, candidate)
    return MemoryRecord(
        record_id=candidate.candidate_id,
        memory_class=candidate.memory_type.value,
        status=status,
        title=candidate.title,
        content=candidate.content,
        inferred=candidate.inferred,
        confidence=candidate.confidence,
        scope=resolved_scope,
        source=MemoryRecordSource(
            source_refs=list(candidate.source_refs),
            derived_from=candidate.derived_from,
            generated_by=candidate.generated_by,
            artifact_path=artifact_path,
            promotion_receipt_id=promotion_receipt_id,
        ),
        review=review,
        authority=authority,
        lifecycle=MemoryRecordLifecycle(
            observed_at=candidate.observed_at,
            promoted_at=promoted_at,
            correction_of=candidate.correction_of,
            contradiction_state=candidate.contradiction_state.value,
            contradiction_notes=candidate.contradiction_notes,
        ),
        staleness=MemoryRecordStaleness(
            reason="current memory lifecycle does not yet persist explicit staleness posture",
        ),
        forgetting=MemoryRecordForgetting(
            reason="archive/forget/tombstone lifecycle is specified but not implemented on this path",
        ),
        promotion=MemoryRecordPromotion(receipt_id=promotion_receipt_id),
        unavailable_fields=unavailable,
    )


def _review_state_for_status(status: ReviewStatus) -> ReviewState:
    """Map a review-queue decision status to the effective MemoryRecord review state.

    A review entry records the decision on ``status``/``decision`` without mutating
    the embedded candidate's original ``review_state`` (which commonly stays
    ``unreviewed``). The MemoryRecord review posture must reflect the decision so it
    cannot contradict the authority granted for the same status.
    """
    return {
        ReviewStatus.PENDING: ReviewState.UNREVIEWED,
        ReviewStatus.PROMOTED: ReviewState.ACCEPTED,
        ReviewStatus.REJECTED: ReviewState.REJECTED,
        ReviewStatus.REVISED: ReviewState.REVISED,
    }[status]


def _authority_for_status(status: ReviewStatus) -> MemoryRecordAuthority:
    promoted = status is ReviewStatus.PROMOTED
    return MemoryRecordAuthority(
        may_recall=promoted,
        may_answer=promoted,
        may_propose=promoted,
        may_write=False,
    )


def _effective_review_state(promoted: PromotedMemory) -> ReviewState:
    """Derive the review state from the promotion outcome, not the candidate.

    ``reject()`` / ``revise()`` build a ``PromotedMemory`` from the original
    candidate without mutating ``candidate.review_state`` (it commonly stays
    ``unreviewed``). ``promoted.outcome`` is the explicit decision, so the
    MemoryRecord review posture must come from it for every outcome.
    """
    return promoted.outcome


def _unavailable_fields(
    scope: MemoryRecordScope,
    candidate: MemoryCandidate,
) -> list[UnavailableMemoryRecordField]:
    fields: list[UnavailableMemoryRecordField] = []
    if scope.active_context_ref is None:
        fields.append(
            UnavailableMemoryRecordField(
                field="scope.active_context_ref",
                reason="not_captured_by_current_path",
            )
        )
    if candidate.confidence is None:
        fields.append(
            UnavailableMemoryRecordField(
                field="confidence",
                reason="not_captured_by_current_path",
            )
        )
    fields.extend(
        [
            UnavailableMemoryRecordField(
                field="staleness.timestamp",
                reason="not_implemented_in_current_lifecycle",
            ),
            UnavailableMemoryRecordField(
                field="lifecycle.archived_at",
                reason="not_implemented_in_current_lifecycle",
            ),
            UnavailableMemoryRecordField(
                field="forgetting.receipt_id",
                reason="not_implemented_in_current_lifecycle",
            ),
        ]
    )
    return fields


__all__ = [
    "MemoryRecord",
    "MemoryRecordAuthority",
    "MemoryRecordForgetting",
    "MemoryRecordLifecycle",
    "MemoryRecordPromotion",
    "MemoryRecordReview",
    "MemoryRecallCandidate",
    "MemoryRecordScope",
    "MemoryRecordSource",
    "MemoryRecordStaleness",
    "UnavailableMemoryRecordField",
    "memory_record_from_promoted",
    "memory_record_from_recall_candidate",
    "memory_record_from_review_entry",
]
