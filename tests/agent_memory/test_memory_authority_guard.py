"""Tests for memory authority guard (AGENT-MEMORY-05).

Verifies the four Acceptance Criteria from Issue #1083:

1. test_unreviewed_memory_cannot_authorize_writeback
2. test_memory_cannot_override_human_authored_truth
3. test_memory_authority_guard_requires_posture_visibility
4. test_memory_supports_suggestion_without_escalating_to_mutation_authority
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.agent_memory.authority_guard import (
    AuthorityGuardError,
    assert_does_not_override_human_truth,
    assert_posture_visible,
    assert_suggestion_only,
    assert_writeback_authorized,
)
from app.agent_memory.candidate import (
    ActivationPolicy,
    ContradictionState,
    MemoryCandidate,
    MemoryType,
    ReviewState,
)
from app.agent_memory.promotion import PromotedMemory
from app.agent_memory.recall_explanation import UseRight
from app.agent_memory.review_queue import ReviewEntry, ReviewStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _candidate(
    *,
    title: str = "User prefers concise answers",
    memory_type: MemoryType = MemoryType.PREFERENCE_MEMORY,
    inferred: bool = True,
    source_refs: list[str] | None = None,
    review_state: ReviewState = ReviewState.UNREVIEWED,
    activation_policy: ActivationPolicy | None = None,
    contradiction_state: ContradictionState = ContradictionState.CLEAR,
    contradiction_notes: str | None = None,
) -> MemoryCandidate:
    if activation_policy is None:
        if review_state is ReviewState.UNREVIEWED:
            activation_policy = ActivationPolicy.REVIEW_QUEUE_ONLY
        else:
            activation_policy = ActivationPolicy.EXPLICIT_OR_CONTEXTUAL
    return MemoryCandidate(
        title=title,
        memory_type=memory_type,
        inferred=inferred,
        source_refs=source_refs or ["session:2026-05-21T09:00:00Z"],
        derived_from="conversation:abc123",
        generated_by="companion_agent",
        review_state=review_state,
        activation_policy=activation_policy,
        contradiction_state=contradiction_state,
        contradiction_notes=contradiction_notes,
    )


def _promoted_memory(
    *,
    candidate: MemoryCandidate | None = None,
    outcome: ReviewState = ReviewState.ACCEPTED,
    decided_by: str = "reviewer:rasmus",
    decision_notes: str | None = None,
    revision_of: str | None = None,
) -> PromotedMemory:
    c = candidate or _candidate(
        review_state=ReviewState.ACCEPTED,
        inferred=False,
    )
    return PromotedMemory(
        outcome=outcome,
        candidate=c,
        decided_by=decided_by,
        decided_at=datetime.now(timezone.utc),
        decision_notes=decision_notes,
        revision_of=revision_of,
    )


def _review_entry(
    *,
    candidate: MemoryCandidate | None = None,
    status: ReviewStatus = ReviewStatus.PENDING,
) -> ReviewEntry:
    c = candidate or _candidate()
    return ReviewEntry(candidate=c, status=status)


# ---------------------------------------------------------------------------
# AC 1: Unreviewed memory cannot authorize writeback or governed apply flows
# ---------------------------------------------------------------------------


def test_unreviewed_memory_cannot_authorize_writeback() -> None:
    # ReviewEntry (PENDING/unreviewed) → blocked
    entry = _review_entry()
    with pytest.raises(AuthorityGuardError):
        assert_writeback_authorized(entry)

    # PromotedMemory with REJECTED outcome → blocked
    rejected_candidate = _candidate(review_state=ReviewState.REJECTED)
    rejected = _promoted_memory(candidate=rejected_candidate, outcome=ReviewState.REJECTED)
    with pytest.raises(AuthorityGuardError):
        assert_writeback_authorized(rejected)

    # PromotedMemory with REVISED outcome → blocked (authority moves to revised successor)
    revised_candidate = _candidate(review_state=ReviewState.REVISED)
    revised = _promoted_memory(candidate=revised_candidate, outcome=ReviewState.REVISED)
    with pytest.raises(AuthorityGuardError):
        assert_writeback_authorized(revised)

    # REVIEW_QUEUE_ONLY activation policy → blocked even if review_state is something else
    blocked_policy_candidate = _candidate(
        review_state=ReviewState.UNREVIEWED,
        activation_policy=ActivationPolicy.BLOCKED,
    )
    blocked_entry = _review_entry(candidate=blocked_policy_candidate)
    with pytest.raises(AuthorityGuardError):
        assert_writeback_authorized(blocked_entry)

    # PromotedMemory with ACCEPTED outcome + accepted candidate → passes
    accepted_candidate = _candidate(
        review_state=ReviewState.ACCEPTED,
        inferred=False,
        activation_policy=ActivationPolicy.EXPLICIT_OR_CONTEXTUAL,
    )
    promoted = _promoted_memory(candidate=accepted_candidate, outcome=ReviewState.ACCEPTED)
    assert_writeback_authorized(promoted)  # must not raise


# ---------------------------------------------------------------------------
# AC 2: Memory cannot override human-authored truth regardless of acceptance state
# ---------------------------------------------------------------------------


def test_memory_cannot_override_human_authored_truth() -> None:
    # Even a fully accepted, promoted memory cannot override human-authored artifacts
    accepted_candidate = _candidate(
        review_state=ReviewState.ACCEPTED,
        inferred=False,
        activation_policy=ActivationPolicy.EXPLICIT_OR_CONTEXTUAL,
    )
    promoted = _promoted_memory(candidate=accepted_candidate, outcome=ReviewState.ACCEPTED)

    for human_class in ("human_knowledge", "human_authored", "human_note"):
        with pytest.raises(AuthorityGuardError):
            assert_does_not_override_human_truth(
                promoted, target_artifact_class=human_class
            )

    # Non-human-authored target artifact classes are not blocked
    assert_does_not_override_human_truth(
        promoted, target_artifact_class="agentic_memory"
    )  # must not raise

    assert_does_not_override_human_truth(
        promoted, target_artifact_class="project_context"
    )  # must not raise

    # Even unreviewed memory is blocked from overriding human truth
    entry = _review_entry()
    with pytest.raises(AuthorityGuardError):
        assert_does_not_override_human_truth(entry, target_artifact_class="human_knowledge")

    with pytest.raises(AuthorityGuardError):
        assert_does_not_override_human_truth(entry, target_artifact_class="human_authored")


# ---------------------------------------------------------------------------
# AC 3: Stale, contradicted, or inferred memory must surface posture before reuse
# ---------------------------------------------------------------------------


def test_memory_authority_guard_requires_posture_visibility() -> None:
    # Contradicted candidate → posture must be surfaced before reuse
    contradicted_candidate = _candidate(
        contradiction_state=ContradictionState.CONTRADICTED,
        contradiction_notes="Later sessions contradict this.",
    )
    entry = _review_entry(candidate=contradicted_candidate)
    with pytest.raises(AuthorityGuardError):
        assert_posture_visible(entry)

    # REVISED contradiction_state → same rule
    revised_candidate = _candidate(
        contradiction_state=ContradictionState.REVISED,
        contradiction_notes="This was superseded by a correction.",
    )
    with pytest.raises(AuthorityGuardError):
        assert_posture_visible(_review_entry(candidate=revised_candidate))

    # Inferred + unreviewed → must surface posture
    inferred_unreviewed = _candidate(inferred=True, review_state=ReviewState.UNREVIEWED)
    with pytest.raises(AuthorityGuardError):
        assert_posture_visible(_review_entry(candidate=inferred_unreviewed))

    # Inferred but accepted (review makes posture visible) → passes
    accepted_inferred = _candidate(
        inferred=True,
        review_state=ReviewState.ACCEPTED,
        activation_policy=ActivationPolicy.EXPLICIT_OR_CONTEXTUAL,
    )
    promoted = _promoted_memory(candidate=accepted_inferred, outcome=ReviewState.ACCEPTED)
    assert_posture_visible(promoted)  # must not raise

    # Non-inferred, non-contradicted, clear state → passes
    clear_candidate = _candidate(
        inferred=False,
        review_state=ReviewState.ACCEPTED,
        contradiction_state=ContradictionState.CLEAR,
        activation_policy=ActivationPolicy.EXPLICIT_OR_CONTEXTUAL,
    )
    clear_promoted = _promoted_memory(candidate=clear_candidate, outcome=ReviewState.ACCEPTED)
    assert_posture_visible(clear_promoted)  # must not raise


# ---------------------------------------------------------------------------
# AC 4: Implementation distinguishes memory-supported suggestion from
#        memory-authorized mutation
# ---------------------------------------------------------------------------


def test_memory_supports_suggestion_without_escalating_to_mutation_authority() -> None:
    unreviewed = _candidate(review_state=ReviewState.UNREVIEWED)
    entry = _review_entry(candidate=unreviewed)

    # Suggestion path (SUGGESTIVE) is allowed for unreviewed memory
    assert_suggestion_only(entry, proposed_use_right=UseRight.SUGGESTIVE)  # must not raise

    # Escalation to stronger use rights is blocked
    with pytest.raises(AuthorityGuardError):
        assert_suggestion_only(entry, proposed_use_right=UseRight.INFORMATIONAL)

    with pytest.raises(AuthorityGuardError):
        assert_suggestion_only(entry, proposed_use_right=UseRight.INSTRUCTIONAL)

    with pytest.raises(AuthorityGuardError):
        assert_suggestion_only(entry, proposed_use_right=UseRight.ACTION_AUTHORIZING)

    # Accepted memory can use INSTRUCTIONAL without tripping the suggestion-only guard
    accepted_candidate = _candidate(
        review_state=ReviewState.ACCEPTED,
        inferred=False,
        activation_policy=ActivationPolicy.EXPLICIT_OR_CONTEXTUAL,
    )
    promoted = _promoted_memory(candidate=accepted_candidate, outcome=ReviewState.ACCEPTED)
    assert_suggestion_only(promoted, proposed_use_right=UseRight.INSTRUCTIONAL)  # must not raise
    assert_suggestion_only(promoted, proposed_use_right=UseRight.SUGGESTIVE)  # also fine

    # REVIEWED (not yet accepted) state → only SUGGESTIVE allowed
    reviewed_candidate = _candidate(
        review_state=ReviewState.REVIEWED,
        activation_policy=ActivationPolicy.EXPLICIT_OR_CONTEXTUAL,
    )
    reviewed_entry = _review_entry(candidate=reviewed_candidate)
    assert_suggestion_only(reviewed_entry, proposed_use_right=UseRight.SUGGESTIVE)
    with pytest.raises(AuthorityGuardError):
        assert_suggestion_only(reviewed_entry, proposed_use_right=UseRight.INSTRUCTIONAL)
