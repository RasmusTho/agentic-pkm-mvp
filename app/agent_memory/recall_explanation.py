"""Recall explanation surfaces (AGENT-MEMORY-04).

Implements the recall explanation contract as specified in
``docs/AGENT_MEMORY/EXPLAIN_MEMORY_RECALL.md``.

Key invariants:

- Recall explanation includes source provenance and review posture.
- Recall explanation includes an activation_reason ("why now"), not only a
  replay of the stored memory text.
- Recall explanation preserves lifecycle state (inferred, promoted, revised,
  historically rejected) at the time of activation.
- Recall explanation preserves authority limits: use_right and authority_limits
  make explicit what the recalled memory cannot do, not only what it says.
- ACTION_AUTHORIZING use right requires all three of action_scope,
  authority_source, and receipt_ref — missing any raises RecallExplanationError.
- Unreviewed or rejected memory is capped at SUGGESTIVE regardless of any
  action kwargs supplied; attempting to escalate raises RecallExplanationError.
- Both compact_trace() and full_audit() must be derivable without information
  loss from one RecallExplanation object.

This module ships no storage backend, activation engine, or write-authority
guard. Those are owned by later slices (#1083).
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Union

from pydantic import BaseModel, ConfigDict

from app.agent_memory.candidate import MemoryCandidate, ReviewState
from app.agent_memory.promotion import PromotedMemory
from app.agent_memory.review_queue import ReviewEntry


class UseRight(str, Enum):
    """Activation use right for a recalled memory artifact.

    Derived deterministically from the candidate's review_state at the time
    of recall. Higher rights require stricter review evidence.
    """

    SUGGESTIVE = "suggestive"
    INFORMATIONAL = "informational"
    INSTRUCTIONAL = "instructional"
    ACTION_AUTHORIZING = "action_authorizing"


class LifecycleState(str, Enum):
    """The lifecycle posture of recalled memory at activation time."""

    INFERRED = "inferred"
    PROMOTED = "promoted"
    REVISED = "revised"
    HISTORICALLY_REJECTED = "historically_rejected"


class RecallExplanationError(Exception):
    """Raised when a recall explanation cannot be built due to an invariant violation."""


_AUTHORITY_LIMITS: dict[UseRight, str] = {
    UseRight.SUGGESTIVE: (
        "This memory may inform a suggestion only; "
        "it cannot authorize any action or override any human-authored artifact."
    ),
    UseRight.INFORMATIONAL: (
        "This memory may inform reasoning but cannot authorize mutation, "
        "apply flows, or instructional reuse."
    ),
    UseRight.INSTRUCTIONAL: (
        "This memory may be used as an instruction but cannot authorize writes, "
        "apply flows, or override human-authored artifacts."
    ),
    UseRight.ACTION_AUTHORIZING: (
        "Authority is bounded by action_scope; this memory cannot override "
        "human-authored contracts or authorize actions outside that scope."
    ),
}

_UNESCALATABLE_STATES = {ReviewState.UNREVIEWED, ReviewState.REJECTED}


class RecallExplanation(BaseModel):
    """Explanation surface for a single memory recall event.

    Carries identity, provenance, lifecycle posture, activation rationale, and
    authority limits in one immutable record. Both compact_trace() and
    full_audit() are derivable without information loss.
    """

    model_config = ConfigDict(frozen=True)

    # Identity
    artifact_id: str
    artifact_title: str

    # Why now — caller-supplied rationale; must not merely replay stored text
    activation_reason: str

    # Provenance
    source_refs: list[str]
    review_state: ReviewState

    # Lifecycle posture at activation time
    lifecycle_state: LifecycleState

    # Authority framing
    use_right: UseRight
    authority_limits: str

    # ACTION_AUTHORIZING fields — None for all other use rights
    action_scope: Optional[str] = None
    authority_source: Optional[str] = None
    receipt_ref: Optional[str] = None

    def compact_trace(self) -> str:
        """Single-line form: '[id8] title | lifecycle | use_right | activation_reason'."""
        return (
            f"[{self.artifact_id[:8]}] {self.artifact_title} "
            f"| {self.lifecycle_state} | {self.use_right} "
            f"| {self.activation_reason}"
        )

    def full_audit(self) -> dict[str, object]:
        """Full field dict — no information loss between compact and audit forms."""
        return self.model_dump()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_candidate(memory: Union[PromotedMemory, ReviewEntry]) -> MemoryCandidate:
    return memory.candidate


def _derive_lifecycle(memory: Union[PromotedMemory, ReviewEntry]) -> LifecycleState:
    if isinstance(memory, PromotedMemory):
        if memory.outcome is ReviewState.ACCEPTED:
            return LifecycleState.PROMOTED
        if memory.outcome is ReviewState.REVISED:
            return LifecycleState.REVISED
        return LifecycleState.HISTORICALLY_REJECTED
    # ReviewEntry still in queue
    return LifecycleState.INFERRED


def _derive_use_right(
    candidate: MemoryCandidate,
    *,
    action_scope: Optional[str],
    authority_source: Optional[str],
    receipt_ref: Optional[str],
) -> UseRight:
    rs = candidate.review_state
    if rs in _UNESCALATABLE_STATES:
        return UseRight.SUGGESTIVE
    if rs is ReviewState.REVIEWED:
        return UseRight.INFORMATIONAL
    if rs is ReviewState.ACCEPTED:
        if action_scope is not None or authority_source is not None or receipt_ref is not None:
            # Will be validated as ACTION_AUTHORIZING below
            return UseRight.ACTION_AUTHORIZING
        return UseRight.INSTRUCTIONAL
    # Fallback for any unanticipated review_state value
    return UseRight.SUGGESTIVE


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_recall_explanation(
    memory: Union[PromotedMemory, ReviewEntry],
    *,
    activation_reason: str,
    action_scope: Optional[str] = None,
    authority_source: Optional[str] = None,
    receipt_ref: Optional[str] = None,
) -> RecallExplanation:
    """Build a recall explanation for a recalled memory artifact.

    ``activation_reason`` is the caller-supplied "why now" rationale. It must
    be distinct from the stored memory text — its purpose is to explain why
    this memory is relevant to the current context, not to replay what the
    memory says.

    The three ``action_*`` kwargs are required together when the caller
    intends an ACTION_AUTHORIZING use right. Supplying any of them without
    the others raises RecallExplanationError. Supplying them for a candidate
    whose review_state is not ACCEPTED also raises — unreviewed memory cannot
    be escalated to action-authorizing use right.
    """
    candidate = _extract_candidate(memory)
    lifecycle_state = _derive_lifecycle(memory)

    action_kwargs = (action_scope, authority_source, receipt_ref)
    has_any_action_kwarg = any(v is not None for v in action_kwargs)
    has_all_action_kwargs = all(v is not None for v in action_kwargs)

    # Block escalation for unescalatable states regardless of kwargs
    if has_any_action_kwarg and candidate.review_state in _UNESCALATABLE_STATES:
        raise RecallExplanationError(
            f"cannot escalate memory with review_state={candidate.review_state!r} "
            "to action_authorizing use right; action kwargs require review_state=accepted"
        )

    # If any action kwarg is provided, all three must be present
    if has_any_action_kwarg and not has_all_action_kwargs:
        missing = [
            name
            for name, val in [
                ("action_scope", action_scope),
                ("authority_source", authority_source),
                ("receipt_ref", receipt_ref),
            ]
            if val is None
        ]
        raise RecallExplanationError(
            f"action_authorizing recall requires all three kwargs; "
            f"missing: {', '.join(missing)}"
        )

    use_right = _derive_use_right(
        candidate,
        action_scope=action_scope,
        authority_source=authority_source,
        receipt_ref=receipt_ref,
    )
    authority_limits = _AUTHORITY_LIMITS[use_right]

    artifact_id: str
    if isinstance(memory, PromotedMemory):
        artifact_id = memory.promotion_id
    else:
        artifact_id = memory.candidate_id

    return RecallExplanation(
        artifact_id=artifact_id,
        artifact_title=candidate.title,
        activation_reason=activation_reason,
        source_refs=list(candidate.source_refs),
        review_state=candidate.review_state,
        lifecycle_state=lifecycle_state,
        use_right=use_right,
        authority_limits=authority_limits,
        action_scope=action_scope,
        authority_source=authority_source,
        receipt_ref=receipt_ref,
    )
