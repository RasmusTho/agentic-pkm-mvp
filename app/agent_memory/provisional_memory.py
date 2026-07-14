"""Fail-closed read model for provisional, direct-write memory.

Markdown is the only meaning-bearing input. Lifecycle receipts deliberately
contain identifiers, hashes, and transition metadata only; they can never be
used to reconstruct a missing claim.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agent_memory.candidate import MemoryType, ReviewState

NonEmptyRef = Annotated[str, Field(min_length=1)]


class ProvisionalEvidenceRole(str, Enum):
    BACKGROUND = "background"
    REFERENCE = "reference"
    ANALOGY = "analogy"
    INSPIRATION = "inspiration"
    NON_EVIDENCE = "non_evidence"


class ProvisionalSensitivity(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PRIVATE = "private"
    SECRET = "secret"


class ProvisionalLifecycleTransition(str, Enum):
    WRITE_STAGED = "write_staged"
    CREATED = "created"
    WRITE_FAILED = "write_failed"
    DELETED = "deleted"


class ProvisionalReconciliationState(str, Enum):
    READY = "ready"
    EDITED = "edited"
    RETRYABLE_PARTIAL = "retryable_partial"
    MISSING = "missing"
    TERMINAL_DELETED = "terminal_deleted"
    INCONSISTENT = "inconsistent"


class ProvisionalMarkdownArtifact(BaseModel):
    """Metadata parsed with the current content of one Markdown artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_id: str = Field(min_length=1)
    artifact_ref: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    principal_id: str = Field(min_length=1)
    memory_type: MemoryType
    evidence_role: ProvisionalEvidenceRole = ProvisionalEvidenceRole.BACKGROUND
    sensitivity: ProvisionalSensitivity
    content: str = Field(min_length=1)
    created_by: str = Field(min_length=1)
    created_at: datetime
    provenance_event_ids: tuple[NonEmptyRef, ...] = Field(min_length=1)
    source_role: Literal["agent_memory"] = "agent_memory"
    authority_state: Literal["noncanonical"] = "noncanonical"
    review_state: Literal[ReviewState.UNREVIEWED] = ReviewState.UNREVIEWED

    @field_validator("created_at")
    @classmethod
    def _require_aware_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @property
    def content_digest(self) -> str:
        return sha256(self.content.encode("utf-8")).hexdigest()


class ProvisionalLifecycleReceipt(BaseModel):
    """Content-free proof of a provisional-memory lifecycle transition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt_id: str = Field(min_length=1)
    memory_id: str = Field(min_length=1)
    artifact_ref: str = Field(min_length=1)
    transition: ProvisionalLifecycleTransition
    actor_ref: str = Field(min_length=1)
    occurred_at: datetime
    artifact_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    error_code: str | None = None

    @field_validator("occurred_at")
    @classmethod
    def _require_aware_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_transition_metadata(self) -> "ProvisionalLifecycleReceipt":
        if self.transition is ProvisionalLifecycleTransition.CREATED:
            if self.artifact_digest is None:
                raise ValueError("created receipt requires artifact_digest")
            if self.error_code is not None:
                raise ValueError("created receipt cannot carry error_code")
        elif self.transition is ProvisionalLifecycleTransition.WRITE_FAILED:
            if not self.error_code:
                raise ValueError("write_failed receipt requires error_code")
            if self.artifact_digest is not None:
                raise ValueError("failed write cannot claim an artifact digest")
        elif self.error_code is not None:
            raise ValueError("error_code is only valid for write_failed")
        return self

    @property
    def terminal(self) -> bool:
        return self.transition in {
            ProvisionalLifecycleTransition.CREATED,
            ProvisionalLifecycleTransition.DELETED,
        }

    @property
    def retryable(self) -> bool:
        return self.transition in {
            ProvisionalLifecycleTransition.WRITE_STAGED,
            ProvisionalLifecycleTransition.WRITE_FAILED,
        }

    def content_free_payload(self) -> dict[str, object]:
        """Return the persistence shape; no claim-content field exists."""
        return self.model_dump(mode="json", exclude_none=True)


class ProvisionalMemoryRecord(BaseModel):
    """Derived MemoryItem-compatible view of current Markdown content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_id: str
    artifact_ref: str
    scope_id: str
    principal_id: str
    memory_type: MemoryType
    evidence_role: ProvisionalEvidenceRole
    sensitivity: ProvisionalSensitivity
    content: str
    created_by: str
    created_at: datetime
    provenance_event_ids: tuple[NonEmptyRef, ...]
    lifecycle_receipt_refs: tuple[NonEmptyRef, ...]
    source_role: Literal["agent_memory"] = "agent_memory"
    authority_state: Literal["noncanonical"] = "noncanonical"
    review_state: Literal[ReviewState.UNREVIEWED] = ReviewState.UNREVIEWED
    may_read: Literal[True] = True
    may_support_cited_proposal: Literal[True] = True
    may_apply: Literal[False] = False
    may_write: Literal[False] = False


