from __future__ import annotations

from datetime import datetime, timezone

from app.agent_memory.candidate import (
    ContradictionState,
    MemoryCandidate,
    MemoryType,
    ReviewState,
)
from app.agent_memory.memory_record import (
    MemoryRecordScope,
    memory_record_from_recall_candidate,
    memory_record_from_review_entry,
)
from app.agent_memory.promotion import PromotedMemory
from app.agent_memory.recall_retrieval import RecallCandidate
from app.agent_memory.review_queue import MemoryCandidateReviewQueue, ReviewDecision


def _candidate(
    *,
    candidate_id: str = "candidate-memory-record",
    memory_type: MemoryType = MemoryType.SEMANTIC_MEMORY,
    review_state: ReviewState = ReviewState.ACCEPTED,
    inferred: bool = False,
) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id=candidate_id,
        title="Design docs before code",
        memory_type=memory_type,
        review_state=review_state,
        inferred=inferred,
        content="The user prefers reading owner docs before implementation.",
        source_refs=["note:source.md", "session:2026-06-21T08:00:00Z"],
        derived_from="vault:source.md",
        generated_by="companion_agent",
        confidence="reviewed",
        contradiction_state=ContradictionState.CLEAR,
    )


def _promoted(candidate: MemoryCandidate) -> PromotedMemory:
    return PromotedMemory(
        promotion_id="promotion-001",
        outcome=ReviewState.ACCEPTED,
        candidate=candidate,
        decided_by="companion-ui:reviewer",
        decided_at=datetime(2026, 6, 21, 8, 30, tzinfo=timezone.utc),
        decision_notes="Confirmed by human review.",
        promoted_at=datetime(2026, 6, 21, 8, 31, tzinfo=timezone.utc),
    )


def test_recall_candidate_maps_to_memory_record_lifecycle_fields() -> None:
    recall = RecallCandidate(
        promoted=_promoted(_candidate()),
        score=4.0,
        reason="title matched design",
        artifact_path="Agent Memory/design-docs-before-code.md",
        receipt_id="receipt-materialized",
    )

    record = memory_record_from_recall_candidate(
        recall,
        scope=MemoryRecordScope(
            active_context_ref="active-context:test",
            vault_id="vault-alpha",
            artifact_path=recall.artifact_path,
        ),
    )

    assert record.record_id == "candidate-memory-record"
    assert record.memory_class == "semantic_memory"
    assert record.review.state == "accepted"
    assert record.review.reviewed_by == "companion-ui:reviewer"
    assert record.source.source_refs == [
        "note:source.md",
        "session:2026-06-21T08:00:00Z",
    ]
    assert record.source.artifact_path == "Agent Memory/design-docs-before-code.md"
    assert record.source.promotion_receipt_id == "receipt-materialized"
    assert record.lifecycle.promoted_at is not None
    assert record.staleness.state == "unknown"


def test_review_entry_projection_marks_transitional_fields_unavailable() -> None:
    queue = MemoryCandidateReviewQueue()
    entry = queue.enqueue(
        _candidate(
            candidate_id="candidate-pending",
            review_state=ReviewState.UNREVIEWED,
            inferred=True,
        )
    )

    record = memory_record_from_review_entry(entry)

    assert record.status == "pending"
    assert record.review.state == "unreviewed"
    assert record.authority.may_recall is False
    assert record.authority.may_write is False
    unavailable = {item.field for item in record.unavailable_fields}
    assert "scope.active_context_ref" in unavailable
    assert "staleness.timestamp" in unavailable
    assert "lifecycle.archived_at" in unavailable
    assert "forgetting.receipt_id" in unavailable


def test_memory_record_preserves_gov_promotion_boundary() -> None:
    queue = MemoryCandidateReviewQueue()
    candidate = _candidate(memory_type=MemoryType.PREFERENCE_MEMORY)
    queue.enqueue(candidate)
    entry = queue.decide(
        candidate.candidate_id,
        ReviewDecision.PROMOTE,
        decided_by="human://reviewer",
        notes="Preference confirmed.",
    )

    record = memory_record_from_review_entry(entry, promotion_receipt_id="receipt-review")

    assert record.authority.may_answer is True
    assert record.authority.may_propose is True
    assert record.authority.may_write is False
    assert record.promotion.requires_gov is True
    assert record.promotion.target == "GOV/HKA"
    assert record.promotion.hidden_in_mem is False
    assert record.promotion.receipt_id == "receipt-review"
