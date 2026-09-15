"""HTTP request/response models for the BuilderOps control plane."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class OwnerOutcomeCommitRequest(BaseModel):
    """Confirm-and-commit subtype on the existing record route."""

    model_config = ConfigDict(extra="forbid")
    record_type: Literal["BuilderOpsReceipt"]
    owner_outcome: dict[str, Any]
    idempotency_key: str = Field(min_length=1, max_length=128)


class OwnerAskCommitRequest(BaseModel):
    """Publish a source-validated existing proposal, without starting it."""

    model_config = ConfigDict(extra="forbid")
    record_type: Literal["BuilderOpsReceipt"]
    owner_ask: dict[str, Any]


class InquiryCommitRequest(BaseModel):
    """Model-inquiry authority object; a specialization of a record commit."""

    envelope: AuthorityEnvelopeInput
    inquiry_id: str
    state: str
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str


class InquiryCommandPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str
    approval_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=16384)
    context_pack: dict[str, Any]
    expires_at: datetime


class InquiryCommandStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["start", "hold"]
    proposal: dict[str, Any]
    material: dict[str, Any]


class InquiryCommandAuthorityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval: dict[str, Any]
    purpose: Literal["reserve", "attempt", "execute", "readback"]


class IssueDeliveryPreviewRequest(BaseModel):
    """Exact manifest for the finite FCA-ID-A Issue-delivery admission slice.

    The before-validator accepts both the explicit ``manifest`` envelope and
    the top-level form used by older control-plane clients.  The service owns
    the canonicalization and adds the authenticated grant/epoch fields; no
    caller can provide those authority fields as a substitute.
    """

    model_config = ConfigDict(extra="forbid")
    manifest: dict[str, Any]

    @model_validator(mode="before")
    @classmethod
    def _accept_top_level_manifest(cls, value: Any) -> Any:
        if isinstance(value, dict) and "manifest" not in value:
            return {"manifest": value}
        return value


class IssueDeliveryStartRequest(BaseModel):
    """Owner Hold/Start decision over one exact preview manifest."""

    model_config = ConfigDict(extra="forbid")
    decision: Literal["start", "hold"]
    manifest: dict[str, Any]

    @model_validator(mode="before")
    @classmethod
    def _accept_proposal_alias(cls, value: Any) -> Any:
        if isinstance(value, dict):
            result = dict(value)
            if "manifest" not in result and "proposal" in result:
                result["manifest"] = result.pop("proposal")
            return result
        return value


class IssueDeliveryAuthorityRequest(BaseModel):
    """Destination authority read; execution/read grants stay separate."""

    model_config = ConfigDict(extra="forbid")
    manifest: dict[str, Any]
    purpose: Literal["execute", "readback"]

    @model_validator(mode="before")
    @classmethod
    def _accept_approval_alias(cls, value: Any) -> Any:
        if isinstance(value, dict):
            result = dict(value)
            if "manifest" not in result and "approval" in result:
                result["manifest"] = result.pop("approval")
            return result
        return value


class IssueDeliveryOperationRecordRequest(BaseModel):
    """Destination-owned receipt write for the FCA-ID-B operation adapter.

    The destination never receives a generic ``records:write`` capability for
    these records.  The service re-reads the committed Issue approval and
    current execute grant before accepting the exact reservation/attempt/entry
    binding below.
    """

    model_config = ConfigDict(extra="forbid")

    envelope: AuthorityEnvelopeInput
    record_id: str = Field(min_length=1, max_length=512)
    state: Literal["reserved", "attempted", "active", "launch_unknown", "terminal"]
    payload: dict[str, Any]
    idempotency_key: str = Field(min_length=1, max_length=512)
    operation_key: str = Field(min_length=1, max_length=256)
    approval_id: str = Field(min_length=1, max_length=256)
    approval_manifest_hash: str = Field(min_length=64, max_length=64)


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


class RowDerivedReadbackEvidence(BaseModel):
    """Closed ordinary readback vocabulary; claim/LSN authority never enters evidence."""

    model_config = ConfigDict(extra="forbid")
    readback: Literal["found", "not-found", "unknown"]
    relaunch_performed: bool | None = None


class TerminalUnknownModelEvidence(BaseModel):
    """Exact pre-session model-effect evidence for a terminal unknown result."""

    model_config = ConfigDict(extra="forbid")
    head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    outcome: Literal["indeterminate_pre_session_model_effect"]
    provider_session_id: None
    relaunch_performed: Literal[False]


RowDerivedPostEffectEvidence = (
    RowDerivedReadbackEvidence | TerminalUnknownModelEvidence
)


class RowDerivedPostEffectReconcileRequest(RowDerivedPostEffectPendingRequest):
    observed_applied: bool
    terminal_unknown: bool = False
    evidence: RowDerivedPostEffectEvidence

    @model_validator(mode="after")
    def _terminal_unknown_uses_exact_evidence(
        self,
    ) -> "RowDerivedPostEffectReconcileRequest":
        is_terminal_evidence = isinstance(self.evidence, TerminalUnknownModelEvidence)
        if self.terminal_unknown != is_terminal_evidence:
            raise ValueError(
                "terminal-unknown reconciliation requires exact terminal evidence"
            )
        return self


__all__ = [
    "AttemptCommitRequest",
    "AuthorityEnvelopeInput",
    "InquiryCommitRequest",
    "IssueDeliveryAuthorityRequest",
    "IssueDeliveryPreviewRequest",
    "IssueDeliveryStartRequest",
    "LeaseClaimRequest",
    "LeaseInput",
    "OutboxClaimRequest",
    "OutboxClaimInput",
    "OutboxRecoverRequest",
    "OutboxReconcileRequest",
    "OutboxUnknownRequest",
    "RowDerivedPostEffectPendingRequest",
    "RowDerivedPostEffectEvidence",
    "RowDerivedReadbackEvidence",
    "TerminalUnknownModelEvidence",
    "RowDerivedPostEffectReconcileRequest",
    "PromotionCommitRequest",
    "RecordCommitRequest",
    "TaskClaimRequest",
    "TaskCompleteRequest",
    "TaskHeartbeatRequest",
    "TaskReleaseRequest",
    "TaskTransitionRequest",
]
