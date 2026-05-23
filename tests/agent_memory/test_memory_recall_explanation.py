"""Tests for recall explanation surfaces (AGENT-MEMORY-04).

Verifies the four Acceptance Criteria from Issue #1082:

1. test_recall_explanation_includes_source_and_review_state
2. test_recall_explanation_includes_why_now
3. test_recall_explanation_preserves_memory_lifecycle_state
4. test_recall_explanation_preserves_authority_limits
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.agent_memory.candidate import (
    ActivationPolicy,
    ContradictionState,
    MemoryCandidate,
    MemoryType,
    ReviewState,
)
from app.agent_memory.promotion import PromotedMemory
from app.agent_memory.recall_explanation import (
    LifecycleState,
    RecallExplanation,
    RecallExplanationError,
    UseRight,
    build_recall_explanation,
)
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


# ---------------------------------------------------------------------------
# AC 1: Recalled memory includes source provenance and review posture
# ---------------------------------------------------------------------------


def test_recall_explanation_includes_source_and_review_state() -> None:
    candidate = _candidate(
        source_refs=["session:2026-05-21T09:00:00Z", "note:pref.md"],
        review_state=ReviewState.ACCEPTED,
        inferred=False,
    )
    mem = _promoted_memory(candidate=candidate, outcome=ReviewState.ACCEPTED)

    explanation = build_recall_explanation(mem, activation_reason="answering terse-reply question")

    assert explanation.source_refs == ["session:2026-05-21T09:00:00Z", "note:pref.md"]
    assert explanation.review_state is ReviewState.ACCEPTED
    assert explanation.artifact_id == mem.promotion_id
    assert explanation.artifact_title == candidate.title
    assert isinstance(explanation, RecallExplanation)


# ---------------------------------------------------------------------------
# AC 2: Recall explanation includes a "why now" rationale, not only memory text
# ---------------------------------------------------------------------------


def test_recall_explanation_includes_why_now() -> None:
    candidate = _candidate(
        review_state=ReviewState.ACCEPTED,
        inferred=False,
        title="User prefers concise answers",
    )
    mem = _promoted_memory(candidate=candidate)

    activation_reason = "User asked for a summary in the same style as session:2026-05-21"
    explanation = build_recall_explanation(mem, activation_reason=activation_reason)

    assert explanation.activation_reason == activation_reason
    # Must not be just a replay of stored title/content
    assert explanation.activation_reason != explanation.artifact_title
    # compact_trace must embed the why-now rationale
    trace = explanation.compact_trace()
    assert activation_reason in trace or "summary" in trace


# ---------------------------------------------------------------------------
# AC 3: Recall explanation preserves the memory's lifecycle state at activation
# ---------------------------------------------------------------------------


def test_recall_explanation_preserves_memory_lifecycle_state() -> None:
    # PROMOTED path
    accepted_candidate = _candidate(review_state=ReviewState.ACCEPTED, inferred=False)
    promoted = _promoted_memory(candidate=accepted_candidate, outcome=ReviewState.ACCEPTED)
    exp_promoted = build_recall_explanation(promoted, activation_reason="test")
    assert exp_promoted.lifecycle_state is LifecycleState.PROMOTED

    # REVISED path
    revised_candidate = _candidate(review_state=ReviewState.ACCEPTED, inferred=False)
    revised_mem = _promoted_memory(
        candidate=revised_candidate,
        outcome=ReviewState.REVISED,
        revision_of="prior_candidate_id_abc",
    )
    exp_revised = build_recall_explanation(revised_mem, activation_reason="test")
    assert exp_revised.lifecycle_state is LifecycleState.REVISED

    # HISTORICALLY_REJECTED path
    rejected_candidate = _candidate(review_state=ReviewState.REJECTED)
    rejected_mem = _promoted_memory(
        candidate=rejected_candidate,
        outcome=ReviewState.REJECTED,
    )
    exp_rejected = build_recall_explanation(rejected_mem, activation_reason="test")
    assert exp_rejected.lifecycle_state is LifecycleState.HISTORICALLY_REJECTED

    # ReviewEntry (queue) path → INFERRED
    candidate = _candidate()
    entry = ReviewEntry(candidate=candidate, status=ReviewStatus.PENDING)
    exp_inferred = build_recall_explanation(entry, activation_reason="test")
    assert exp_inferred.lifecycle_state is LifecycleState.INFERRED

    # full_audit must carry lifecycle_state without information loss
    audit = exp_promoted.full_audit()
    assert audit["lifecycle_state"] == LifecycleState.PROMOTED
    assert audit["artifact_id"] == promoted.promotion_id
    assert audit["source_refs"] == accepted_candidate.source_refs


# ---------------------------------------------------------------------------
# AC 4: Recall explanation preserves authority limits
# ---------------------------------------------------------------------------


def test_recall_explanation_preserves_authority_limits() -> None:
    # Unreviewed candidate (ReviewEntry) → SUGGESTIVE, restrictive limits
    unreviewed_candidate = _candidate(review_state=ReviewState.UNREVIEWED)
    entry = ReviewEntry(candidate=unreviewed_candidate, status=ReviewStatus.PENDING)
    exp = build_recall_explanation(entry, activation_reason="test")
    assert exp.use_right is UseRight.SUGGESTIVE
    assert exp.authority_limits  # non-empty
    assert "cannot authorize" in exp.authority_limits

    # Accepted candidate → INSTRUCTIONAL (still has limits, just weaker)
    accepted_candidate = _candidate(review_state=ReviewState.ACCEPTED, inferred=False)
    promoted = _promoted_memory(candidate=accepted_candidate, outcome=ReviewState.ACCEPTED)
    exp_inst = build_recall_explanation(promoted, activation_reason="test")
    assert exp_inst.use_right is UseRight.INSTRUCTIONAL
    assert exp_inst.authority_limits  # still non-empty
    assert "cannot authorize" in exp_inst.authority_limits

    # ACTION_AUTHORIZING requires all three kwargs — missing any raises
    with pytest.raises(RecallExplanationError, match="missing"):
        build_recall_explanation(
            promoted,
            activation_reason="test",
            action_scope="update-preferences",
            # authority_source and receipt_ref missing
        )

    with pytest.raises(RecallExplanationError):
        build_recall_explanation(
            promoted,
            activation_reason="test",
            authority_source="review:rasmus",
            receipt_ref="promotion:abc",
            # action_scope missing
        )

    # Unreviewed + action kwargs → raises (cannot escalate)
    with pytest.raises(RecallExplanationError):
        build_recall_explanation(
            entry,
            activation_reason="test",
            action_scope="update-prefs",
            authority_source="review:rasmus",
            receipt_ref="receipt:xyz",
        )

    # Full action-authorizing on accepted candidate works
    exp_auth = build_recall_explanation(
        promoted,
        activation_reason="test",
        action_scope="update-preferences",
        authority_source="review:rasmus",
        receipt_ref="promotion:" + promoted.promotion_id,
    )
    assert exp_auth.use_right is UseRight.ACTION_AUTHORIZING
    assert exp_auth.action_scope == "update-preferences"
    assert exp_auth.authority_source == "review:rasmus"
    assert exp_auth.authority_limits  # still bounded
    assert "outside that scope" in exp_auth.authority_limits
