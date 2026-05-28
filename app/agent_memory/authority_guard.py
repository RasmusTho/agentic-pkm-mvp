"""Memory authority guard for write-authority boundaries (AGENT-MEMORY-05)."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from app.agent_memory.candidate import ContradictionState, MemoryType, ReviewState
from app.agent_memory.promotion import PromotedMemory
from app.agent_memory.recall_explanation import RecallUseRight


class MemoryAuthorityLevel(str, Enum):
    SUGGESTION_ONLY = "suggestion_only"
    INSTRUCTIONAL = "instructional"
    ACTION_AUTHORIZING = "action_authorizing"


class MemoryAuthorityDecision(BaseModel):
    allow_suggestion: bool = True
    allow_mutation: bool = False
    authority_level: MemoryAuthorityLevel = MemoryAuthorityLevel.SUGGESTION_ONLY
    blocked_reasons: list[str] = Field(default_factory=list)
    posture_visibility_required: bool = False
    posture_markers: list[str] = Field(default_factory=list)
    requested_action_scope: Optional[str] = None


_ACTION_AUTHORIZING_MEMORY_TYPES = {
    MemoryType.POLICY_MEMORY,
    MemoryType.PREFERENCE_MEMORY,
}


def evaluate_memory_authority(
    promoted: PromotedMemory,
    *,
    use_right: RecallUseRight,
    requested_action_scope: str | None = None,
    conflicts_with_human_truth: bool = False,
) -> MemoryAuthorityDecision:
    """Evaluate whether recalled memory may escalate to mutation authority.

    Rules:
    - suggestion is allowed as long as posture is visible;
    - mutation authority requires accepted review posture and policy/preference class;
    - inferred/contradicted/revised/rejected memory must surface posture before reuse;
    - human-authored truth always wins over recalled memory.
    """

    candidate = promoted.candidate
    blocked: list[str] = []
    posture_markers: list[str] = []

    if candidate.inferred:
        posture_markers.append("inferred")
    if candidate.contradiction_state is ContradictionState.CONTRADICTED:
        posture_markers.append("contradicted")
    if candidate.contradiction_state is ContradictionState.REVISED:
        posture_markers.append("revised")
    if candidate.contradiction_state is ContradictionState.REJECTED:
        posture_markers.append("rejected")
    if candidate.review_state is ReviewState.REJECTED or promoted.outcome is ReviewState.REJECTED:
        posture_markers.append("rejected")

    posture_visibility_required = bool(posture_markers)

    if candidate.review_state is not ReviewState.ACCEPTED:
        blocked.append("review_state_not_accepted")
    if candidate.inferred:
        blocked.append("inferred_memory_not_mutation_authoritative")
    if promoted.outcome in {ReviewState.REVISED, ReviewState.REJECTED}:
        blocked.append("non_current_memory_lifecycle_state")
    if candidate.contradiction_state in {ContradictionState.CONTRADICTED, ContradictionState.REJECTED}:
        blocked.append("contradiction_state_blocks_mutation_authority")
    if conflicts_with_human_truth:
        blocked.append("human_authored_truth_precedence")

    allow_mutation = False
    authority_level = MemoryAuthorityLevel.SUGGESTION_ONLY

    if use_right is RecallUseRight.INSTRUCTIONAL and candidate.review_state is ReviewState.ACCEPTED:
        authority_level = MemoryAuthorityLevel.INSTRUCTIONAL

    if use_right is RecallUseRight.ACTION_AUTHORIZING:
        if candidate.memory_type not in _ACTION_AUTHORIZING_MEMORY_TYPES:
            blocked.append("memory_type_not_action_authorizing")
        if not requested_action_scope:
            blocked.append("missing_action_scope")
        allow_mutation = len(blocked) == 0
        authority_level = (
            MemoryAuthorityLevel.ACTION_AUTHORIZING
            if allow_mutation
            else MemoryAuthorityLevel.SUGGESTION_ONLY
        )
    else:
        allow_mutation = False

    return MemoryAuthorityDecision(
        allow_suggestion=True,
        allow_mutation=allow_mutation,
        authority_level=authority_level,
        blocked_reasons=sorted(set(blocked)),
        posture_visibility_required=posture_visibility_required,
        posture_markers=sorted(set(posture_markers)),
        requested_action_scope=requested_action_scope,
    )
