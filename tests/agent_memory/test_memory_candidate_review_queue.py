from __future__ import annotations

import pytest

from app.agent_memory.candidate import (
    ContradictionState,
    MemoryCandidate,
    MemoryType,
    ReviewState,
)
from app.agent_memory.review_queue import (
    MemoryCandidateReviewQueue,
    ReviewDecision,
    ReviewQueueError,
    ReviewStatus,
)


def _candidate(
    *,
    title: str = "Observed user preference",
    memory_type: MemoryType = MemoryType.PREFERENCE_MEMORY,
    inferred: bool = True,
    content: str = "User answered tersely in two consecutive sessions.",
) -> MemoryCandidate:
    return MemoryCandidate(
        title=title,
        memory_type=memory_type,
        inferred=inferred,
        content=content,
        source_refs=["session:2026-05-21T09:00:00Z"],
        derived_from="conversation:abc123",
        generated_by="companion_agent",
    )


def test_review_queue_requires_human_decision() -> None:
    queue = MemoryCandidateReviewQueue()
    candidate = _candidate()

    entry = queue.enqueue(candidate)

    assert entry.status is ReviewStatus.PENDING
    assert entry.decision is None
    assert entry.decided_by is None
    assert entry.decided_at is None
    assert entry.candidate.review_state is ReviewState.UNREVIEWED

    pending = queue.pending()
    assert [e.candidate_id for e in pending] == [candidate.candidate_id]
    assert queue.decided() == []

    # An entry is only promoted when a reviewer makes an explicit decision.
    # Empty and whitespace-only decided_by values are not real decisions and must be refused.
    with pytest.raises(ReviewQueueError):
        queue.decide(candidate.candidate_id, ReviewDecision.PROMOTE, decided_by="")

    with pytest.raises(ReviewQueueError):
        queue.decide(candidate.candidate_id, ReviewDecision.PROMOTE, decided_by="   ")

    # Without a recorded decision the queue continues to treat the candidate as pending.
    assert queue.get(candidate.candidate_id).status is ReviewStatus.PENDING

    decided = queue.decide(
        candidate.candidate_id,
        ReviewDecision.PROMOTE,
        decided_by="reviewer:rasmus",
        notes="Confirmed in latest session.",
    )

    assert decided.status is ReviewStatus.PROMOTED
    assert decided.decision is ReviewDecision.PROMOTE
    assert decided.decided_by == "reviewer:rasmus"
    assert decided.decided_at is not None

    # A decided entry cannot be silently re-decided.
    with pytest.raises(ReviewQueueError):
        queue.decide(
            candidate.candidate_id,
            ReviewDecision.REJECT,
            decided_by="reviewer:rasmus",
        )


def test_review_queue_exposes_candidate_provenance_and_class() -> None:
    queue = MemoryCandidateReviewQueue()
    candidate = _candidate(
        title="Proposed semantic fact about user domain",
        memory_type=MemoryType.SEMANTIC_MEMORY,
        inferred=True,
        content="User works in clinical genomics tooling.",
    )

    entry = queue.enqueue(candidate)

    assert entry.title == "Proposed semantic fact about user domain"
    assert entry.content == "User works in clinical genomics tooling."
    assert entry.proposed_memory_type is MemoryType.SEMANTIC_MEMORY
    assert entry.source_refs == ["session:2026-05-21T09:00:00Z"]
    assert entry.derived_from == "conversation:abc123"
    assert entry.generated_by == "companion_agent"
    # Inferred-vs-reviewed posture must remain visible during review.
    assert entry.inferred is True
    assert entry.review_posture == "inferred"
    # Proposed class must not be presented as a promoted/authoritative class.
    assert entry.candidate.review_state is ReviewState.UNREVIEWED
    assert entry.status is ReviewStatus.PENDING

    asserted_candidate = MemoryCandidate(
        title="User explicitly stated preference",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        source_refs=["note:explicit-preference.md"],
        derived_from="vault:notes/preferences.md",
        generated_by="human",
        inferred=False,
    )
    asserted_entry = queue.enqueue(asserted_candidate)
    assert asserted_entry.inferred is False
    assert asserted_entry.review_posture == "asserted"


