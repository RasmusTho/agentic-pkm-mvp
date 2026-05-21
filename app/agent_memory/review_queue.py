"""Memory candidate review queue (AGENT-MEMORY-02).

Pure-domain review surface that holds :class:`MemoryCandidate` entries until a
reviewer records an explicit decision (promote, reject, or revise). Implements
the boundary required by
``docs/AGENT_MEMORY/ADD_MEMORY_CANDIDATE_REVIEW_QUEUE.md`` and the
hidden-authority guard in
``docs/CONTEXTUALIZATION_LAYER/CONTEXT_ACTIVATION_SEMANTICS.md`` §7: unreviewed
candidates are never authorized for working-context recall.

This module deliberately ships no storage backend, API surface, prompt wiring,
or activation engine. Promotion storage semantics, recall explanation
rendering, and write-authority enforcement are owned by later slices
(#1081, #1082, #1083).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.agent_memory.candidate import MemoryCandidate, MemoryType


class ReviewDecision(str, Enum):
    PROMOTE = "promote"
    REJECT = "reject"
    REVISE = "revise"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    PROMOTED = "promoted"
    REJECTED = "rejected"
    REVISED = "revised"


class ReviewQueueError(Exception):
    """Raised when a review queue operation violates an explicit invariant."""


class ReviewEntry(BaseModel):
    """A candidate's review-surface projection.

    ``status``, ``decision``, ``decided_by``, and ``decided_at`` reflect the
    explicit review decision recorded for the underlying candidate. The
    embedded :class:`MemoryCandidate` is the source of provenance and proposed
    memory class — those fields are surfaced via read-only properties so that
    the review surface preserves them without duplicating the candidate shape.
    """

    model_config = ConfigDict(frozen=True)

    candidate: MemoryCandidate
    status: ReviewStatus = Field(default=ReviewStatus.PENDING)
    decision: Optional[ReviewDecision] = None
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    decision_notes: Optional[str] = None
    revision_of: Optional[str] = None

    @property
    def candidate_id(self) -> str:
        return self.candidate.candidate_id

    @property
    def title(self) -> str:
        return self.candidate.title

    @property
    def content(self) -> Optional[str]:
        return self.candidate.content

    @property
    def source_refs(self) -> list[str]:
        return list(self.candidate.source_refs)

    @property
    def derived_from(self) -> Optional[str]:
        return self.candidate.derived_from

    @property
    def generated_by(self) -> Optional[str]:
        return self.candidate.generated_by

    @property
    def proposed_memory_type(self) -> MemoryType:
        return self.candidate.memory_type

    @property
    def inferred(self) -> bool:
        return self.candidate.inferred

    @property
    def review_posture(self) -> str:
        if self.status is not ReviewStatus.PENDING:
            return "decided"
        return "inferred" if self.candidate.inferred else "asserted"


_DECISION_TO_STATUS: dict[ReviewDecision, ReviewStatus] = {
    ReviewDecision.PROMOTE: ReviewStatus.PROMOTED,
    ReviewDecision.REJECT: ReviewStatus.REJECTED,
    ReviewDecision.REVISE: ReviewStatus.REVISED,
}


class MemoryCandidateReviewQueue:
    """In-memory review queue for memory candidates awaiting decision."""

    def __init__(self) -> None:
        self._entries: dict[str, ReviewEntry] = {}

    def enqueue(self, candidate: MemoryCandidate) -> ReviewEntry:
        if candidate.candidate_id in self._entries:
            raise ReviewQueueError(
                f"candidate already in queue: {candidate.candidate_id}"
            )
        entry = ReviewEntry(candidate=candidate)
        self._entries[candidate.candidate_id] = entry
        return entry

    def get(self, candidate_id: str) -> ReviewEntry:
        try:
            return self._entries[candidate_id]
        except KeyError as exc:
            raise ReviewQueueError(f"no candidate in queue: {candidate_id}") from exc

    def pending(self) -> list[ReviewEntry]:
        return [e for e in self._entries.values() if e.status is ReviewStatus.PENDING]

    def decided(self) -> list[ReviewEntry]:
        return [e for e in self._entries.values() if e.status is not ReviewStatus.PENDING]

    def decide(
        self,
        candidate_id: str,
        decision: ReviewDecision,
        *,
        decided_by: str,
        notes: Optional[str] = None,
        revision: Optional[MemoryCandidate] = None,
    ) -> ReviewEntry:
        """Record an explicit review decision for ``candidate_id``.

        ``decided_by`` is required: a review decision must name its reviewer
        (human ID, policy identifier, or system reviewer ID). Empty values are
        refused because they collapse the human-decision boundary the queue
        exists to enforce.

        ``ReviewDecision.REVISE`` requires a revised :class:`MemoryCandidate`
        which is enqueued as a new pending entry whose ``revision_of`` points
        back to the original candidate. The original entry transitions to
        ``REVISED`` so its evidence remains inspectable.
        """

        if not decided_by:
            raise ReviewQueueError(
                "decided_by is required to record a review decision"
            )

        entry = self.get(candidate_id)
        if entry.status is not ReviewStatus.PENDING:
            raise ReviewQueueError(
                f"candidate already decided: {candidate_id}"
            )

        if decision is ReviewDecision.REVISE:
            if revision is None:
                raise ReviewQueueError(
                    "revise requires a revised MemoryCandidate payload"
                )
            if revision.candidate_id in self._entries:
                raise ReviewQueueError(
                    f"revision candidate id already in queue: {revision.candidate_id}"
                )
            revision_entry = ReviewEntry(
                candidate=revision,
                status=ReviewStatus.PENDING,
                revision_of=candidate_id,
            )
            self._entries[revision.candidate_id] = revision_entry

        updated = entry.model_copy(
            update={
                "status": _DECISION_TO_STATUS[decision],
                "decision": decision,
                "decided_by": decided_by,
                "decided_at": datetime.now(timezone.utc),
                "decision_notes": notes,
            }
        )
        self._entries[candidate_id] = updated
        return updated

    def recallable_for_working_context(self) -> list[ReviewEntry]:
        """Entries authorized for working-context recall.

        Per the hidden-authority guard in
        ``docs/CONTEXTUALIZATION_LAYER/CONTEXT_ACTIVATION_SEMANTICS.md`` §7,
        only entries with an explicit PROMOTE decision are authorized for
        agent working-context recall by this surface. Unreviewed and rejected
        entries are excluded; revised entries hand authority to the revised
        successor, which must itself be reviewed.
        """

        return [e for e in self._entries.values() if e.status is ReviewStatus.PROMOTED]
