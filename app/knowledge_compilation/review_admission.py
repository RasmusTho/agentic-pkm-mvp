"""Pure admission handoff for generated Knowledge Compilation artifacts.

Child slice #1537 under parent feature #1533. This module records an explicit
review/admission decision for generated runtime artifacts and can hand admitted,
memory-like material to the existing in-memory review queue. It does not promote,
store, emit, write, or mutate durable memory.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent_memory.candidate import MemoryCandidate, MemoryType
from app.agent_memory.review_queue import MemoryCandidateReviewQueue, ReviewEntry
from app.knowledge_compilation.runtime_artifacts import (
    AdmissionState,
    CompilationDraft,
    ContextAuthorityLimits,
    CurationCandidate,
    GeneratedArtifact,
    ReorientationPacket,
    SourceRef,
    TrustVerb,
)


AdmissibleArtifact = CompilationDraft | CurationCandidate | ReorientationPacket


class AdmissionHandoffError(Exception):
    """Raised when an admission handoff would bypass the explicit review boundary."""


class AdmissionDecision(str, Enum):
    ADMIT = "admit"
    REJECT = "reject"
    REVISE = "revise"


class AdmissionScope(str, Enum):
    COMPILATION_REVIEW = "compilation_review"
    CURATION_REVIEW = "curation_review"
    MEMORY_REVIEW_QUEUE = "memory_review_queue"
    ORIENTATION_ONLY = "orientation_only"


class AdmissionReceiptPosture(str, Enum):
    DURABLE_RECEIPT_REF = "durable_receipt_ref"


class AdmissionDecisionRecord(BaseModel):
    """Explicit admission decision and receipt posture for a generated artifact."""

    model_config = ConfigDict(frozen=True)

    reviewer_ref: str
    actor_ref: str
    decision: AdmissionDecision
    scope: AdmissionScope
    authority_basis: str
    receipt_ref: str
    receipt_posture: AdmissionReceiptPosture
    decision_notes: Optional[str] = None
    decided_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _require_explicit_fields(self) -> "AdmissionDecisionRecord":
        for field_name in ("reviewer_ref", "actor_ref", "authority_basis", "receipt_ref"):
            value = getattr(self, field_name)
            if not value.strip():
                raise ValueError(f"{field_name} is required for admission handoff")
        return self


class AdmissionHandoff(BaseModel):
    """Immutable handoff result preserving generated origin and decision evidence."""

    model_config = ConfigDict(frozen=True)

    original_artifact: AdmissibleArtifact
    admitted_artifact: AdmissibleArtifact
    decision_record: AdmissionDecisionRecord

    @property
    def can_promote_directly(self) -> bool:
        """Admission only opens a downstream review path; it never executes promotion."""

        return False


_DECISION_TO_ARTIFACT_STATE: dict[AdmissionDecision, AdmissionState] = {
    AdmissionDecision.ADMIT: AdmissionState.ADMITTED,
    AdmissionDecision.REJECT: AdmissionState.REJECTED,
    AdmissionDecision.REVISE: AdmissionState.REVISION_REQUESTED,
}


def _reject_direct_authority(artifact: GeneratedArtifact) -> None:
    if artifact.trust_verb is TrustVerb.APPLY:
        raise AdmissionHandoffError(
            "admission handoff cannot accept direct APPLY posture; APPLY is an execution "
            "verb, not a review/admission boundary"
        )
    limits: ContextAuthorityLimits = artifact.authority_limits
    elevated = [
        name
        for name, granted in (
            ("may_write", limits.may_write),
            ("may_promote", limits.may_promote),
            ("may_authorize_action", limits.may_authorize_action),
        )
        if granted
    ]
    if elevated:
        raise AdmissionHandoffError(
            "admission handoff cannot carry direct write/action authority: "
            + ", ".join(elevated)
        )


def record_admission_decision(
    artifact: AdmissibleArtifact,
    *,
    reviewer_ref: str,
    actor_ref: str,
    decision: AdmissionDecision,
    scope: AdmissionScope,
    authority_basis: str,
    receipt_ref: str,
    receipt_posture: AdmissionReceiptPosture,
    decision_notes: Optional[str] = None,
) -> AdmissionHandoff:
    """Record an explicit admission decision for a generated artifact.

    The returned artifact copy carries the decision posture and durable receipt
    reference, but remains non-canonical and does not gain write/action authority.
    """

    _reject_direct_authority(artifact)
    record = AdmissionDecisionRecord(
        reviewer_ref=reviewer_ref,
        actor_ref=actor_ref,
        decision=decision,
        scope=scope,
        authority_basis=authority_basis,
        receipt_ref=receipt_ref,
        receipt_posture=receipt_posture,
        decision_notes=decision_notes,
    )
    decided_artifact = artifact.model_copy(
        update={
            "admission_state": _DECISION_TO_ARTIFACT_STATE[record.decision],
            "admission_receipt_ref": record.receipt_ref,
        }
    )
    return AdmissionHandoff(
        original_artifact=artifact,
        admitted_artifact=decided_artifact,
        decision_record=record,
    )


def _source_ids(source_refs: tuple[SourceRef, ...]) -> list[str]:
    return [ref.artifact_id for ref in source_refs]


def _artifact_title(artifact: AdmissibleArtifact) -> str:
    return getattr(artifact, "title", artifact.artifact_id)


def _artifact_content(artifact: AdmissibleArtifact) -> Optional[str]:
    for field_name in ("body", "rationale", "summary"):
        value = getattr(artifact, field_name, None)
        if value:
            return value
    return None


def route_admitted_memory_to_review_queue(
    handoff: AdmissionHandoff,
    queue: MemoryCandidateReviewQueue,
    *,
    memory_type: MemoryType,
    title: Optional[str] = None,
    content: Optional[str] = None,
) -> ReviewEntry:
    """Enqueue admitted memory-like material for existing review-queue semantics.

    This is a handoff only: the returned entry is pending review, not durable memory.
    """

    record = handoff.decision_record
    if record.decision is not AdmissionDecision.ADMIT:
        raise AdmissionHandoffError("only admitted artifacts can enter the memory review queue")
    if record.scope is not AdmissionScope.MEMORY_REVIEW_QUEUE:
        raise AdmissionHandoffError(
            "memory handoff requires admission scope memory_review_queue"
        )
    artifact = handoff.admitted_artifact
    if (
        artifact.admission_state is not AdmissionState.ADMITTED
        or artifact.admission_receipt_ref != record.receipt_ref
    ):
        raise AdmissionHandoffError(
            "memory handoff requires an admitted artifact with matching receipt reference"
        )

    candidate = MemoryCandidate(
        title=title or _artifact_title(artifact),
        memory_type=memory_type,
        source_refs=_source_ids(artifact.source_refs),
        derived_from=artifact.artifact_id,
        generated_by=artifact.generated_by,
        content=content if content is not None else _artifact_content(artifact),
        inferred=artifact.inferred,
    )
    return queue.enqueue(candidate)
