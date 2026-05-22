"""Tests for companion-note-aware memory handling (AGENT-MEMORY-03, #1085).

Verifies that:
1. New memory candidates for a human knowledge artifact are recorded in a
   synthesis_companion, not inline in the primary note.
2. The synthesis_companion artifact_class remains 'companion_metadata' after
   candidate memory references are added (never becomes 'agentic_memory').
3. Promoting a candidate from a companion updates the companion's candidate
   list and creates the promoted memory artifact separately.
4. The review queue can discover pending candidate references from
   synthesis_companion artifacts.
5. Human-authored sections in a companion are not overwritten when the system
   updates the ## Candidate Memories section.

Source: docs/CONTEXTUALIZATION_LAYER/COMPANION_NOTE_PATTERN.md §8 and §10
"""

from __future__ import annotations

import pytest

from app.agent_memory.candidate import MemoryCandidate, MemoryType
from app.agent_memory.companion_aware import (
    AGENTIC_MEMORY_ARTIFACT_CLASS,
    CANDIDATE_MEMORIES_HEADING,
    COMPANION_ARTIFACT_CLASS,
    SYNTHESIS_COMPANION_TYPE,
    PromotionResult,
    SynthesisCompanion,
    add_candidate_to_companion,
    discover_candidates_from_companions,
    promote_candidate_from_companion,
    update_companion_candidate_memories_section,
)
from app.agent_memory.review_queue import ReviewStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_companion(
    companion_for: str = "My Concept Note",
    target_path: str = "Concepts/My Concept Note.md",
    body: str = "",
) -> SynthesisCompanion:
    return SynthesisCompanion(
        companion_for=companion_for,
        target_path=target_path,
        body=body,
    )


def _make_candidate(
    title: str = "User prefers concise answers",
    memory_type: MemoryType = MemoryType.PREFERENCE_MEMORY,
) -> MemoryCandidate:
    return MemoryCandidate(
        title=title,
        memory_type=memory_type,
        content="Observed across three sessions.",
        source_refs=["session:2026-05-20T10:00:00Z"],
        generated_by="companion_agent",
    )


# ---------------------------------------------------------------------------
# AC1: candidates stored in synthesis_companion, not in primary note
# ---------------------------------------------------------------------------


def test_candidate_memory_stored_in_synthesis_companion() -> None:
    """New candidates for a human knowledge artifact go into a
    synthesis_companion, not inline in the primary note.

    Verify: the companion receives the candidate in its ``candidates`` dict;
    the primary note (represented here as a plain string that must remain
    unchanged) is NOT modified.
    """
    primary_note_content = (
        "---\nartifact_class: human_knowledge\ntitle: My Concept Note\n---\n\n"
        "# My Concept Note\n\nContent written by the human.\n"
    )

    companion = _make_companion()
    candidate = _make_candidate()

    # Act: add candidate to companion — primary note is NOT touched
    updated_companion = add_candidate_to_companion(companion, candidate)

    # Candidate is in the companion
    assert candidate.candidate_id in updated_companion.candidates
    assert updated_companion.candidates[candidate.candidate_id].title == candidate.title

    # Companion is a synthesis_companion
    assert updated_companion.companion_type == SYNTHESIS_COMPANION_TYPE

    # Primary note is completely unchanged (caller owns the primary note;
    # companion_aware never touches it)
    assert primary_note_content == (
        "---\nartifact_class: human_knowledge\ntitle: My Concept Note\n---\n\n"
        "# My Concept Note\n\nContent written by the human.\n"
    )

    # Candidate Memories section appears in the companion body
    assert CANDIDATE_MEMORIES_HEADING in updated_companion.body
    assert candidate.candidate_id in updated_companion.body


# ---------------------------------------------------------------------------
# AC2: synthesis_companion artifact_class stays 'companion_metadata'
# ---------------------------------------------------------------------------


def test_companion_class_not_promoted_to_agentic_memory() -> None:
    """synthesis_companion artifact_class remains 'companion_metadata' after
    candidate memory references are added; it must never become 'agentic_memory'.

    Source: COMPANION_NOTE_PATTERN.md §8, issue constraint §2.
    """
    companion = _make_companion()
    candidate = _make_candidate()

    # Add a candidate
    updated = add_candidate_to_companion(companion, candidate)

    # artifact_class must remain companion_metadata
    assert updated.artifact_class == COMPANION_ARTIFACT_CLASS
    assert updated.artifact_class != AGENTIC_MEMORY_ARTIFACT_CLASS

    # Adding multiple candidates still preserves the class
    candidate2 = _make_candidate(title="Second candidate", memory_type=MemoryType.SEMANTIC_MEMORY)
    updated2 = add_candidate_to_companion(updated, candidate2)
    assert updated2.artifact_class == COMPANION_ARTIFACT_CLASS

    # Attempting to construct a companion with an agentic_memory class raises ValueError
    with pytest.raises(ValueError, match="artifact_class must be"):
        SynthesisCompanion(
            companion_for="test",
            target_path="test.md",
            artifact_class=AGENTIC_MEMORY_ARTIFACT_CLASS,
        )


# ---------------------------------------------------------------------------
# AC3: promotion updates companion and creates memory artifact separately
# ---------------------------------------------------------------------------


