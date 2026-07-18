"""HTTP request/response models for the BuilderOps control plane."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AuthorityEnvelopeInput(BaseModel):
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


class AttemptCommitRequest(BaseModel):
    envelope: AuthorityEnvelopeInput
    task_id: str
    attempt_id: str
    state: str
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str
    lease: LeaseInput
    expected_states: list[str] | None = None


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


__all__ = [
    "AttemptCommitRequest",
    "AuthorityEnvelopeInput",
    "InquiryCommitRequest",
    "LeaseClaimRequest",
    "LeaseInput",
    "OutboxClaimRequest",
    "PromotionCommitRequest",
    "RecordCommitRequest",
    "TaskClaimRequest",
    "TaskCompleteRequest",
    "TaskHeartbeatRequest",
]
