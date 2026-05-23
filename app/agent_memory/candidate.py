from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class ReviewState(str, Enum):
    UNREVIEWED = "unreviewed"
    REVIEWED = "reviewed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    REVISED = "revised"


class ActivationPolicy(str, Enum):
    """Activation policy values per CONTEXT_ACTIVATION_SEMANTICS.md §4.3.1.

    Controls under what conditions an artifact may be activated into agent
    working context.  Unreviewed candidates default to review_queue_only,
    which prevents them from entering agent task working context.
    """

    EXPLICIT_ONLY = "explicit_only"
    EXPLICIT_OR_CONTEXTUAL = "explicit_or_contextual"
    ON_RESUME = "on_resume"
    REVIEW_QUEUE_ONLY = "review_queue_only"
    BLOCKED = "blocked"


class MemoryType(str, Enum):
    WORKING_CONTEXT = "working_context"
    EPISODIC_MEMORY = "episodic_memory"
    SEMANTIC_MEMORY = "semantic_memory"
    PROSPECTIVE_MEMORY = "prospective_memory"
    PROCEDURAL_MEMORY = "procedural_memory"
    PREFERENCE_MEMORY = "preference_memory"
    POLICY_MEMORY = "policy_memory"


class ContradictionState(str, Enum):
    CLEAR = "clear"
    CONTRADICTED = "contradicted"
    REVISED = "revised"
    REJECTED = "rejected"


class MemoryCandidate(BaseModel):
    """Candidate memory awaiting review before promotion to durable memory.

    memory_type is the proposed cognitive class — it does not mean the candidate
    is already promoted. review_state must reach ACCEPTED before the candidate
    enters activatable working context.
    """

    artifact_class: str = Field(default="agentic_memory")
    candidate_id: str = Field(default_factory=lambda: uuid4().hex)
    title: str
    memory_type: MemoryType
    artifact_type: Optional[str] = None
    review_state: ReviewState = Field(default=ReviewState.UNREVIEWED)
    # Unreviewed candidates default to review_queue_only — they may enter the
    # review surface but must not enter agent task working context.
    # See CONTEXT_ACTIVATION_SEMANTICS.md §4.3.1.
    activation_policy: ActivationPolicy = Field(
        default=ActivationPolicy.REVIEW_QUEUE_ONLY
    )
    inferred: bool = Field(default=True)

    # Source provenance — first-class fields, not optional comment text
    source_refs: list[str] = Field(default_factory=list)
    derived_from: Optional[str] = None
    generated_by: Optional[str] = None

    content: Optional[str] = None
    confidence: Optional[str] = None

    # Correction and contradiction hooks for revise/reject flows
    contradiction_state: ContradictionState = Field(default=ContradictionState.CLEAR)
    correction_of: Optional[str] = None
    contradiction_notes: Optional[str] = None

    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _enforce_unreviewed_activation_policy(self) -> "MemoryCandidate":
        _UNREVIEWED_ALLOWED = {ActivationPolicy.REVIEW_QUEUE_ONLY, ActivationPolicy.BLOCKED}
        if (
            self.review_state is ReviewState.UNREVIEWED
            and self.activation_policy not in _UNREVIEWED_ALLOWED
        ):
            raise ValueError(
                f"unreviewed candidates must use activation_policy "
                f"'review_queue_only' or 'blocked', got {self.activation_policy!r}"
            )
        return self
