"""Provider-free diagnostic trace harness for Knowledge Compilation runtime slices.

Child slice #1538 under parent feature #1533. The harness inspects generated
runtime artifacts and admission handoff outcomes, producing diagnostic evidence
only. It is not a durable receipt, event family, storage backend, provider call,
or promotion executor.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.knowledge_compilation.review_admission import (
    AdmissionDecision,
    AdmissionHandoff,
)
from app.knowledge_compilation.runtime_artifacts import (
    AdmissionState,
    CompilationDraft,
    CurationCandidate,
    GeneratedArtifact,
    ReorientationPacket,
    SourceRef,
    TrustVerb,
)


TraceableArtifact = CompilationDraft | CurationCandidate | ReorientationPacket


class KnowledgeCompilationTraceError(Exception):
    """Raised when trace validation finds missing evidence or authority drift."""


class ArtifactTraceRecord(BaseModel):
    """Diagnostic evidence captured for one generated runtime artifact."""

    model_config = ConfigDict(frozen=True)

    artifact_id: str
    artifact_class: str
    trace_ref: Optional[str] = None
    source_ids: tuple[str, ...] = Field(default_factory=tuple)
    canonical: bool
    trust_verb: str
    admission_state: str
    admission_receipt_ref: Optional[str] = None
    may_write: bool = False
    may_promote: bool = False
    may_authorize_action: bool = False


class AdmissionTraceRecord(BaseModel):
    """Diagnostic evidence captured for one explicit admission handoff."""

    model_config = ConfigDict(frozen=True)

    artifact_id: str
    decision: AdmissionDecision
    scope: str
    reviewer_ref: str
    actor_ref: str
    authority_basis: str
    receipt_ref: str
    trace_ref: Optional[str] = None
    source_ids: tuple[str, ...] = Field(default_factory=tuple)


class KnowledgeCompilationTraceReport(BaseModel):
    """Diagnostic eval report for the runtime-foundation flow."""

    model_config = ConfigDict(frozen=True)

    artifact_records: tuple[ArtifactTraceRecord, ...] = Field(default_factory=tuple)
    admission_records: tuple[AdmissionTraceRecord, ...] = Field(default_factory=tuple)
    promotion_path_records: tuple[str, ...] = Field(default_factory=tuple)
    provider_free: bool = True
    diagnostic_only: bool = True
    emits_events: bool = False
    durable_writes: bool = False
    is_receipt: bool = False


def _value(value: object) -> str:
    return str(getattr(value, "value", value))


def _source_ids(source_refs: tuple[SourceRef, ...]) -> tuple[str, ...]:
    ids = tuple(ref.artifact_id for ref in source_refs)
    if not ids:
        raise KnowledgeCompilationTraceError(
            "generated artifact trace requires provenance source_refs"
        )
    return ids


def _validate_artifact_posture(artifact: GeneratedArtifact) -> ArtifactTraceRecord:
    source_ids = _source_ids(artifact.source_refs)
    if artifact.canonical:
        raise KnowledgeCompilationTraceError(
            f"generated artifact {artifact.artifact_id!r} drifted to canonical posture"
        )

    trust_verb = _value(artifact.trust_verb)
    admission_state = _value(artifact.admission_state)
    if trust_verb == TrustVerb.APPLY.value:
        raise KnowledgeCompilationTraceError(
            f"generated artifact {artifact.artifact_id!r} carries direct APPLY authority"
        )
    if trust_verb != TrustVerb.SUGGEST.value and admission_state != AdmissionState.ADMITTED.value:
        raise KnowledgeCompilationTraceError(
            f"generated artifact {artifact.artifact_id!r} escalated trust without admission"
        )

    limits = artifact.authority_limits
    if limits.may_write or limits.may_promote or limits.may_authorize_action:
        raise KnowledgeCompilationTraceError(
            f"generated artifact {artifact.artifact_id!r} carries hidden authority"
        )

    if admission_state == AdmissionState.ADMITTED.value and not artifact.admission_receipt_ref:
        raise KnowledgeCompilationTraceError(
            f"generated artifact {artifact.artifact_id!r} is admitted without admission receipt"
        )

    return ArtifactTraceRecord(
        artifact_id=artifact.artifact_id,
        artifact_class=artifact.artifact_class,
        trace_ref=artifact.trace_ref,
        source_ids=source_ids,
        canonical=artifact.canonical,
        trust_verb=trust_verb,
        admission_state=admission_state,
        admission_receipt_ref=artifact.admission_receipt_ref,
        may_write=limits.may_write,
        may_promote=limits.may_promote,
        may_authorize_action=limits.may_authorize_action,
    )


def _validate_handoff(handoff: AdmissionHandoff) -> AdmissionTraceRecord:
    original = handoff.original_artifact
    admitted = handoff.admitted_artifact
    if original.source_refs != admitted.source_refs:
        raise KnowledgeCompilationTraceError(
            f"admission handoff for {original.artifact_id!r} changed provenance"
        )
    if original.trace_ref != admitted.trace_ref:
        raise KnowledgeCompilationTraceError(
            f"admission handoff for {original.artifact_id!r} changed trace identity"
        )
    if admitted.canonical:
        raise KnowledgeCompilationTraceError(
            f"admission handoff for {original.artifact_id!r} made the artifact canonical"
        )

    source_ids = _source_ids(admitted.source_refs)
    record = handoff.decision_record
    if admitted.admission_receipt_ref != record.receipt_ref:
        raise KnowledgeCompilationTraceError(
            f"admission handoff for {original.artifact_id!r} has mismatched receipt"
        )

    return AdmissionTraceRecord(
        artifact_id=admitted.artifact_id,
        decision=record.decision,
        scope=record.scope.value,
        reviewer_ref=record.reviewer_ref,
        actor_ref=record.actor_ref,
        authority_basis=record.authority_basis,
        receipt_ref=record.receipt_ref,
        trace_ref=admitted.trace_ref,
        source_ids=source_ids,
    )


def _validate_promotion_paths(
    requested_artifact_ids: tuple[str, ...],
    *,
    artifact_records: dict[str, ArtifactTraceRecord],
    admission_records: dict[str, AdmissionTraceRecord],
) -> tuple[str, ...]:
    for artifact_id in requested_artifact_ids:
        artifact_record = artifact_records.get(artifact_id)
        admission_record = admission_records.get(artifact_id)
        if artifact_record is None:
            raise KnowledgeCompilationTraceError(
                f"promotion-like path references unknown artifact {artifact_id!r}"
            )
        if (
            artifact_record.admission_state != AdmissionState.ADMITTED.value
            or not artifact_record.admission_receipt_ref
            or admission_record is None
            or admission_record.decision is not AdmissionDecision.ADMIT
            or admission_record.receipt_ref != artifact_record.admission_receipt_ref
        ):
            raise KnowledgeCompilationTraceError(
                "promotion-like path requires explicit admission receipt posture"
            )
    return requested_artifact_ids


def evaluate_knowledge_compilation_trace(
    *,
    artifacts: Sequence[TraceableArtifact],
    handoffs: Sequence[AdmissionHandoff] = (),
    promotion_like_artifact_ids: Sequence[str] = (),
) -> KnowledgeCompilationTraceReport:
    """Build a provider-free diagnostic report for generated KC runtime artifacts."""

    artifact_records = tuple(_validate_artifact_posture(artifact) for artifact in artifacts)
    admission_records = tuple(_validate_handoff(handoff) for handoff in handoffs)
    artifact_record_map = {record.artifact_id: record for record in artifact_records}
    admission_record_map = {record.artifact_id: record for record in admission_records}
    promotion_records = _validate_promotion_paths(
        tuple(promotion_like_artifact_ids),
        artifact_records=artifact_record_map,
        admission_records=admission_record_map,
    )
    return KnowledgeCompilationTraceReport(
        artifact_records=artifact_records,
        admission_records=admission_records,
        promotion_path_records=promotion_records,
    )
