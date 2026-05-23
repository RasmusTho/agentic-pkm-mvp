"""Tests for memory authority guard boundaries (AGENT-MEMORY-05, #1083)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.agent_memory.authority_guard import MemoryAuthorityLevel, evaluate_memory_authority
from app.agent_memory.candidate import (
    ContradictionState,
    MemoryCandidate,
    MemoryType,
    ReviewState,
)
from app.agent_memory.promotion import PromotedMemory
from app.agent_memory.recall_explanation import RecallUseRight


def _candidate(
    *,
    review_state: ReviewState,
    inferred: bool,
    memory_type: MemoryType = MemoryType.PREFERENCE_MEMORY,
    contradiction_state: ContradictionState = ContradictionState.CLEAR,
) -> MemoryCandidate:
    return MemoryCandidate(
        title="Authority candidate",
        memory_type=memory_type,
        review_state=review_state,
        inferred=inferred,
        contradiction_state=contradiction_state,
        source_refs=["vault://notes/policy.md"],
    )


def _promoted(
    *,
    review_state: ReviewState,
    inferred: bool,
    memory_type: MemoryType = MemoryType.PREFERENCE_MEMORY,
    contradiction_state: ContradictionState = ContradictionState.CLEAR,
    outcome: ReviewState = ReviewState.ACCEPTED,
) -> PromotedMemory:
    return PromotedMemory(
        outcome=outcome,
        candidate=_candidate(
            review_state=review_state,
            inferred=inferred,
            memory_type=memory_type,
            contradiction_state=contradiction_state,
        ),
        decided_by="human://reviewer",
        decided_at=datetime.now(timezone.utc),
    )


def test_unreviewed_memory_cannot_authorize_writeback() -> None:
    promoted = _promoted(review_state=ReviewState.UNREVIEWED, inferred=True)

    decision = evaluate_memory_authority(
        promoted,
        use_right=RecallUseRight.ACTION_AUTHORIZING,
        requested_action_scope="active_note_body_update",
    )

    assert decision.authority_level is MemoryAuthorityLevel.SUGGESTION_ONLY
    assert decision.allow_mutation is False
    assert "review_state_not_accepted" in decision.blocked_reasons


def test_memory_cannot_override_human_authored_truth() -> None:
    promoted = _promoted(review_state=ReviewState.ACCEPTED, inferred=False)

    decision = evaluate_memory_authority(
        promoted,
        use_right=RecallUseRight.ACTION_AUTHORIZING,
        requested_action_scope="active_note_body_update",
        conflicts_with_human_truth=True,
    )

    assert decision.allow_mutation is False
    assert "human_authored_truth_precedence" in decision.blocked_reasons


def test_memory_authority_guard_requires_posture_visibility() -> None:
    promoted = _promoted(
        review_state=ReviewState.REVIEWED,
        inferred=True,
        contradiction_state=ContradictionState.CONTRADICTED,
    )

    decision = evaluate_memory_authority(
        promoted,
        use_right=RecallUseRight.ACTIVATABLE,
    )

    assert decision.posture_visibility_required is True
    assert "inferred" in decision.posture_markers
    assert "contradicted" in decision.posture_markers


def test_memory_supports_suggestion_without_escalating_to_mutation_authority() -> None:
    promoted = _promoted(review_state=ReviewState.REVIEWED, inferred=True)

    decision = evaluate_memory_authority(
        promoted,
        use_right=RecallUseRight.INSTRUCTIONAL,
    )

    assert decision.allow_suggestion is True
    assert decision.allow_mutation is False
    assert decision.authority_level is MemoryAuthorityLevel.SUGGESTION_ONLY
