"""Memory promotion, rejection, and revision lifecycle (AGENT-MEMORY-03).

Implements explicit post-review lifecycle decisions as specified in
``docs/AGENT_MEMORY/PROMOTE_REJECT_AND_REVISE_MEMORY.md``.

Key invariants:

- Promotion preserves provenance and review context, not merely a final value.
- Rejection is a visible lifecycle outcome that retains the candidate and its
  rejection receipt; it is not silent deletion.
- Revision is a correction path that references the prior candidate; earlier
  evidence is never silently overwritten.
- Promotion into ``semantic_memory`` requires stricter review evidence than
  simple episodic retention (i.e. an explicit asserted source reference or a
  non-inferred candidate).

This module ships no storage backend, activation engine, or recall surface.
Those are owned by later slices.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from app.agent_memory.candidate import MemoryCandidate, MemoryType, ReviewState
from app.agent_memory.review_queue import (
    ReviewDecision,
    ReviewEntry,
    ReviewStatus,
)


class PromotionError(Exception):
    """Raised when a promotion lifecycle operation violates an explicit invariant."""


class PromotedMemory(BaseModel):
    """A memory candidate that has completed the review lifecycle.

    Promotion copies the full review entry so that provenance, source references,
    and the review decision receipt are preserved alongside the promoted content.
    The artifact is immutable once created; it is a record, not a cursor.
    """

    promotion_id: str = Field(default_factory=lambda: uuid4().hex)
    outcome: ReviewState  # ACCEPTED, REJECTED, or REVISED
    candidate: MemoryCandidate  # full candidate — provenance preserved
    decided_by: str
    decided_at: datetime
    decision_notes: Optional[str] = None
    # For REVISED outcome: ID of the prior candidate this replaces
    revision_of: Optional[str] = None
    promoted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SEMANTIC_TYPES = {MemoryType.SEMANTIC_MEMORY}

# Episodic memory types that can be promoted with standard review evidence
_EPISODIC_TYPES = {
    MemoryType.EPISODIC_MEMORY,
    MemoryType.WORKING_CONTEXT,
    MemoryType.PROSPECTIVE_MEMORY,
    MemoryType.PROCEDURAL_MEMORY,
    MemoryType.PREFERENCE_MEMORY,
    MemoryType.POLICY_MEMORY,
}


def _require_decided(entry: ReviewEntry, expected: ReviewDecision) -> None:
    if entry.status is ReviewStatus.PENDING:
        raise PromotionError(
            f"candidate {entry.candidate_id!r} has not been reviewed yet"
        )
    if entry.decision is not expected:
        raise PromotionError(
            f"candidate {entry.candidate_id!r} has decision "
            f"{entry.decision!r}, expected {expected!r}"
        )


def _require_asserted_promote_fields(entry: ReviewEntry) -> None:
    """Semantic promotion requires stricter review evidence.

    Per the Issue constraint:
    "Semantic promotion (to ``semantic_memory``) requires stricter review evidence
    than episodic retention."

    Stricter evidence means the candidate must carry at least one source reference
    *and* must not be flagged as a pure inference (inferred=False), OR it must
    carry an explicit asserted source reference.  We implement the minimum viable
    rule: the candidate must either be non-inferred OR have more than one source
    reference demonstrating cross-session evidence.
    """
    candidate = entry.candidate
    has_multi_source = len(candidate.source_refs) > 1
    is_asserted = not candidate.inferred
    if not (is_asserted or has_multi_source):
        raise PromotionError(
            f"semantic promotion of {entry.candidate_id!r} requires the candidate to "
            "be non-inferred (asserted) or carry multiple source references as stricter "
            "review evidence; inferred single-source candidates may only be retained as "
            "episodic memory"
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def promote(entry: ReviewEntry) -> PromotedMemory:
    """Promote a reviewed candidate to durable memory.

    Requires ``ReviewDecision.PROMOTE`` to have been recorded on *entry*.
    Enforces stricter evidence requirements for ``semantic_memory`` targets.

    Returns a :class:`PromotedMemory` with ``outcome=ReviewState.ACCEPTED``
    and the full review provenance embedded.
    """
    _require_decided(entry, ReviewDecision.PROMOTE)

    if entry.candidate.memory_type in _SEMANTIC_TYPES:
        _require_asserted_promote_fields(entry)

    return PromotedMemory(
        outcome=ReviewState.ACCEPTED,
        candidate=entry.candidate,
        decided_by=entry.decided_by,  # type: ignore[arg-type]
        decided_at=entry.decided_at,  # type: ignore[arg-type]
        decision_notes=entry.decision_notes,
    )


def reject(entry: ReviewEntry) -> PromotedMemory:
    """Record a visible rejection outcome for a reviewed candidate.

    The candidate artifact is *retained* with ``outcome=ReviewState.REJECTED``
    so the rejection reason and provenance remain inspectable. Rejection is a
    lifecycle state, not deletion.

    Requires ``ReviewDecision.REJECT`` to have been recorded on *entry*.
    """
    _require_decided(entry, ReviewDecision.REJECT)

    return PromotedMemory(
        outcome=ReviewState.REJECTED,
        candidate=entry.candidate,
        decided_by=entry.decided_by,  # type: ignore[arg-type]
        decided_at=entry.decided_at,  # type: ignore[arg-type]
        decision_notes=entry.decision_notes,
    )


def revise(original_entry: ReviewEntry, revised_entry: ReviewEntry) -> PromotedMemory:
    """Record a revision that corrects an earlier candidate.

    The *original_entry* must carry ``ReviewDecision.REVISE``.
    The *revised_entry* is the new pending candidate that replaced it —
    it may be PENDING (awaiting its own decision) or already PROMOTED.

    Returns a :class:`PromotedMemory` for the original entry with
    ``outcome=ReviewState.REVISED`` and ``revision_of`` pointing at the
    original candidate ID.  The revised entry's ``revision_of`` must reference
    the original candidate so the chain of evidence is preserved.

    Earlier evidence in the original candidate is never overwritten; it remains
    accessible via the returned artifact's ``candidate`` field.
    """
    _require_decided(original_entry, ReviewDecision.REVISE)

    if revised_entry.revision_of != original_entry.candidate_id:
        raise PromotionError(
            f"revised entry {revised_entry.candidate_id!r} does not reference "
            f"original candidate {original_entry.candidate_id!r} via revision_of"
        )

    return PromotedMemory(
        outcome=ReviewState.REVISED,
        candidate=original_entry.candidate,
        decided_by=original_entry.decided_by,  # type: ignore[arg-type]
        decided_at=original_entry.decided_at,  # type: ignore[arg-type]
        decision_notes=original_entry.decision_notes,
        revision_of=revised_entry.candidate_id,
    )
