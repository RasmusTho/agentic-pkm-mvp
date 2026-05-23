"""Memory authority guard (AGENT-MEMORY-05).

Implements the authority boundary that prevents unreviewed, inferred, or
contradicted memory from authorizing writeback or overriding human-authored
knowledge, as specified in
``docs/AGENT_MEMORY/PREVENT_UNREVIEWED_MEMORY_AUTHORITY.md``.

Key invariants (all categorical — not configurable, not softened by confidence):

- Unreviewed and rejected memory cannot authorize writeback or governed apply
  flows. ``candidate`` and ``unreviewed`` review states never reach
  ``activatable``, ``instructional``, or ``action_authorizing`` use rights.
- Human-authored artifacts (``human_knowledge``, ``human_authored``,
  ``human_note``) remain stronger authority than recalled memory regardless
  of acceptance state.
- Stale, contradicted, or inferred unreviewed memory must surface its posture
  before reuse; silent consumption raises ``AuthorityGuardError``.
- A suggestion path exists (``SUGGESTIVE`` use right is allowed for unreviewed
  memory) but must not be escalated to ``INSTRUCTIONAL`` or
  ``ACTION_AUTHORIZING`` without review.

This module imports ``UseRight`` from ``recall_explanation`` (AGENT-MEMORY-04)
as the shared use-right vocabulary. It ships no storage backend, activation
engine, or recall surface.
"""

from __future__ import annotations

from typing import Union

from app.agent_memory.candidate import (
    ActivationPolicy,
    ContradictionState,
    MemoryCandidate,
    ReviewState,
)
from app.agent_memory.promotion import PromotedMemory
from app.agent_memory.recall_explanation import UseRight
from app.agent_memory.review_queue import ReviewEntry, ReviewStatus

__all__ = [
    "AuthorityGuardError",
    "assert_writeback_authorized",
    "assert_does_not_override_human_truth",
    "assert_posture_visible",
    "assert_suggestion_only",
]


class AuthorityGuardError(Exception):
    """Raised when a memory authority check fails categorically."""


_HUMAN_AUTHORED_CLASSES = frozenset({"human_knowledge", "human_authored", "human_note"})

_BLOCKED_ACTIVATION_POLICIES = frozenset(
    {ActivationPolicy.REVIEW_QUEUE_ONLY, ActivationPolicy.BLOCKED}
)

_UNESCALATABLE_REVIEW_STATES = frozenset({ReviewState.UNREVIEWED, ReviewState.REVIEWED})

_POSTURE_REQUIRED_CONTRADICTION_STATES = frozenset(
    {ContradictionState.CONTRADICTED, ContradictionState.REVISED}
)


def _extract_candidate(memory: Union[PromotedMemory, ReviewEntry]) -> MemoryCandidate:
    return memory.candidate


# ---------------------------------------------------------------------------
# Public guard functions
# ---------------------------------------------------------------------------


def assert_writeback_authorized(memory: Union[PromotedMemory, ReviewEntry]) -> None:
    """Raise AuthorityGuardError if memory cannot authorize writeback.

    Blocked states:
    - ReviewEntry with PENDING status (unreviewed candidate)
    - PromotedMemory with REJECTED or REVISED outcome
    - candidate.review_state is UNREVIEWED or REVIEWED (not yet accepted)
    - candidate.activation_policy is REVIEW_QUEUE_ONLY or BLOCKED

    The only state that passes: PromotedMemory with outcome=ACCEPTED and
    candidate.review_state=ACCEPTED.

    This guard is categorical. Confidence score, frequency, or proximity to
    sources do not override it.
    """
    candidate = _extract_candidate(memory)

    if isinstance(memory, ReviewEntry):
        if memory.status is ReviewStatus.PENDING:
            raise AuthorityGuardError(
                f"unreviewed candidate {candidate.candidate_id!r} cannot authorize "
                "writeback; candidate must be reviewed and accepted first"
            )

    if isinstance(memory, PromotedMemory):
        if memory.outcome in (ReviewState.REJECTED, ReviewState.REVISED):
            raise AuthorityGuardError(
                f"memory with outcome={memory.outcome!r} cannot authorize writeback; "
                "only ACCEPTED outcome grants write authority"
            )

    if candidate.review_state in (ReviewState.UNREVIEWED, ReviewState.REVIEWED):
        raise AuthorityGuardError(
            f"memory with review_state={candidate.review_state!r} cannot authorize "
            "writeback; review_state must be ACCEPTED"
        )

    if candidate.activation_policy in _BLOCKED_ACTIVATION_POLICIES:
        raise AuthorityGuardError(
            f"memory with activation_policy={candidate.activation_policy!r} cannot "
            "authorize writeback; policy restricts activation to review surface only"
        )