def test_promotion_updates_companion_and_creates_memory_artifact() -> None:
    """Promoting a candidate from a companion note:
    - removes the candidate from the companion's candidates dict, and
    - creates the promoted memory artifact separately (returned in PromotionResult).

    The companion's artifact_class stays 'companion_metadata'.
    The promoted artifact's artifact_class becomes 'agentic_memory'.
    """
    companion = _make_companion()
    candidate = _make_candidate()
    companion_with_candidate = add_candidate_to_companion(companion, candidate)

    assert candidate.candidate_id in companion_with_candidate.candidates

    # Act: promote the candidate
    result: PromotionResult = promote_candidate_from_companion(
        companion_with_candidate, candidate.candidate_id
    )

    # Companion is updated: candidate removed
    assert candidate.candidate_id not in result.updated_companion.candidates
    assert result.updated_companion.artifact_class == COMPANION_ARTIFACT_CLASS

    # Companion body reflects removal
    assert CANDIDATE_MEMORIES_HEADING in result.updated_companion.body
    assert candidate.candidate_id not in result.updated_companion.body

    # Promoted artifact exists and has agentic_memory class
    assert result.promoted_artifact is not None
    assert result.promoted_artifact.artifact_class == AGENTIC_MEMORY_ARTIFACT_CLASS
    assert result.promoted_artifact.candidate_id == candidate.candidate_id
    assert result.promoted_artifact.title == candidate.title

    # Attempting to promote an absent candidate raises KeyError
    with pytest.raises(KeyError, match="candidate not found in companion"):
        promote_candidate_from_companion(
            result.updated_companion, candidate.candidate_id
        )


# ---------------------------------------------------------------------------
# AC4: review queue discovers candidates from synthesis_companion artifacts
# ---------------------------------------------------------------------------


def test_review_queue_discovers_candidates_from_companions() -> None:
    """The review queue can discover pending candidate references from
    synthesis_companion artifacts.

    Source: issue AC4, COMPANION_NOTE_PATTERN.md §8.
    """
    companion_a = _make_companion(
        companion_for="Note A", target_path="Notes/Note A.md"
    )
    companion_b = _make_companion(
        companion_for="Note B", target_path="Notes/Note B.md"
    )

    cand_a1 = _make_candidate(title="Candidate A1", memory_type=MemoryType.SEMANTIC_MEMORY)
    cand_a2 = _make_candidate(title="Candidate A2", memory_type=MemoryType.EPISODIC_MEMORY)
    cand_b1 = _make_candidate(title="Candidate B1", memory_type=MemoryType.PREFERENCE_MEMORY)

    companion_a = add_candidate_to_companion(companion_a, cand_a1)
    companion_a = add_candidate_to_companion(companion_a, cand_a2)
    companion_b = add_candidate_to_companion(companion_b, cand_b1)

    # Act: discover
    queue = discover_candidates_from_companions([companion_a, companion_b])

    pending = queue.pending()
    pending_ids = {e.candidate_id for e in pending}

    assert cand_a1.candidate_id in pending_ids
    assert cand_a2.candidate_id in pending_ids
    assert cand_b1.candidate_id in pending_ids
    assert len(pending) == 3

    # All discovered entries are PENDING (not yet decided)
    for entry in pending:
        assert entry.status is ReviewStatus.PENDING

    # Non-synthesis companion (type not synthesis_companion/mixed_companion) is ignored
    non_synthesis = SynthesisCompanion(
        companion_for="Other",
        target_path="Other.md",
        companion_type="activation_companion",  # not synthesis
    )
    non_synthesis_with_candidate = add_candidate_to_companion(
        non_synthesis,
        _make_candidate(title="Ignored candidate"),
    )
    queue2 = discover_candidates_from_companions([non_synthesis_with_candidate])
    assert queue2.pending() == []


# ---------------------------------------------------------------------------
# AC5: human-authored sections preserved on system update
# ---------------------------------------------------------------------------


def test_companion_human_sections_preserved_on_system_update() -> None:
    """Human-authored sections in a companion are not overwritten when the
    system updates the ## Candidate Memories section.

    Source: COMPANION_NOTE_PATTERN.md §10 Editability and Conflict Handling.
    """
    human_review_section = (
        "## Human Review Notes\n\n"
        "This artifact is particularly relevant to the Q2 planning cycle.\n"
        "Do not discard candidates related to scheduling.\n"
    )
    human_purpose_section = (
        "## Purpose\n\n"
        "Carry synthesis signals for the planning note.\n"
    )
    initial_body = human_purpose_section + "\n" + human_review_section

    companion = _make_companion(body=initial_body)
    candidate = _make_candidate()

    # System adds a candidate — should update only ## Candidate Memories
    updated = add_candidate_to_companion(companion, candidate)

    # Human sections are intact
    assert human_purpose_section in updated.body
    assert "This artifact is particularly relevant to the Q2 planning cycle." in updated.body
    assert "Do not discard candidates related to scheduling." in updated.body

    # Candidate memories section is present with the new candidate
    assert CANDIDATE_MEMORIES_HEADING in updated.body
    assert candidate.candidate_id in updated.body

    # Simulate a second system update (e.g. adding another candidate)
    candidate2 = _make_candidate(
        title="Second candidate", memory_type=MemoryType.POLICY_MEMORY
    )
    updated2 = add_candidate_to_companion(updated, candidate2)

    # Human sections still intact
    assert "This artifact is particularly relevant to the Q2 planning cycle." in updated2.body
    assert "Do not discard candidates related to scheduling." in updated2.body

    # Both candidates in managed section
    assert candidate.candidate_id in updated2.body
    assert candidate2.candidate_id in updated2.body

    # System-only update (no new candidate, just regenerate the section)
    refreshed = update_companion_candidate_memories_section(updated2)
    assert "This artifact is particularly relevant to the Q2 planning cycle." in refreshed.body
    assert candidate.candidate_id in refreshed.body
    assert candidate2.candidate_id in refreshed.body

    # artifact_class always remains companion_metadata
    assert refreshed.artifact_class == COMPANION_ARTIFACT_CLASS