def test_review_queue_supports_promote_reject_and_revise() -> None:
    queue = MemoryCandidateReviewQueue()

    promote_c = _candidate(title="Promote me")
    reject_c = _candidate(title="Reject me")
    revise_c = _candidate(title="Revise me", content="Single-session bias.")

    queue.enqueue(promote_c)
    queue.enqueue(reject_c)
    queue.enqueue(revise_c)

    promoted = queue.decide(
        promote_c.candidate_id,
        ReviewDecision.PROMOTE,
        decided_by="reviewer:rasmus",
    )
    rejected = queue.decide(
        reject_c.candidate_id,
        ReviewDecision.REJECT,
        decided_by="reviewer:rasmus",
        notes="Observation was a one-off; not a stable preference.",
    )

    revision_candidate = MemoryCandidate(
        title="Revised: user prefers detailed responses on technical topics",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        source_refs=["session:2026-05-21T10:00:00Z"],
        derived_from="conversation:def456",
        generated_by="companion_agent",
        inferred=True,
        contradiction_state=ContradictionState.CONTRADICTED,
        correction_of=revise_c.candidate_id,
        contradiction_notes="Later sessions contradict the original observation.",
    )
    revised = queue.decide(
        revise_c.candidate_id,
        ReviewDecision.REVISE,
        decided_by="reviewer:rasmus",
        notes="Narrowed to technical-topic preference.",
        revision=revision_candidate,
    )

    assert promoted.status is ReviewStatus.PROMOTED
    assert rejected.status is ReviewStatus.REJECTED
    assert revised.status is ReviewStatus.REVISED
    assert {promoted.decision, rejected.decision, revised.decision} == {
        ReviewDecision.PROMOTE,
        ReviewDecision.REJECT,
        ReviewDecision.REVISE,
    }

    # Rejection is preserved with reason; it is not silent deletion.
    assert rejected.decision_notes is not None
    assert queue.get(reject_c.candidate_id).status is ReviewStatus.REJECTED

    # Revision preserves prior evidence: original entry is still recoverable as REVISED,
    # and the revised candidate enters the queue as a new pending entry that references
    # the prior candidate.
    revised_entry = queue.get(revision_candidate.candidate_id)
    assert revised_entry.status is ReviewStatus.PENDING
    assert revised_entry.revision_of == revise_c.candidate_id
    assert revised_entry.candidate.correction_of == revise_c.candidate_id

    # Revise requires an explicit revised candidate; calling without one is refused.
    other = _candidate(title="No revision payload")
    queue.enqueue(other)
    with pytest.raises(ReviewQueueError):
        queue.decide(
            other.candidate_id,
            ReviewDecision.REVISE,
            decided_by="reviewer:rasmus",
        )


def test_review_queue_does_not_authorize_unreviewed_recall() -> None:
    queue = MemoryCandidateReviewQueue()
    unreviewed = _candidate(title="Unreviewed observation")
    to_reject = _candidate(title="Rejected observation")
    to_promote = _candidate(title="Confirmed preference", inferred=False)

    queue.enqueue(unreviewed)
    queue.enqueue(to_reject)
    queue.enqueue(to_promote)

    # Before any review, no candidate is recallable as authoritative working-context memory.
    assert queue.recallable_for_working_context() == []

    queue.decide(
        to_reject.candidate_id,
        ReviewDecision.REJECT,
        decided_by="reviewer:rasmus",
        notes="Not a real preference.",
    )

    # A rejected candidate must never become recallable working-context memory.
    recallable_after_reject = queue.recallable_for_working_context()
    assert recallable_after_reject == []

    queue.decide(
        to_promote.candidate_id,
        ReviewDecision.PROMOTE,
        decided_by="reviewer:rasmus",
    )

    recallable_after_promote = queue.recallable_for_working_context()
    assert [e.candidate_id for e in recallable_after_promote] == [to_promote.candidate_id]

    # The unreviewed candidate, even with high apparent confidence, must remain excluded
    # from working-context recall until an explicit decision is recorded.
    assert all(
        e.candidate_id != unreviewed.candidate_id
        for e in recallable_after_promote
    )