def assert_does_not_override_human_truth(
    memory: Union[PromotedMemory, ReviewEntry],
    *,
    target_artifact_class: str,
) -> None:
    """Raise AuthorityGuardError if memory would override a human-authored artifact.

    Human-authored artifact classes (``human_knowledge``, ``human_authored``,
    ``human_note``) are always stronger authority than recalled memory,
    regardless of the memory's review or acceptance state. This applies even
    to fully promoted memory.
    """
    if target_artifact_class in _HUMAN_AUTHORED_CLASSES:
        candidate = _extract_candidate(memory)
        raise AuthorityGuardError(
            f"memory {candidate.candidate_id!r} cannot override human-authored artifact "
            f"of class {target_artifact_class!r}; human-authored knowledge remains "
            "stronger authority than recalled memory regardless of acceptance state"
        )


def assert_posture_visible(memory: Union[PromotedMemory, ReviewEntry]) -> None:
    """Raise AuthorityGuardError if memory posture must be surfaced before reuse.

    Raises for:
    - candidate.contradiction_state is CONTRADICTED or REVISED (stale/contradicted)
    - candidate.inferred is True AND candidate.review_state is UNREVIEWED

    Passes for:
    - Accepted memory (inferred or not) — review makes the posture explicit
    - Clear, non-contradicted, non-inferred-unreviewed memory

    Silent consumption of stale, contradicted, or inferred unreviewed memory
    is not allowed; the caller must have a surface that makes posture visible
    before reaching a recall or reuse point.
    """
    candidate = _extract_candidate(memory)

    if candidate.contradiction_state in _POSTURE_REQUIRED_CONTRADICTION_STATES:
        raise AuthorityGuardError(
            f"memory {candidate.candidate_id!r} has contradiction_state="
            f"{candidate.contradiction_state!r} and must surface its posture before "
            "reuse; silent consumption of contradicted or stale memory is not allowed"
        )

    if candidate.inferred and candidate.review_state is ReviewState.UNREVIEWED:
        raise AuthorityGuardError(
            f"inferred unreviewed memory {candidate.candidate_id!r} must surface its "
            "posture before reuse; callers must make the inferred/unreviewed status "
            "visible rather than consuming it silently"
        )


def assert_suggestion_only(
    memory: Union[PromotedMemory, ReviewEntry],
    *,
    proposed_use_right: UseRight,
) -> None:
    """Raise AuthorityGuardError if proposed_use_right exceeds SUGGESTIVE for
    unreviewed or not-yet-accepted memory.

    Unreviewed (UNREVIEWED) and in-review-but-not-accepted (REVIEWED) candidates
    may only be used with SUGGESTIVE use right. Any escalation to INFORMATIONAL,
    INSTRUCTIONAL, or ACTION_AUTHORIZING raises.

    Accepted memory is not restricted by this guard — a separate escalation
    check (build_recall_explanation) governs ACTION_AUTHORIZING requirements.
    """
    candidate = _extract_candidate(memory)

    if candidate.review_state in _UNESCALATABLE_REVIEW_STATES:
        if proposed_use_right is not UseRight.SUGGESTIVE:
            raise AuthorityGuardError(
                f"memory with review_state={candidate.review_state!r} may only be used "
                f"with use_right={UseRight.SUGGESTIVE!r}; escalation to "
                f"{proposed_use_right!r} requires review_state=accepted"
            )
