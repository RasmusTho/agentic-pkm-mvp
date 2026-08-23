"""Explicit-owner retained-source adapter for the governed archival kernel.

This adapter owns admission and policy checks only.  Its injected PDM StorePort
remains the sole persistence and byte-transfer seam; locations, DSNs, paths,
and companion notes are deliberately absent from this surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
from typing import Protocol, Sequence

from app.archival.contracts import (
    AccessAuthority,
    ArchivalReceipt,
    ArtifactClass,
    ArtifactDescriptor,
    ArtifactIdentity,
    CleanupProof,
    DerivationClass,
    DoctorFinding,
    DurabilityClass,
    Generation,
    Liveness,
    LivenessState,
    OpaqueReference,
    OperationBinding,
    OperationRecord,
    OwnerAuthority,
    PolicyProfile,
    Representation,
    RepresentationRef,
    RepresentationReservation,
    TransitionStage,
    VerificationResult,
)
from app.archival.transition import FaultStage, TransitionConflict, TransitionFailure


ADAPTER_ID = "retained_source"


class RetainedSourceKind(str, Enum):
    """Only post-curation source roles are eligible for this adapter."""

    MEDIA_ORIGINAL = "media_original"
    DOCUMENT_ORIGINAL = "document_original"
    EXTERNAL_RAW = "external_raw"
    COMPANION_NOTE = "companion_note"


@dataclass(frozen=True)
class OwnerKeepDecision:
    """An opaque owner-native admission decision, never a file or note pointer."""

    reference: OpaqueReference

    def __post_init__(self) -> None:
        if not isinstance(self.reference, OpaqueReference):
            raise ValueError("owner keep decision must be a typed opaque reference")
        if self.reference.namespace != "retained-source-admission":
            raise ValueError("owner keep decision must be retained-source admission authority")


@dataclass(frozen=True)
class RetainedSourceRetirement:
    """Exact owner authorization for policy-specific physical retirement."""

    artifact: ArtifactIdentity
    generation: Generation
    reference: OpaqueReference

    def __post_init__(self) -> None:
        if not isinstance(self.artifact, ArtifactIdentity) or not isinstance(self.generation, Generation):
            raise ValueError("retirement must bind typed artifact identity and generation")
        if not isinstance(self.reference, OpaqueReference):
            raise ValueError("retirement must carry a typed opaque reference")
        if self.reference.namespace != "retained-source-retirement":
            raise ValueError("retirement must use retained-source owner policy")


@dataclass(frozen=True)
class RetainedSourceReceiptMetadata:
    """Owner-native durable receipt fields omitted from the provider-free receipt."""

    identity: ArtifactIdentity
    provenance_refs: tuple
    policy_profile: PolicyProfile
    format: str
    generation: Generation
    representation_refs: tuple[RepresentationRef, ...]


@dataclass(frozen=True)
class RetainedSourceAdmission:
    """Stable descriptor plus the explicit owner decision that admits it."""

    descriptor: ArtifactDescriptor
    source: RepresentationRef
    kind: RetainedSourceKind
    format: str
    keep_decision: OwnerKeepDecision
    restore_destination: OpaqueReference

    def __post_init__(self) -> None:
        if not isinstance(self.descriptor, ArtifactDescriptor):
            raise ValueError("retained source requires an owner-native descriptor")
        if not isinstance(self.source, RepresentationRef):
            raise ValueError("retained source representation must be a typed opaque reference")
        if not isinstance(self.kind, RetainedSourceKind):
            raise ValueError("retained source kind must be explicit")
        if self.kind in {RetainedSourceKind.EXTERNAL_RAW, RetainedSourceKind.COMPANION_NOTE}:
            raise ValueError("external_raw or companion note is not a retained-source admission")
        if not isinstance(self.keep_decision, OwnerKeepDecision):
            raise ValueError("retained source requires an explicit owner keep decision")
        if not isinstance(self.restore_destination, OpaqueReference):
            raise ValueError("restore destination must be a typed opaque reference")
        if self.restore_destination.namespace != "retained-source-destination":
            raise ValueError("restore destination must be owner-native retained-source authority")
        if not isinstance(self.format, str) or not self.format or self.format.startswith("/"):
            raise ValueError("retained source format must be a non-location format identifier")
        descriptor = self.descriptor
        if (
            descriptor.artifact_class is not ArtifactClass.SOURCE
            or descriptor.derivation is not DerivationClass.SOURCE
            or descriptor.durability is not DurabilityClass.DURABLE
            or descriptor.policy_profile is not PolicyProfile.RETAINED_SOURCE
            or descriptor.identity.owner is not OwnerAuthority.CLASS_ADAPTER
            or descriptor.identity.owner_namespace != ADAPTER_ID
            or self.source.adapter != ADAPTER_ID
        ):
            raise ValueError("retained-source admission must preserve the retained-source owner policy")
        provenance_kinds = {item.kind for item in descriptor.provenance_refs}
        if not {"content", "origin"}.issubset(provenance_kinds):
            raise ValueError("retained-source admission requires content and origin provenance")


class RetainedSourceStorePort(Protocol):
    """Narrow PDM binding; implementations own bytes, metadata, and journals."""

    contract: str
    owner_subsystem: str

    def enumerate(self, artifact: ArtifactIdentity) -> Sequence[Representation]: ...
    def resolve(self, reference: RepresentationRef) -> Representation: ...
    def authorize_read(self, artifact: ArtifactDescriptor, authority: AccessAuthority) -> ArchivalReceipt: ...
    def bind_operation(self, binding: OperationBinding) -> OperationRecord: ...
    def read_operation(self, idempotency_key: str) -> OperationRecord | None: ...
    def reserve(self, binding: OperationBinding) -> RepresentationReservation: ...
    def copy(self, binding: OperationBinding, reservation: RepresentationReservation) -> None: ...
    def verify(self, binding: OperationBinding, reservation: RepresentationReservation) -> VerificationResult: ...
    def durable_receipt(self, binding: OperationBinding, reservation: RepresentationReservation, verification: VerificationResult) -> ArchivalReceipt: ...
    def activate(self, binding: OperationBinding, reservation: RepresentationReservation, verification: VerificationResult, receipt: ArchivalReceipt) -> None: ...
    def retire(self, binding: OperationBinding, representation: Representation, receipt: ArchivalReceipt) -> None: ...
    def complete_operation(self, binding: OperationBinding, receipt: ArchivalReceipt) -> ArchivalReceipt: ...
    def restore(self, artifact: ArtifactDescriptor, authority: AccessAuthority, representation: RepresentationRef) -> ArchivalReceipt: ...
    def read_restore(self, artifact: ArtifactDescriptor, representation: RepresentationRef) -> ArchivalReceipt | None: ...
    def cleanup(self, artifact: ArtifactDescriptor) -> CleanupProof: ...
    def read_cleanup(self, artifact: ArtifactDescriptor) -> CleanupProof | None: ...
    def doctor(self) -> Sequence[DoctorFinding]: ...
    def read_bytes(self, reference: RepresentationRef) -> bytes: ...
    def copy_bytes(self, source: RepresentationRef, target: RepresentationRef) -> None: ...
    def write_restored(self, destination: OpaqueReference, payload: bytes, *, generation: Generation, format: str) -> None: ...
    def record_retained_source_receipt(self, receipt: ArchivalReceipt, metadata: RetainedSourceReceiptMetadata) -> None: ...


class RetainedSourceAdapter:
    """Policy and admission guard around an owner-native PDM StorePort binding."""

    def __init__(self, admission: RetainedSourceAdmission, store_port: RetainedSourceStorePort) -> None:
        if not isinstance(admission, RetainedSourceAdmission):
            raise ValueError("retained source requires explicit admission")
        if getattr(store_port, "contract", None) != "StorePort" or getattr(store_port, "owner_subsystem", None) != "PDM":
            raise ValueError("retained source storage must be a PDM StorePort binding")
        self.admission = admission
        self._store = store_port
        self._retirement: RetainedSourceRetirement | None = None
        self._restore_receipts: dict[tuple[ArtifactIdentity, RepresentationRef], ArchivalReceipt] = {}

    @property
    def artifact(self) -> ArtifactDescriptor:
        return self.admission.descriptor

    def authorize_retirement(self, decision: RetainedSourceRetirement) -> None:
        if decision.artifact != self.artifact.identity or decision.generation != self.artifact.generation:
            raise TransitionConflict("retained-source retirement differs from exact owner generation")
        self._retirement = decision

    def restore_to(self, artifact: ArtifactDescriptor, representation: RepresentationRef, destination: OpaqueReference) -> ArchivalReceipt:
        self._require_artifact(artifact)
        if destination != self.admission.restore_destination:
            raise TransitionConflict("restore destination differs from the owner gate")
        resolved = self.resolve(representation)
        if resolved.generation != artifact.generation:
            raise TransitionConflict("restore generation differs from owner-native representation")
        if resolved.stage is not TransitionStage.ACTIVE or resolved.liveness.state is not LivenessState.ACTIVE:
            raise TransitionConflict("restore representation is not active")
        authority = AccessAuthority(OwnerAuthority.CLASS_ADAPTER, OpaqueReference("retained-source-owner", destination.token))
        self.authorize_read(artifact, authority)
        payload = self._store.read_bytes(representation)
        self._verify_content(payload)
        self._store.write_restored(destination, payload, generation=artifact.generation, format=self.admission.format)
        receipt = ArchivalReceipt(
            OpaqueReference("retained-source-receipt", f"restore-{destination.token}"),
            artifact.identity,
            artifact.generation,
            TransitionStage.RESTORED,
            artifact.policy_profile,
            Liveness(LivenessState.ACTIVE, OpaqueReference("retained-source-liveness", f"restored-{destination.token}")),
            artifact.provenance_refs,
            (representation,),
        )
        self._restore_receipts[(artifact.identity, representation)] = receipt
        return receipt

    def enumerate(self, artifact: ArtifactIdentity) -> Sequence[Representation]:
        return self._store.enumerate(artifact) if artifact == self.artifact.identity else ()

    def resolve(self, reference: RepresentationRef) -> Representation:
        if reference.adapter != ADAPTER_ID:
            raise TransitionConflict("representation is not owned by retained-source adapter")
        return self._store.resolve(reference)

    def authorize_read(self, artifact: ArtifactDescriptor, authority: AccessAuthority) -> ArchivalReceipt:
        self._require_artifact(artifact)
        if authority.issuer is not OwnerAuthority.CLASS_ADAPTER or authority.grant_ref.namespace != "retained-source-owner":
            raise TransitionConflict("retained-source restore requires the owner gate")
        return self._store.authorize_read(artifact, authority)

    def bind_operation(self, binding: OperationBinding) -> OperationRecord:
        self._require_binding(binding)
        return self._store.bind_operation(binding)

    def read_operation(self, idempotency_key: str) -> OperationRecord | None:
        return self._store.read_operation(idempotency_key)

    def reserve(self, binding: OperationBinding) -> RepresentationReservation:
        self._require_binding(binding)
        return self._store.reserve(binding)

    def copy(self, binding: OperationBinding, reservation: RepresentationReservation) -> None:
        self._require_binding(binding)
        self._store.copy_bytes(binding.source, binding.target)
        self._store.copy(binding, reservation)

    def verify(self, binding: OperationBinding, reservation: RepresentationReservation) -> VerificationResult:
        self._require_binding(binding)
        self._verify_content(self._store.read_bytes(binding.target))
        return self._store.verify(binding, reservation)

    def durable_receipt(self, binding: OperationBinding, reservation: RepresentationReservation, verification: VerificationResult) -> ArchivalReceipt:
        self._require_binding(binding)
        receipt = self._store.durable_receipt(binding, reservation, verification)
        self._store.record_retained_source_receipt(
            receipt,
            RetainedSourceReceiptMetadata(
                self.artifact.identity,
                self.artifact.provenance_refs,
                self.artifact.policy_profile,
                self.admission.format,
                self.artifact.generation,
                receipt.representation_refs,
            ),
        )
        return receipt

    def activate(self, binding: OperationBinding, reservation: RepresentationReservation, verification: VerificationResult, receipt: ArchivalReceipt) -> None:
        self._require_binding(binding)
        self._store.activate(binding, reservation, verification, receipt)

    def retire(self, binding: OperationBinding, representation: Representation, receipt: ArchivalReceipt) -> None:
        self._require_binding(binding)
        self._store.retire(binding, representation, receipt)

    def complete_operation(self, binding: OperationBinding, receipt: ArchivalReceipt) -> ArchivalReceipt:
        self._require_binding(binding)
        return self._store.complete_operation(binding, receipt)

    def restore(self, artifact: ArtifactDescriptor, authority: AccessAuthority, representation: RepresentationRef) -> ArchivalReceipt:
        self._require_artifact(artifact)
        self.authorize_read(artifact, authority)
        return self._store.restore(artifact, authority, representation)

    def read_restore(self, artifact: ArtifactDescriptor, representation: RepresentationRef) -> ArchivalReceipt | None:
        self._require_artifact(artifact)
        return self._restore_receipts.get((artifact.identity, representation)) or self._store.read_restore(artifact, representation)

    def cleanup(self, artifact: ArtifactDescriptor) -> CleanupProof:
        self._require_artifact(artifact)
        if self._retirement is None:
            raise TransitionFailure(FaultStage.CLEANUP, "retained-source retirement is not owner-authorized")
        return self._store.cleanup(artifact)

    def read_cleanup(self, artifact: ArtifactDescriptor) -> CleanupProof | None:
        self._require_artifact(artifact)
        return self._store.read_cleanup(artifact)

    def doctor(self) -> Sequence[DoctorFinding]:
        return self._store.doctor()

    def _require_artifact(self, artifact: ArtifactDescriptor) -> None:
        if artifact != self.artifact:
            raise TransitionConflict("retained-source artifact or generation differs from owner admission")

    def _require_binding(self, binding: OperationBinding) -> None:
        if (
            binding.artifact != self.artifact.identity
            or binding.generation != self.artifact.generation
            or binding.policy is not PolicyProfile.RETAINED_SOURCE
            or binding.source != self.admission.source
            or binding.source.adapter != ADAPTER_ID
            or binding.target.adapter != ADAPTER_ID
        ):
            raise TransitionConflict("retained-source operation differs from explicit owner admission")

    def _verify_content(self, payload: bytes) -> None:
        content_refs = [ref.reference.token for ref in self.artifact.provenance_refs if ref.kind == "content" and ref.reference.namespace == "content-sha256"]
        if len(content_refs) != 1 or hashlib.sha256(payload).hexdigest() != content_refs[0]:
            raise TransitionConflict("retained-source content identity differs from owner provenance")
