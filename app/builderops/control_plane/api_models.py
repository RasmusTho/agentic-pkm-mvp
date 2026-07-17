"""HTTP request/response models for the BuilderOps control plane."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AuthorityEnvelopeInput(BaseModel):
    repository: str
    scope: str
    stack: str
    source_refs: list[str] = Field(min_length=1)
    schema_version: int = Field(default=1, ge=1)


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


__all__ = ["AuthorityEnvelopeInput", "LeaseClaimRequest", "RecordCommitRequest"]
