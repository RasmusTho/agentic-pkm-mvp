"""Companion-note-aware memory handling (AGENT-MEMORY-03).

This module provides the surfaces required to integrate agent memory candidates
with the Companion Note Pattern defined in
``docs/CONTEXTUALIZATION_LAYER/COMPANION_NOTE_PATTERN.md``.

Key invariants enforced here:

- New memory candidates for a human knowledge artifact are recorded in a
  ``synthesis_companion`` (or ``mixed_companion``), NOT inline in the primary note.
- The companion's ``artifact_class`` remains ``companion_metadata`` even after
  candidate memory references are added; it must never become ``agentic_memory``.
- When a candidate is promoted, the companion's candidate list is updated to
  remove the pending reference AND a separate promoted memory artifact is
  returned by the caller.
- The review queue can discover pending candidates from ``synthesis_companion``
  artifacts by scanning them.
- Human-authored sections inside the companion (e.g. free-text review notes)
  are preserved when the system regenerates the ``## Candidate Memories``
  section.

This module deliberately ships no storage back-end, no watcher, no prompt
wiring, and no activation engine.  Those surfaces are owned by later slices.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.agent_memory.candidate import MemoryCandidate
from app.agent_memory.review_queue import (
    MemoryCandidateReviewQueue,
)

# ---------------------------------------------------------------------------
# Companion artifact class constant — must never be mutated to agentic_memory
# ---------------------------------------------------------------------------

COMPANION_ARTIFACT_CLASS = "companion_metadata"
AGENTIC_MEMORY_ARTIFACT_CLASS = "agentic_memory"

# Companion types relevant to memory (from COMPANION_NOTE_PATTERN.md §8)
SYNTHESIS_COMPANION_TYPE = "synthesis_companion"
MIXED_COMPANION_TYPE = "mixed_companion"

# Managed-section heading used in the companion body
CANDIDATE_MEMORIES_HEADING = "## Candidate Memories"

# Regex that matches the managed section block (heading + everything up to
# the next ## heading or end-of-string).  Non-greedy, DOTALL.
_MANAGED_SECTION_RE = re.compile(
    r"(## Candidate Memories\n)(.*?)(?=\n## |\Z)",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# In-memory synthesis companion model
# ---------------------------------------------------------------------------


@dataclass
class SynthesisCompanion:
    """In-memory representation of a synthesis companion for a human knowledge artifact.

    ``artifact_class`` is fixed to ``companion_metadata`` and must NOT be
    changed to ``agentic_memory`` even when candidate memory references are
    present.  Candidates are *references* that await promotion, not promoted
    memory artifacts.

    ``companion_type`` defaults to ``synthesis_companion``.  Set it to
    ``mixed_companion`` when the companion also carries other companion data
    (activation, processing, etc.).

    ``body`` holds the human-readable companion body text (everything after
    optional YAML frontmatter).  The ``## Candidate Memories`` section within
    ``body`` is the system-managed block.  All other sections are
    human-editable and must not be overwritten by system updates.
    """

    # Linkage (per COMPANION_NOTE_PATTERN.md §6)
    companion_for: str
    target_path: str
    target_artifact_class: str = "human_knowledge"

    # Identity / class fields — artifact_class must stay companion_metadata
    artifact_class: str = field(default=COMPANION_ARTIFACT_CLASS)
    companion_type: str = field(default=SYNTHESIS_COMPANION_TYPE)

    # Timestamps
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Optional attribution
    generated_by: Optional[str] = None

    # Candidate memory references stored in this companion.
    # Keys are candidate_id strings; values are MemoryCandidate objects.
    candidates: dict[str, MemoryCandidate] = field(default_factory=dict)

    # Human-readable body (may contain human-authored sections that must not
    # be overwritten).
    body: str = field(default="")

    def __post_init__(self) -> None:
        # Enforce the class invariant: the artifact_class must always be
        # companion_metadata.  Accept no other value.
        if self.artifact_class != COMPANION_ARTIFACT_CLASS:
            raise ValueError(
                f"SynthesisCompanion artifact_class must be "
                f"'{COMPANION_ARTIFACT_CLASS}', got '{self.artifact_class}'"
            )


# ---------------------------------------------------------------------------
# Companion-aware candidate storage
# ---------------------------------------------------------------------------


def add_candidate_to_companion(
    companion: SynthesisCompanion,
    candidate: MemoryCandidate,
) -> SynthesisCompanion:
    """Record a new memory candidate in the companion's candidate dict.

    Returns a new ``SynthesisCompanion`` instance (companions are treated as
    value objects here; the caller owns persistence).

    The companion's ``artifact_class`` is verified to remain
    ``companion_metadata`` after the operation.  The candidate is NOT stored
    inline in any primary human note.
    """
    if companion.artifact_class != COMPANION_ARTIFACT_CLASS:
        raise ValueError(
            "companion artifact_class must remain 'companion_metadata' — "
            f"got '{companion.artifact_class}'"
        )

    updated_candidates = {**companion.candidates, candidate.candidate_id: candidate}
    updated_body = _update_candidate_memories_section(companion.body, updated_candidates)

    import dataclasses

    return dataclasses.replace(
        companion,
        candidates=updated_candidates,
        body=updated_body,
        updated=datetime.now(timezone.utc).isoformat(),
        artifact_class=COMPANION_ARTIFACT_CLASS,  # explicit: never change
    )


# ---------------------------------------------------------------------------
# Promotion
# ---------------------------------------------------------------------------


@dataclass
class PromotionResult:
    """Result of promoting a candidate from a companion.

    ``updated_companion`` has the promoted candidate removed from its
    ``candidates`` dict (and from the ``## Candidate Memories`` section).

    ``promoted_artifact`` is the candidate as a promoted memory artifact.
    The caller is responsible for persisting it separately — promotion does
    NOT happen on the companion itself.
    """

    updated_companion: SynthesisCompanion
    promoted_artifact: MemoryCandidate


def promote_candidate_from_companion(
    companion: SynthesisCompanion,
    candidate_id: str,
) -> PromotionResult:
    """Promote a candidate from the companion and return both updated surfaces.

    Per the issue constraints:
    - The companion is updated to remove the pending candidate reference.
    - The promoted memory artifact is returned separately.
    - The companion's ``artifact_class`` stays ``companion_metadata``; it does
      not become ``agentic_memory``.

    Raises ``KeyError`` if ``candidate_id`` is not in the companion's
    candidate dict.
    """
    if candidate_id not in companion.candidates:
        raise KeyError(f"candidate not found in companion: {candidate_id}")

    candidate = companion.candidates[candidate_id]

    # Build the promoted memory artifact — keep candidate fields, mark as
    # a promoted (non-inferred) artifact.
    promoted = candidate.model_copy(
        update={
            "artifact_class": AGENTIC_MEMORY_ARTIFACT_CLASS,
            "inferred": False,
        }
    )

    # Remove candidate from companion dict
    updated_candidates = {
        cid: c for cid, c in companion.candidates.items() if cid != candidate_id
    }
    updated_body = _update_candidate_memories_section(companion.body, updated_candidates)

    import dataclasses

    updated_companion = dataclasses.replace(
        companion,
        candidates=updated_candidates,
        body=updated_body,
        updated=datetime.now(timezone.utc).isoformat(),
        artifact_class=COMPANION_ARTIFACT_CLASS,  # explicit: never change
    )

    return PromotionResult(
        updated_companion=updated_companion,
        promoted_artifact=promoted,
    )


# ---------------------------------------------------------------------------
# Review queue discovery from companions
# ---------------------------------------------------------------------------


def discover_candidates_from_companions(
    companions: list[SynthesisCompanion],
    queue: Optional[MemoryCandidateReviewQueue] = None,
) -> MemoryCandidateReviewQueue:
    """Discover pending memory candidates from synthesis_companion artifacts.

    Scans each companion in ``companions`` (filtering to those whose
    ``companion_type`` is ``synthesis_companion`` or ``mixed_companion``) and
    enqueues all candidates not already present in ``queue``.

    If ``queue`` is None a fresh ``MemoryCandidateReviewQueue`` is created.

    Returns the queue with all discovered candidates enqueued.
    """
    if queue is None:
        queue = MemoryCandidateReviewQueue()

    for companion in companions:
        if companion.companion_type not in (
            SYNTHESIS_COMPANION_TYPE,
            MIXED_COMPANION_TYPE,
        ):
            continue

        for candidate in companion.candidates.values():
            existing_ids = {e.candidate_id for e in queue.pending() + queue.decided()}
            if candidate.candidate_id not in existing_ids:
                queue.enqueue(candidate)

    return queue


# ---------------------------------------------------------------------------
# Human-section-preserving body update
# ---------------------------------------------------------------------------


def update_companion_candidate_memories_section(
    companion: SynthesisCompanion,
) -> SynthesisCompanion:
    """Regenerate only the ``## Candidate Memories`` section of the companion body.

    All other sections in the body are preserved unchanged.  This satisfies
    the COMPANION_NOTE_PATTERN.md §10 requirement that human-authored sections
    must not be overwritten by system updates.
    """
    updated_body = _update_candidate_memories_section(
        companion.body, companion.candidates
    )

    import dataclasses

    return dataclasses.replace(
        companion,
        body=updated_body,
        updated=datetime.now(timezone.utc).isoformat(),
        artifact_class=COMPANION_ARTIFACT_CLASS,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _render_candidate_memories_block(candidates: dict[str, MemoryCandidate]) -> str:
    """Render the managed ``## Candidate Memories`` block content."""
    if not candidates:
        return "(none)\n"
    lines: list[str] = []
    for candidate in candidates.values():
        lines.append(
            f"- [{candidate.candidate_id}] {candidate.title}"
            f" ({candidate.memory_type.value}, review_state={candidate.review_state.value})"
        )
    return "\n".join(lines) + "\n"


def _update_candidate_memories_section(
    body: str,
    candidates: dict[str, MemoryCandidate],
) -> str:
    """Replace the managed section in ``body`` while preserving all other sections.

    If the managed heading is not present in ``body``, it is appended.  All
    content outside the managed section is untouched.
    """
    new_block = _render_candidate_memories_block(candidates)

    if _MANAGED_SECTION_RE.search(body):
        # Replace the existing managed section content
        def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
            return m.group(1) + new_block

        return _MANAGED_SECTION_RE.sub(_replace, body)

    # Append managed section if not present
    separator = "\n" if body and not body.endswith("\n") else ""
    return body + separator + CANDIDATE_MEMORIES_HEADING + "\n" + new_block


__all__ = [
    "AGENTIC_MEMORY_ARTIFACT_CLASS",
    "CANDIDATE_MEMORIES_HEADING",
    "COMPANION_ARTIFACT_CLASS",
    "MIXED_COMPANION_TYPE",
    "SYNTHESIS_COMPANION_TYPE",
    "PromotionResult",
    "SynthesisCompanion",
    "add_candidate_to_companion",
    "discover_candidates_from_companions",
    "promote_candidate_from_companion",
    "update_companion_candidate_memories_section",
]
