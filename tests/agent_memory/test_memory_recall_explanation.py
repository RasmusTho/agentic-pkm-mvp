"""Tests for explainable memory recall surfaces (AGENT-MEMORY-04, #1082)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.agent_memory.candidate import MemoryCandidate, MemoryType, ReviewState
from app.agent_memory.promotion import PromotedMemory
from app.agent_memory.recall_explanation import (
    ActivationReason,
    MemoryLifecycleState,
    RecallUseRight,
    build_recall_explanation,
)


def _make_candidate(*, review_state: ReviewState = ReviewState.ACCEPTED, inferred: bool = False) -> MemoryCandidate:
    return MemoryCandidate(
        title="Design preference memory",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        review_state=review_state,
        inferred=inferred,
        source_refs=["vault://notes/preferences.md"],
        derived_from="receipt://review-001",
        generated_by="agent://planner",
        content="Prefer compact status updates",
    )


def _make_promoted_memory(
    *,
    outcome: ReviewState = ReviewState.ACCEPTED,
    review_state: ReviewState = ReviewState.ACCEPTED,
    inferred: bool = False,
) -> PromotedMemory:
    candidate = _make_candidate(review_state=review_state, inferred=inferred)
    return PromotedMemory(
        outcome=outcome,
        candidate=candidate,
        decided_by="human://reviewer",
        decided_at=datetime.now(timezone.utc),
        decision_notes="reviewed and accepted",
    )


def test_recall_explanation_includes_source_and_review_state() -> None:
    promoted = _make_promoted_memory()

    explanation = build_recall_explanation(
        promoted,
        use_right=RecallUseRight.ACTIVATABLE,
        activation_reason=ActivationReason.EXPLICIT_REFERENCE,
        why_now="The user explicitly asked to recall delivery preferences.",
        bundle_reference="cb_20260523_001",
    )

    assert explanation.source_provenance.source_refs == ["vault://notes/preferences.md"]
    assert explanation.source_provenance.derived_from == "receipt://review-001"
    assert explanation.source_provenance.generated_by == "agent://planner"
    assert explanation.review_state is ReviewState.ACCEPTED


def test_recall_explanation_includes_why_now() -> None:
    promoted = _make_promoted_memory()

    explanation = build_recall_explanation(
        promoted,
        use_right=RecallUseRight.ACTIVATABLE,
        activation_reason=ActivationReason.CONTEXTUAL_RELEVANCE,
        why_now="Current task asks for short release notes and this memory captures that preference.",
        bundle_reference="cb_20260523_002",
    )

    assert (
        explanation.why_now
        == "Current task asks for short release notes and this memory captures that preference."
    )


def test_recall_explanation_preserves_memory_lifecycle_state() -> None:
    revised = _make_promoted_memory(outcome=ReviewState.REVISED, review_state=ReviewState.REVISED)

    explanation = build_recall_explanation(
        revised,
        use_right=RecallUseRight.ACTIVATABLE,
        activation_reason=ActivationReason.RESUME_CONTINUITY,
        why_now="Resuming a task that references a revised memory record.",
        bundle_reference="cb_20260523_003",
    )

    assert explanation.lifecycle_state is MemoryLifecycleState.REVISED


def test_recall_explanation_preserves_authority_limits() -> None:
    inferred_reviewed = _make_promoted_memory(
        outcome=ReviewState.ACCEPTED,
        review_state=ReviewState.REVIEWED,
        inferred=True,
    )

    explanation = build_recall_explanation(
        inferred_reviewed,
        use_right=RecallUseRight.ACTIVATABLE,
        activation_reason=ActivationReason.POLICY_APPLICABILITY,
        why_now="The memory is relevant context but still not accepted as behavioral authority.",
        bundle_reference="cb_20260523_004",
    )

    assert "memory_is_supporting_input_not_source_of_truth" in explanation.authority_limits
    assert "does_not_authorize_writeback" in explanation.authority_limits
    assert "requires_accepted_review_state_for_instructional_use" in explanation.authority_limits
    assert "inferred_memory_requires_review_visibility" in explanation.authority_limits


def test_instructional_recall_accepts_promoted_accepted_memory() -> None:
    promoted = _make_promoted_memory(outcome=ReviewState.ACCEPTED, review_state=ReviewState.UNREVIEWED)
    explanation = build_recall_explanation(
        promoted,
        use_right=RecallUseRight.INSTRUCTIONAL,
        activation_reason=ActivationReason.AUTHORITY_SIGNAL,
        why_now="Accepted promotion should govern instructional authority posture.",
        behavioral_claim="Keep release notes compact and factual.",
    )
    assert explanation.review_state is ReviewState.ACCEPTED


def test_action_authorizing_recall_requires_behavioral_claim() -> None:
    promoted = _make_promoted_memory(outcome=ReviewState.ACCEPTED, review_state=ReviewState.ACCEPTED)
    with pytest.raises(ValueError, match="behavioral_claim"):
        build_recall_explanation(
            promoted,
            use_right=RecallUseRight.ACTION_AUTHORIZING,
            activation_reason=ActivationReason.AUTHORITY_SIGNAL,
            why_now="Attempting authority escalation without instructional rationale.",
            action_scope="active_note_body_update",
            authority_source="review_receipt",
            receipt_reference="receipt://authority-001",
        )
