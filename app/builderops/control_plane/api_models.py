"""HTTP request/response models for the BuilderOps control plane."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AuthorityEnvelopeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: str
    scope: str
    stack: str
    source_refs: list[str] = Field(min_length=1)
    schema_version: int = Field(default=1, ge=1)


class LeaseInput(BaseModel):
    """Client-returned lease fields for a follow-up fenced mutation.

    The repository is carried by the request envelope; every other lease field
    is echoed back so the store can re-validate the fencing token and holder.
    """

    resource_id: str
    holder: str
    fencing_token: int = Field(ge=1)
    expires_at: datetime
    lease_kind: str = "task"


class LeaseClaimRequest(BaseModel):
    envelope: AuthorityEnvelopeInput
    resource_id: str
    idempotency_key: str
    request: dict[str, Any] = Field(default_factory=dict)
    ttl_seconds: int = Field(default=5400, ge=1, le=86400)


class RecordCommitRequest(BaseModel):
    envelope: AuthorityEnvelopeInput
    record_id: str
    record_type: str
    state: str
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str


class InquiryCommitRequest(BaseModel):
    """Model-inquiry authority object; a specialization of a record commit."""

    envelope: AuthorityEnvelopeInput
    inquiry_id: str
    state: str
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str


class TaskClaimRequest(BaseModel):
    envelope: AuthorityEnvelopeInput
    task_id: str
    idempotency_key: str
    request: dict[str, Any] = Field(default_factory=dict)
    ttl_seconds: int = Field(default=5400, ge=1, le=86400)
    require_new_fence: bool = False


class TaskHeartbeatRequest(BaseModel):
    envelope: AuthorityEnvelopeInput
    lease: LeaseInput
    idempotency_key: str
    request: dict[str, Any] = Field(default_factory=dict)
    ttl_seconds: int = Field(default=5400, ge=1, le=86400)


class TaskCompleteRequest(BaseModel):
    envelope: AuthorityEnvelopeInput
    lease: LeaseInput
    idempotency_key: str
    request: dict[str, Any] = Field(default_factory=dict)
    expected_version: int = Field(ge=1)


class TaskReleaseRequest(BaseModel):
    envelope: AuthorityEnvelopeInput
    lease: LeaseInput
    idempotency_key: str
    request: dict[str, Any] = Field(default_factory=dict)
    expected_version: int = Field(ge=1)


class TaskTransitionRequest(BaseModel):
    envelope: AuthorityEnvelopeInput
    task_id: str
    to_state: str
    idempotency_key: str
    request: dict[str, Any] = Field(default_factory=dict)
    outbox: dict[str, Any] | None = None
    lease: LeaseInput | None = None
    expected_states: list[str] | None = None
    expected_version: int | None = Field(default=None, ge=1)


class AttemptCommitRequest(BaseModel):
    envelope: AuthorityEnvelopeInput
    task_id: str
    attempt_id: str
    state: str
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str
    lease: LeaseInput
    expected_states: list[str] | None = None
    expected_task_version: int = Field(ge=1)


class PromotionCommitRequest(BaseModel):
    envelope: AuthorityEnvelopeInput
    promotion_id: str
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str
    lease: LeaseInput | None = None
    expected_states: list[str] | None = None


class OutboxClaimRequest(BaseModel):
    """Privileged executor request to claim a durable external-effect intent."""

    envelope: AuthorityEnvelopeInput
    operation_key: str | None = None
    worker_id: str
    claim_ttl_seconds: int = Field(default=300, ge=1, le=3600)


class OutboxRecoverRequest(BaseModel):
    envelope: AuthorityEnvelopeInput
    operation_key: str
    worker_id: str
    claim_ttl_seconds: int = Field(default=300, ge=1, le=3600)


class OutboxClaimInput(BaseModel):
    repository: str
    operation_key: str
    worker_id: str
    fencing_token: int = Field(ge=1)
    intent_lsn: str
    claim_lsn: str
    receipt_sequence: int = Field(ge=1)
    expires_at: datetime


class OutboxUnknownRequest(BaseModel):
    envelope: AuthorityEnvelopeInput
    claim: OutboxClaimInput
    detail: str


class OutboxReconcileRequest(BaseModel):
    envelope: AuthorityEnvelopeInput
    claim: OutboxClaimInput
    observed_applied: bool
    terminal_unknown: bool = False
    evidence: dict[str, Any] = Field(default_factory=dict)


class RowDerivedPostEffectPendingRequest(BaseModel):
    """Dormant #4898 phase: only a row locator and current fence are accepted."""

    model_config = ConfigDict(extra="forbid")
    envelope: AuthorityEnvelopeInput
    operation_key: str = Field(min_length=1)
    minimum_fencing_token: int = Field(ge=1)


class RowDerivedPostEffectEvidence(BaseModel):
    """Closed readback vocabulary; claim/LSN authority never enters evidence."""

    model_config = ConfigDict(extra="forbid")
    readback: Literal["found", "not-found", "unknown"]
    merge_sha: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{40}$")
    provider_session_id: str | None = Field(default=None, min_length=1, max_length=256)
    relaunch_performed: bool | None = None


class RowDerivedPostEffectReconcileRequest(RowDerivedPostEffectPendingRequest):
    observed_applied: bool
    terminal_unknown: bool = False
    evidence: RowDerivedPostEffectEvidence


__all__ = [
    "AttemptCommitRequest",
    "AuthorityEnvelopeInput",
    "InquiryCommitRequest",
    "LeaseClaimRequest",
    "LeaseInput",
    "OutboxClaimRequest",
    "OutboxClaimInput",
    "OutboxRecoverRequest",
    "OutboxReconcileRequest",
    "OutboxUnknownRequest",
    "RowDerivedPostEffectPendingRequest",
    "RowDerivedPostEffectEvidence",
    "RowDerivedPostEffectReconcileRequest",
    "PromotionCommitRequest",
    "RecordCommitRequest",
    "TaskClaimRequest",
    "TaskCompleteRequest",
    "TaskHeartbeatRequest",
    "TaskReleaseRequest",
    "TaskTransitionRequest",
]