class ProvisionalMemoryReconciliation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_id: str
    artifact_ref: str
    state: ProvisionalReconciliationState
    record: ProvisionalMemoryRecord | None = None
    receipt_refs: tuple[str, ...] = ()
    diagnostic: str


def rebuild_provisional_memory(
    *,
    memory_id: str,
    artifact_ref: str,
    artifact: ProvisionalMarkdownArtifact | None,
    receipts: tuple[ProvisionalLifecycleReceipt, ...] = (),
) -> ProvisionalMemoryReconciliation:
    """Reconcile current Markdown with content-free lifecycle receipts.

    Incomplete pairs fail closed. A completed artifact remains readable after a
    human edit, but its state exposes that the receipt digest describes an
    earlier revision. Missing Markdown always produces ``record=None``.
    """
    ordered = tuple(sorted(receipts, key=lambda item: (item.occurred_at, item.receipt_id)))
    refs = tuple(receipt.receipt_id for receipt in ordered)
    if any(
        receipt.memory_id != memory_id or receipt.artifact_ref != artifact_ref
        for receipt in ordered
    ):
        return _reconciliation(
            memory_id, artifact_ref, ProvisionalReconciliationState.INCONSISTENT,
            refs, "receipt_identity_mismatch",
        )
    if artifact is not None and (
        artifact.memory_id != memory_id or artifact.artifact_ref != artifact_ref
    ):
        return _reconciliation(
            memory_id, artifact_ref, ProvisionalReconciliationState.INCONSISTENT,
            refs, "artifact_identity_mismatch",
        )

    latest = ordered[-1] if ordered else None
    if latest is not None and latest.transition is ProvisionalLifecycleTransition.DELETED:
        return _reconciliation(
            memory_id, artifact_ref, ProvisionalReconciliationState.TERMINAL_DELETED,
            refs, "terminal_delete_receipt",
        )
    if artifact is None:
        state = (
            ProvisionalReconciliationState.RETRYABLE_PARTIAL
            if latest is None or latest.retryable
            else ProvisionalReconciliationState.MISSING
        )
        diagnostic = (
            "artifact_absent_retryable"
            if state is ProvisionalReconciliationState.RETRYABLE_PARTIAL
            else "artifact_missing_after_success"
        )
        return _reconciliation(memory_id, artifact_ref, state, refs, diagnostic)
    if latest is None or latest.retryable:
        return _reconciliation(
            memory_id, artifact_ref, ProvisionalReconciliationState.RETRYABLE_PARTIAL,
            refs, "artifact_without_terminal_success_receipt",
        )
    if latest.transition is not ProvisionalLifecycleTransition.CREATED:
        return _reconciliation(
            memory_id, artifact_ref, ProvisionalReconciliationState.INCONSISTENT,
            refs, "unsupported_terminal_transition",
        )

    state = (
        ProvisionalReconciliationState.READY
        if latest.artifact_digest == artifact.content_digest
        else ProvisionalReconciliationState.EDITED
    )
    record = ProvisionalMemoryRecord(
        **artifact.model_dump(),
        lifecycle_receipt_refs=refs,
    )
    return ProvisionalMemoryReconciliation(
        memory_id=memory_id,
        artifact_ref=artifact_ref,
        state=state,
        record=record,
        receipt_refs=refs,
        diagnostic="receipt_matches_markdown" if state is ProvisionalReconciliationState.READY else "markdown_edited_after_receipt",
    )


def _reconciliation(
    memory_id: str,
    artifact_ref: str,
    state: ProvisionalReconciliationState,
    receipt_refs: tuple[str, ...],
    diagnostic: str,
) -> ProvisionalMemoryReconciliation:
    return ProvisionalMemoryReconciliation(
        memory_id=memory_id,
        artifact_ref=artifact_ref,
        state=state,
        receipt_refs=receipt_refs,
        diagnostic=diagnostic,
    )


__all__ = [
    "ProvisionalEvidenceRole",
    "ProvisionalLifecycleReceipt",
    "ProvisionalLifecycleTransition",
    "ProvisionalMarkdownArtifact",
    "ProvisionalMemoryReconciliation",
    "ProvisionalMemoryRecord",
    "ProvisionalReconciliationState",
    "ProvisionalSensitivity",
    "rebuild_provisional_memory",
]
