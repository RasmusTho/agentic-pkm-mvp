from __future__ import annotations

import pytest

from app.agent_memory.candidate import (
    ActivationPolicy,
    ContradictionState,
    MemoryCandidate,
    MemoryType,
    ReviewState,
)


def test_memory_candidate_preserves_source_and_review_state():
    candidate = MemoryCandidate(
        title="User prefers concise responses",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        source_refs=["chat_session:2026-05-19T09:00:00Z"],
        derived_from="conversation:abc123",
        generated_by="companion_agent",
    )
    assert candidate.source_refs == ["chat_session:2026-05-19T09:00:00Z"]
    assert candidate.derived_from == "conversation:abc123"
    assert candidate.generated_by == "companion_agent"
    assert candidate.review_state == ReviewState.UNREVIEWED
    assert candidate.artifact_class == "agentic_memory"


def test_memory_candidate_marks_inferred_vs_reviewed():
    inferred = MemoryCandidate(
        title="Agent inferred preference from session pattern",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        source_refs=["session:xyz"],
    )
    assert inferred.inferred is True
    assert inferred.review_state == ReviewState.UNREVIEWED

    reviewed = MemoryCandidate(
        title="User explicitly stated preference",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        source_refs=["note:explicit-preference.md"],
        inferred=False,
        review_state=ReviewState.ACCEPTED,
    )
    assert reviewed.inferred is False
    assert reviewed.review_state == ReviewState.ACCEPTED


def test_memory_candidate_separates_candidate_class_from_promoted_class():
    candidate = MemoryCandidate(
        title="Proposed semantic knowledge about user domain",
        memory_type=MemoryType.SEMANTIC_MEMORY,
        source_refs=["session:2026-05-19"],
    )
    assert candidate.memory_type == MemoryType.SEMANTIC_MEMORY
    assert candidate.review_state == ReviewState.UNREVIEWED
    assert candidate.inferred is True
    assert candidate.artifact_class == "agentic_memory"


def test_memory_candidate_supports_contradiction_and_revision_state():
    original_id = "cand_abc123"

    revision = MemoryCandidate(
        title="Revised: user prefers detailed responses",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        source_refs=["session:2026-05-19T10:00:00Z"],
        contradiction_state=ContradictionState.CONTRADICTED,
        correction_of=original_id,
        contradiction_notes="Single-session bias; later sessions show preference for detail.",
    )
    assert revision.contradiction_state == ContradictionState.CONTRADICTED
    assert revision.correction_of == original_id
    assert revision.contradiction_notes is not None

    rejected = MemoryCandidate(
        title="Incorrect observation",
        memory_type=MemoryType.SEMANTIC_MEMORY,
        source_refs=["session:abc"],
        contradiction_state=ContradictionState.REJECTED,
        contradiction_notes="Human review determined this observation was incorrect.",
        review_state=ReviewState.REJECTED,
    )
    assert rejected.contradiction_state == ContradictionState.REJECTED
    assert rejected.review_state == ReviewState.REJECTED


def test_unreviewed_candidate_rejects_activatable_policy() -> None:
    """Unreviewed candidates must not bypass the review queue via activation_policy.

    §4.3.1: unreviewed artifacts must stay in review_queue_only or blocked.
    """
    with pytest.raises(ValueError, match="unreviewed candidates must use activation_policy"):
        MemoryCandidate(
            title="Candidate that tries to bypass review",
            memory_type=MemoryType.PREFERENCE_MEMORY,
            source_refs=["session:abc"],
            review_state=ReviewState.UNREVIEWED,
            activation_policy=ActivationPolicy.EXPLICIT_OR_CONTEXTUAL,
        )


def test_unreviewed_candidate_allows_review_queue_only_and_blocked() -> None:
    """REVIEW_QUEUE_ONLY and BLOCKED are both valid for unreviewed candidates."""
    c1 = MemoryCandidate(
        title="Queue candidate",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        source_refs=["session:abc"],
        review_state=ReviewState.UNREVIEWED,
        activation_policy=ActivationPolicy.REVIEW_QUEUE_ONLY,
    )
    assert c1.activation_policy is ActivationPolicy.REVIEW_QUEUE_ONLY

    c2 = MemoryCandidate(
        title="Blocked candidate",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        source_refs=["session:abc"],
        review_state=ReviewState.UNREVIEWED,
        activation_policy=ActivationPolicy.BLOCKED,
    )
    assert c2.activation_policy is ActivationPolicy.BLOCKED
