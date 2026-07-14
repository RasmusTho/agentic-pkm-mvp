"""Fail-closed read model for provisional, direct-write memory.

Markdown is the only meaning-bearing input. Lifecycle receipts deliberately
contain identifiers, hashes, and transition metadata only; they can never be
used to reconstruct a missing claim.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from typing import Annotated, Literal

from pydantic import UUID4, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agent_memory.candidate import MemoryType, ReviewState

NonEmptyRef = Annotated[str, Field(min_length=1)]
EntityId = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
ArtifactRef = Annotated[
    str,
    Field(
        min_length=66,
        max_length=66,
        pattern=(
            r"^vault://Memory/Provisional/"
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-"
            r"[0-9a-f]{12}\.md$"
        ),
    ),
]


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


class ProvisionalFailureCode(str, Enum):
    VAULT_WRITE_FAILED = "vault_write_failed"
    RECEIPT_PERSIST_FAILED = "receipt_persist_failed"
    VALIDATION_FAILED = "validation_failed"
    WRITE_CONFLICT = "write_conflict"
    PERMISSION_DENIED = "permission_denied"


class ProvisionalActor(str, Enum):
    AGENT = "agent"
    HUMAN = "human"
    SYSTEM = "system"


class ProvisionalReconciliationState(str, Enum):
    READY = "ready"
    EDITED = "edited"
    RETRYABLE_PARTIAL = "retryable_partial"
    MISSING = "missing"
    TERMINAL_DELETED = "terminal_deleted"
    INCONSISTENT = "inconsistent"


class ProvisionalDiagnostic(str, Enum):
    RECEIPT_IDENTITY_MISMATCH = "receipt_identity_mismatch"
    ARTIFACT_IDENTITY_MISMATCH = "artifact_identity_mismatch"
    CONFLICTING_RECEIPT_ID = "conflicting_receipt_id"
    AMBIGUOUS_RECEIPT_ORDER = "ambiguous_receipt_order"
    TERMINAL_DELETE_RECEIPT = "terminal_delete_receipt"
    ARTIFACT_ABSENT_RETRYABLE = "artifact_absent_retryable"
    ARTIFACT_MISSING_AFTER_SUCCESS = "artifact_missing_after_success"
    ARTIFACT_WITHOUT_SUCCESS = "artifact_without_terminal_success_receipt"
    UNSUPPORTED_TERMINAL = "unsupported_terminal_transition"
    RECEIPT_MATCHES_MARKDOWN = "receipt_matches_markdown"
    MARKDOWN_EDITED_AFTER_RECEIPT = "markdown_edited_after_receipt"


class ProvisionalMarkdownArtifact(BaseModel):
    """Metadata parsed with the current content of one Markdown artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_id: UUID4
    artifact_ref: ArtifactRef
    scope_id: EntityId
    principal_id: EntityId
    memory_type: MemoryType
    evidence_role: ProvisionalEvidenceRole = ProvisionalEvidenceRole.BACKGROUND
    sensitivity: ProvisionalSensitivity
    content: str = Field(min_length=1)
    created_by: NonEmptyRef
    created_at: datetime
    provenance_event_ids: tuple[NonEmptyRef, ...] = Field(min_length=1)
    source_role: Literal["agent_memory"] = "agent_memory"
    authority_state: Literal["noncanonical"] = "noncanonical"
    review_state: Literal[ReviewState.UNREVIEWED] = ReviewState.UNREVIEWED

    @model_validator(mode="after")
    def _require_canonical_artifact_ref(self) -> "ProvisionalMarkdownArtifact":
        if self.artifact_ref != _artifact_ref_for(self.memory_id):
            raise ValueError("artifact_ref must be canonical for memory_id")
        return self

    @field_validator("created_at")
    @classmethod
    def _require_aware_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @property
    def artifact_digest(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return sha256(canonical.encode("utf-8")).hexdigest()


class ProvisionalLifecycleReceipt(BaseModel):
    """Content-free proof of a provisional-memory lifecycle transition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt_id: UUID4
    memory_id: UUID4
    artifact_ref: ArtifactRef
    transition: ProvisionalLifecycleTransition
    actor_ref: ProvisionalActor
    occurred_at: datetime
    artifact_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    error_code: ProvisionalFailureCode | None = None

    @field_validator("occurred_at")
    @classmethod
    def _require_aware_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_transition_metadata(self) -> "ProvisionalLifecycleReceipt":
        if self.artifact_ref != _artifact_ref_for(self.memory_id):
            raise ValueError("artifact_ref must be canonical for memory_id")
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

    memory_id: UUID4
    artifact_ref: ArtifactRef
    scope_id: EntityId
    principal_id: EntityId
    memory_type: MemoryType
    evidence_role: ProvisionalEvidenceRole
    sensitivity: ProvisionalSensitivity
    content: str = Field(min_length=1)
    created_by: NonEmptyRef
    created_at: datetime
    provenance_event_ids: tuple[NonEmptyRef, ...] = Field(min_length=1)
    lifecycle_receipt_refs: tuple[UUID4, ...] = Field(min_length=1)
    source_role: Literal["agent_memory"] = "agent_memory"
    authority_state: Literal["noncanonical"] = "noncanonical"
    review_state: Literal[ReviewState.UNREVIEWED] = ReviewState.UNREVIEWED
    may_read: Literal[True] = True
    may_support_cited_proposal: Literal[True] = True
    may_apply: Literal[False] = False
    may_write: Literal[False] = False

    @field_validator("created_at")
    @classmethod
    def _require_aware_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value


class ProvisionalMemoryReconciliation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_id: UUID4
    artifact_ref: ArtifactRef
    state: ProvisionalReconciliationState
    record: ProvisionalMemoryRecord | None = None
    receipt_refs: tuple[UUID4, ...] = ()
    diagnostic: ProvisionalDiagnostic

    @model_validator(mode="after")
    def _enforce_record_posture(self) -> "ProvisionalMemoryReconciliation":
        if self.artifact_ref != _artifact_ref_for(self.memory_id):
            raise ValueError("artifact_ref must be canonical for memory_id")
        readable = self.state in {
            ProvisionalReconciliationState.READY,
            ProvisionalReconciliationState.EDITED,
        }
        if readable and self.record is None:
            raise ValueError("readable reconciliation state requires record")
        if not readable and self.record is not None:
            raise ValueError("excluded reconciliation state cannot carry record")
        if self.record is not None:
            if (
                self.record.memory_id != self.memory_id
                or self.record.artifact_ref != self.artifact_ref
            ):
                raise ValueError("record identity must match reconciliation envelope")
            if self.record.lifecycle_receipt_refs != self.receipt_refs:
                raise ValueError("record receipt refs must match reconciliation envelope")
        return self


def rebuild_provisional_memory(
    *,
    memory_id: UUID4,
    artifact_ref: str,
    artifact: ProvisionalMarkdownArtifact | None,
    receipts: tuple[ProvisionalLifecycleReceipt, ...] = (),
) -> ProvisionalMemoryReconciliation:
    """Reconcile current Markdown with content-free lifecycle receipts.

    Incomplete pairs fail closed. A completed artifact remains readable after a
    human edit, but its state exposes that the receipt digest describes an
    earlier revision. Missing Markdown always produces ``record=None``.
    """
    normalized, conflict = _normalize_receipts(receipts)
    if conflict is not None:
        return _reconciliation(memory_id, artifact_ref, conflict[0], (), conflict[1])
    ordered = tuple(sorted(normalized, key=lambda item: (item.occurred_at, item.receipt_id)))
    refs = tuple(receipt.receipt_id for receipt in ordered)
    if any(
        receipt.memory_id != memory_id or receipt.artifact_ref != artifact_ref
        for receipt in ordered
    ):
        return _reconciliation(
            memory_id, artifact_ref, ProvisionalReconciliationState.INCONSISTENT,
            refs, ProvisionalDiagnostic.RECEIPT_IDENTITY_MISMATCH,
        )
    if artifact is not None and (
        artifact.memory_id != memory_id or artifact.artifact_ref != artifact_ref
    ):
        return _reconciliation(
            memory_id, artifact_ref, ProvisionalReconciliationState.INCONSISTENT,
            refs, ProvisionalDiagnostic.ARTIFACT_IDENTITY_MISMATCH,
        )

    latest = ordered[-1] if ordered else None
    if any(
        receipt.transition is ProvisionalLifecycleTransition.DELETED
        for receipt in ordered
    ):
        return _reconciliation(
            memory_id, artifact_ref, ProvisionalReconciliationState.TERMINAL_DELETED,
            refs, ProvisionalDiagnostic.TERMINAL_DELETE_RECEIPT,
        )
    if artifact is None:
        state = (
            ProvisionalReconciliationState.RETRYABLE_PARTIAL
            if latest is None or latest.retryable
            else ProvisionalReconciliationState.MISSING
        )
        diagnostic = (
            ProvisionalDiagnostic.ARTIFACT_ABSENT_RETRYABLE
            if state is ProvisionalReconciliationState.RETRYABLE_PARTIAL
            else ProvisionalDiagnostic.ARTIFACT_MISSING_AFTER_SUCCESS
        )
        return _reconciliation(memory_id, artifact_ref, state, refs, diagnostic)
    if latest is None or latest.retryable:
        return _reconciliation(
            memory_id, artifact_ref, ProvisionalReconciliationState.RETRYABLE_PARTIAL,
            refs, ProvisionalDiagnostic.ARTIFACT_WITHOUT_SUCCESS,
        )
    if latest.transition is not ProvisionalLifecycleTransition.CREATED:
        return _reconciliation(
            memory_id, artifact_ref, ProvisionalReconciliationState.INCONSISTENT,
            refs, ProvisionalDiagnostic.UNSUPPORTED_TERMINAL,
        )

    state = (
        ProvisionalReconciliationState.READY
        if latest.artifact_digest == artifact.artifact_digest
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
        diagnostic=(
            ProvisionalDiagnostic.RECEIPT_MATCHES_MARKDOWN
            if state is ProvisionalReconciliationState.READY
            else ProvisionalDiagnostic.MARKDOWN_EDITED_AFTER_RECEIPT
        ),
    )


def _reconciliation(
    memory_id: UUID4,
    artifact_ref: str,
    state: ProvisionalReconciliationState,
    receipt_refs: tuple[UUID4, ...],
    diagnostic: ProvisionalDiagnostic,
) -> ProvisionalMemoryReconciliation:
    return ProvisionalMemoryReconciliation(
        memory_id=memory_id,
        artifact_ref=artifact_ref,
        state=state,
        receipt_refs=receipt_refs,
        diagnostic=diagnostic,
    )


def _normalize_receipts(
    receipts: tuple[ProvisionalLifecycleReceipt, ...],
) -> tuple[
    tuple[ProvisionalLifecycleReceipt, ...],
    tuple[ProvisionalReconciliationState, ProvisionalDiagnostic] | None,
]:
    by_id: dict[UUID4, ProvisionalLifecycleReceipt] = {}
    for receipt in receipts:
        existing = by_id.get(receipt.receipt_id)
        if existing is not None and existing != receipt:
            return (), (
                ProvisionalReconciliationState.INCONSISTENT,
                ProvisionalDiagnostic.CONFLICTING_RECEIPT_ID,
            )
        by_id[receipt.receipt_id] = receipt
    normalized = tuple(by_id.values())
    timestamps = [receipt.occurred_at for receipt in normalized]
    if len(timestamps) != len(set(timestamps)):
        return (), (
            ProvisionalReconciliationState.INCONSISTENT,
            ProvisionalDiagnostic.AMBIGUOUS_RECEIPT_ORDER,
        )
    return normalized, None


def _artifact_ref_for(memory_id: UUID4) -> str:
    return f"vault://Memory/Provisional/{memory_id}.md"


__all__ = [
    "ProvisionalEvidenceRole",
    "ProvisionalDiagnostic",
    "ProvisionalActor",
    "ProvisionalFailureCode",
    "ProvisionalLifecycleReceipt",
    "ProvisionalLifecycleTransition",
    "ProvisionalMarkdownArtifact",
    "ProvisionalMemoryReconciliation",
    "ProvisionalMemoryRecord",
    "ProvisionalReconciliationState",
    "ProvisionalSensitivity",
    "rebuild_provisional_memory",
]
