"""Tests for memory promotion, rejection, and revision lifecycle (AGENT-MEMORY-03).

Verifies the four Acceptance Criteria from Issue #1081:

1. test_promoted_memory_preserves_provenance
2. test_rejected_memory_preserves_review_receipt
3. test_revised_memory_preserves_prior_context
4. test_semantic_promotion_requires_stricter_review_than_episodic_retention
"""

from __future__ import annotations

import pytest

from app.agent_memory.candidate import (
    ContradictionState,
    MemoryCandidate,
    MemoryType,
    ReviewState,
)
from app.agent_memory.promotion import PromotedMemory, PromotionError, promote, reject, revise
from app.agent_memory.review_queue import (
    MemoryCandidateReviewQueue,
    ReviewDecision,
    ReviewStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _candidate(
    *,
    title: str = "Observed user preference",
    memory_type: MemoryType = MemoryType.PREFERENCE_MEMORY,
    inferred: bool = True,
    content: str = "User answered tersely in two consecutive sessions.",
    source_refs: list[str] | None = None,
) -> MemoryCandidate:
    return MemoryCandidate(
        title=title,
        memory_type=memory_type,
        inferred=inferred,
        content=content,
        source_refs=source_refs or ["session:2026-05-21T09:00:00Z"],
        derived_from="conversation:abc123",
        generated_by="companion_agent",
    )


def _promoted_entry(
    queue: MemoryCandidateReviewQueue,
    candidate: MemoryCandidate,
    *,
    decided_by: str = "reviewer:human",
    notes: str | None = None,
) -> object:
    queue.enqueue(candidate)
    return queue.decide(
        candidate.candidate_id,
        ReviewDecision.PROMOTE,
        decided_by=decided_by,
        notes=notes,
    )


def _rejected_entry(
    queue: MemoryCandidateReviewQueue,
    candidate: MemoryCandidate,
    *,
    decided_by: str = "reviewer:human",
    notes: str | None = "Not a stable observation.",
) -> object:
    queue.enqueue(candidate)
    return queue.decide(
        candidate.candidate_id,
        ReviewDecision.REJECT,
        decided_by=decided_by,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# AC 1 — Promotion preserves provenance and review context
# ---------------------------------------------------------------------------


def test_promoted_memory_preserves_provenance() -> None:
    """Promotion must preserve provenance and review context, not only the final value.

    AC: "Promotion preserves provenance and review context, not only the final memory value."
    Verify: tests/agent_memory/test_memory_promotion.py::test_promoted_memory_preserves_provenance
    """
    queue = MemoryCandidateReviewQueue()
    candidate = _candidate(
        title="User prefers concise technical answers",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        inferred=True,
        source_refs=["session:2026-05-21T09:00:00Z"],
    )

    entry = _promoted_entry(
        queue,
        candidate,
        decided_by="reviewer:human",
        notes="Confirmed in three consecutive sessions.",
    )

    result: PromotedMemory = promote(entry)

    # Outcome is ACCEPTED — not merely "reviewed"
    assert result.outcome is ReviewState.ACCEPTED

    # The full candidate is preserved — provenance fields survive promotion
    assert result.candidate.candidate_id == candidate.candidate_id
    assert result.candidate.title == candidate.title
    assert result.candidate.source_refs == ["session:2026-05-21T09:00:00Z"]
    assert result.candidate.derived_from == "conversation:abc123"
    assert result.candidate.generated_by == "companion_agent"

    # The review receipt fields are preserved alongside the promoted content
    assert result.decided_by == "reviewer:human"
    assert result.decided_at is not None
    assert result.decision_notes == "Confirmed in three consecutive sessions."

    # The promotion receipt itself carries a unique ID
    assert result.promotion_id is not None
    assert result.promoted_at is not None


# ---------------------------------------------------------------------------
# AC 2 — Rejection preserves the review receipt (visible outcome, not deletion)
# ---------------------------------------------------------------------------


def test_rejected_memory_preserves_review_receipt() -> None:
    """Rejection must be a visible lifecycle outcome that preserves the review receipt.

    AC: "Rejection is a visible lifecycle outcome that preserves the review receipt."
    Verify: tests/agent_memory/test_memory_promotion.py::test_rejected_memory_preserves_review_receipt
    """
    queue = MemoryCandidateReviewQueue()
    candidate = _candidate(
        title="Spurious one-off observation",
        memory_type=MemoryType.EPISODIC_MEMORY,
        inferred=True,
    )

    entry = _rejected_entry(
        queue,
        candidate,
        decided_by="reviewer:human",
        notes="Single session; not representative of a stable pattern.",
    )

    result: PromotedMemory = reject(entry)

    # Outcome is REJECTED — a distinct, inspectable lifecycle state
    assert result.outcome is ReviewState.REJECTED

    # The candidate artifact is retained — rejection is NOT deletion
    assert result.candidate.candidate_id == candidate.candidate_id
    assert result.candidate.title == "Spurious one-off observation"
    assert result.candidate.source_refs == ["session:2026-05-21T09:00:00Z"]

    # The review receipt is preserved: who rejected it, when, and why
    assert result.decided_by == "reviewer:human"
    assert result.decided_at is not None
    assert result.decision_notes == "Single session; not representative of a stable pattern."

    # The rejection receipt has its own ID and timestamp
    assert result.promotion_id is not None
    assert result.promoted_at is not None

    # The rejection entry remains visible in the queue (not deleted)
    queue_entry = queue.get(candidate.candidate_id)
    assert queue_entry.status is ReviewStatus.REJECTED
    assert queue_entry.decision_notes is not None

    # A rejected candidate must not become recallable working-context memory
    assert queue.recallable_for_working_context() == []

    # reject() raises PromotionError if the entry has a non-REJECT decision
    promote_candidate = _candidate(title="Different candidate")
    promoted_entry = _promoted_entry(queue, promote_candidate)
    with pytest.raises(PromotionError):
        reject(promoted_entry)


# ---------------------------------------------------------------------------
# AC 3 — Revision preserves earlier evidence (correction without erasure)
# ---------------------------------------------------------------------------


def test_revised_memory_preserves_prior_context() -> None:
    """Revision must preserve earlier evidence; it is a correction path, not erasure.

    AC: "Revision is a correction path that preserves earlier evidence."
    Verify: tests/agent_memory/test_memory_promotion.py::test_revised_memory_preserves_prior_context
    """
    queue = MemoryCandidateReviewQueue()
    original = _candidate(
        title="User prefers terse responses",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        inferred=True,
        content="Single session showing short replies.",
        source_refs=["session:2026-05-20T09:00:00Z"],
    )

    revision_candidate = MemoryCandidate(
        title="Revised: user prefers detail on technical topics",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        inferred=True,
        content="Multiple sessions show preference for detail in technical questions.",
        source_refs=["session:2026-05-21T09:00:00Z"],
        derived_from="conversation:def456",
        generated_by="companion_agent",
        contradiction_state=ContradictionState.CONTRADICTED,
        correction_of=original.candidate_id,
        contradiction_notes="Later sessions contradict the initial single-session observation.",
    )

    queue.enqueue(original)
    revised_queue_entry = queue.decide(
        original.candidate_id,
        ReviewDecision.REVISE,
        decided_by="reviewer:human",
        notes="Narrowed to technical-topic preference based on multi-session pattern.",
        revision=revision_candidate,
    )

    # The revised candidate enters the queue as a new pending entry
    revised_entry = queue.get(revision_candidate.candidate_id)
    assert revised_entry.status is ReviewStatus.PENDING
    assert revised_entry.revision_of == original.candidate_id

    result: PromotedMemory = revise(revised_queue_entry, revised_entry)

    # Outcome is REVISED — a distinct lifecycle state from ACCEPTED or REJECTED
    assert result.outcome is ReviewState.REVISED

    # The original candidate's evidence is preserved in the artifact
    assert result.candidate.candidate_id == original.candidate_id
    assert result.candidate.title == "User prefers terse responses"
    assert result.candidate.source_refs == ["session:2026-05-20T09:00:00Z"]
    assert result.candidate.content == "Single session showing short replies."

    # The review receipt is preserved: reviewer, timestamp, notes
    assert result.decided_by == "reviewer:human"
    assert result.decided_at is not None
    assert result.decision_notes is not None

    # The revision_of field links forward to the revised successor,
    # so the correction chain is traceable
    assert result.revision_of == revision_candidate.candidate_id

    # The original queue entry shows REVISED status — evidence is not deleted
    original_queue_entry = queue.get(original.candidate_id)
    assert original_queue_entry.status is ReviewStatus.REVISED

    # revise() raises PromotionError if revised_entry does not link to the original
    unrelated = _candidate(title="Unrelated candidate")
    queue.enqueue(unrelated)
    # Manually produce an entry with wrong revision_of by using a non-revision candidate
    # (revision_of=None does not match original.candidate_id)
    from app.agent_memory.review_queue import ReviewEntry, ReviewStatus as RS
    wrong_link_entry = ReviewEntry(
        candidate=unrelated,
        status=RS.PENDING,
        revision_of=None,  # does not reference original
    )
    with pytest.raises(PromotionError):
        revise(revised_queue_entry, wrong_link_entry)


# ---------------------------------------------------------------------------
# AC 4 — Semantic promotion requires stricter review than episodic retention
# ---------------------------------------------------------------------------


def test_semantic_promotion_requires_stricter_review_than_episodic_retention() -> None:
    """Semantic promotion (semantic_memory) requires stricter review evidence.

    AC: "Promotion into stronger knowledge posture (semantic) requires stricter review
    than episodic retention."
    Verify: tests/agent_memory/test_memory_promotion.py::
             test_semantic_promotion_requires_stricter_review_than_episodic_retention
    """
    queue = MemoryCandidateReviewQueue()

    # --- Episodic promotion: inferred + single source is allowed ---
    episodic_candidate = _candidate(
        title="User episodic event",
        memory_type=MemoryType.EPISODIC_MEMORY,
        inferred=True,
        source_refs=["session:2026-05-21T09:00:00Z"],
    )
    episodic_entry = _promoted_entry(queue, episodic_candidate)
    episodic_result = promote(episodic_entry)
    assert episodic_result.outcome is ReviewState.ACCEPTED

    # --- Semantic promotion: inferred + single source is NOT sufficient ---
    weak_semantic_candidate = _candidate(
        title="Agent-inferred semantic claim with one source",
        memory_type=MemoryType.SEMANTIC_MEMORY,
        inferred=True,  # inferred, only one source reference
        source_refs=["session:2026-05-21T09:00:00Z"],
    )
    weak_entry = _promoted_entry(queue, weak_semantic_candidate)
    with pytest.raises(PromotionError, match="stricter review evidence"):
        promote(weak_entry)

    # --- Semantic promotion: asserted (non-inferred) is allowed ---
    asserted_semantic_candidate = _candidate(
        title="Human-asserted semantic fact",
        memory_type=MemoryType.SEMANTIC_MEMORY,
        inferred=False,  # explicitly asserted by a reviewer
        source_refs=["note:explicit-knowledge.md"],
    )
    asserted_entry = _promoted_entry(queue, asserted_semantic_candidate)
    asserted_result = promote(asserted_entry)
    assert asserted_result.outcome is ReviewState.ACCEPTED

    # --- Semantic promotion: inferred but multi-source is allowed ---
    multi_source_semantic_candidate = _candidate(
        title="Agent-inferred semantic claim with multi-session evidence",
        memory_type=MemoryType.SEMANTIC_MEMORY,
        inferred=True,
        source_refs=[
            "session:2026-05-19T09:00:00Z",
            "session:2026-05-20T09:00:00Z",
        ],
    )
    multi_source_entry = _promoted_entry(queue, multi_source_semantic_candidate)
    multi_source_result = promote(multi_source_entry)
    assert multi_source_result.outcome is ReviewState.ACCEPTED

    # --- promote() raises PromotionError for candidates with non-PROMOTE decision ---
    reject_semantic_candidate = _candidate(
        title="Rejected semantic candidate",
        memory_type=MemoryType.SEMANTIC_MEMORY,
        inferred=False,
    )
    reject_entry = _rejected_entry(queue, reject_semantic_candidate)
    with pytest.raises(PromotionError):
        promote(reject_entry)


# ---------------------------------------------------------------------------
# Immutability and lifecycle invariants
# ---------------------------------------------------------------------------


def test_promoted_memory_is_immutable() -> None:
    """PromotedMemory must be frozen — it is an audit receipt, not a cursor."""
    queue = MemoryCandidateReviewQueue()
    candidate = _candidate()
    entry = _promoted_entry(queue, candidate)
    result = promote(entry)

    with pytest.raises(Exception):
        result.outcome = ReviewState.REJECTED  # type: ignore[misc]

    with pytest.raises(Exception):
        result.decided_by = "tampered"  # type: ignore[misc]


def test_revise_rejects_already_rejected_revised_entry() -> None:
    """revise() must reject a revised_entry whose status is REJECTED — the lifecycle
    chain would otherwise be inconsistent (a rejected entry cannot be a valid successor).
    """
    from app.agent_memory.review_queue import ReviewStatus as RS

    queue = MemoryCandidateReviewQueue()
    original = _candidate(title="Original candidate")
    revision_candidate = _candidate(title="Revision candidate")

    queue.enqueue(original)
    # Queue API: REVISE records a decision on original and auto-enqueues revision_candidate
    queue.decide(
        original.candidate_id,
        ReviewDecision.REVISE,
        decided_by="reviewer:human",
        revision=revision_candidate,
    )
    # Now reject the revision successor
    queue.decide(
        revision_candidate.candidate_id,
        ReviewDecision.REJECT,
        decided_by="reviewer:human",
    )

    original_entry = queue.get(original.candidate_id)
    revision_entry = queue.get(revision_candidate.candidate_id)

    assert revision_entry.status is RS.REJECTED

    with pytest.raises(PromotionError, match="PENDING or PROMOTED"):
        revise(original_entry, revision_entry)
