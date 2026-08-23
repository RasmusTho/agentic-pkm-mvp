"""Thin GAF adapter over Heimdal's existing governed raw-media seams.

The adapter owns no persistence.  Raw identity/representations remain in
``raw_store``; archive receipts remain HAR-04 manifests; reads remain behind
``raw_read_gate``; and erasure truth remains HAR-05 tombstones and deletion
receipts.
"""

from __future__ import annotations

import hashlib
from typing import Callable, Sequence

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
    ProvenanceRef,
    Representation,
    RepresentationRef,
    RepresentationReservation,
    TransitionStage,
    VerificationResult,
)
from app.archival.transition import FaultStage, TransitionConflict, TransitionFailure
from app.heimdal import raw_liveness, raw_read_gate, raw_store
from app.heimdal.raw_store import RawRecord, RawRepresentation

ADAPTER_ID = "heimdal"
_REPRESENTATION_NAMESPACE = "heimdal-representation"
_RAW_ID_NAMESPACE = "heimdal-raw"
_RESTORE_CORRELATION_KEY = "archival_restore_correlation"


def _opaque(namespace: str, token: str) -> OpaqueReference:
    return OpaqueReference(namespace, token)


def _representation_ref(representation_id: str) -> RepresentationRef:
    return RepresentationRef(
        ADAPTER_ID,
        _opaque(_REPRESENTATION_NAMESPACE, representation_id),
    )


def _representation_id(reference: RepresentationRef) -> str:
    if reference.adapter != ADAPTER_ID or reference.opaque_id.namespace != _REPRESENTATION_NAMESPACE:
        raise TransitionConflict("representation is not owned by the Heimdal adapter")
    return reference.opaque_id.token


def describe_raw_media(record: RawRecord, *, generation: int | None = None) -> ArtifactDescriptor:
    """Map one exact owner-native raw generation without minting archive identity."""

    active = [item for item in raw_store.all_raw_representations(record.id) if item.active]
    resolved_generation = generation if generation is not None else (
        active[0].raw_generation if len(active) == 1 else 0
    )
    chain_digest = hashlib.sha256(
        "\x00".join(record.capture_chain).encode("utf-8")
    ).hexdigest()
    identity = ArtifactIdentity(
        OwnerAuthority.CLASS_ADAPTER,
        _opaque(_RAW_ID_NAMESPACE, record.id),
        owner_namespace=ADAPTER_ID,
    )
    return ArtifactDescriptor(
        identity=identity,
        artifact_class=ArtifactClass.SOURCE,
        derivation=DerivationClass.SOURCE,
        durability=DurabilityClass.DURABLE,
        owner=OwnerAuthority.CLASS_ADAPTER,
        generation=Generation(resolved_generation),
        provenance_refs=(
            ProvenanceRef("content", _opaque("heimdal-content", record.content_identity)),
            ProvenanceRef("raw", _opaque("heimdal-raw-ref", raw_read_gate.raw_ref_for(record))),
            ProvenanceRef("capture", _opaque("heimdal-capture-chain", chain_digest)),
        ),
        policy_profile=PolicyProfile.RAW_EVIDENCE,
    )


class HeimdalRawMediaAdapter:
    """Artifact-scoped projection over HAR-01..05 owner-native authority."""

    def __init__(
        self,
        record: RawRecord,
        *,
        generation: int | None = None,
        archive_action: Callable[[str, str], object] | None = None,
    ) -> None:
        self.record = record
        self.artifact = describe_raw_media(record, generation=generation)
        self._archive_action = archive_action
        self._binding: OperationBinding | None = None
        self._archive_result: object | None = None
        self._failure_reason: str | None = None
        self._restore_authority: AccessAuthority | None = None
        self._restored_storage_kind: str | None = None

    @property
    def archive_result(self) -> object | None:
        """Return the owner action's response; durable truth is read separately."""

        return self._archive_result

    @property
    def failure_reason(self) -> str | None:
        return self._failure_reason

    @property
    def restored_storage_kind(self) -> str | None:
        return self._restored_storage_kind

    @staticmethod
    def ref_for(representation: RawRepresentation | str) -> RepresentationRef:
        representation_id = representation if isinstance(representation, str) else representation.id
        return _representation_ref(representation_id)

    def enumerate(self, artifact: ArtifactIdentity) -> Sequence[Representation]:
        if artifact != self.artifact.identity:
            return ()
        rows = raw_store.all_raw_representations(self.record.id)
        if rows:
            return tuple(self._project(row) for row in rows)
        tombstone = self._tombstone()
        if tombstone is None:
            return ()
        terminal_ref = _representation_ref(f"erased-generation-{tombstone.generation}")
        return (
            Representation(
                artifact,
                terminal_ref,
                Generation(tombstone.generation),
                TransitionStage.ERASED,
                Liveness(LivenessState.ERASED, _opaque("heimdal-deletion", tombstone.deletion_receipt_id)),
            ),
        )

    def resolve(self, reference: RepresentationRef) -> Representation:
        representation_id = _representation_id(reference)
        for row in raw_store.all_raw_representations(self.record.id):
            if row.id == representation_id:
                return self._project(row)
        tombstone = self._tombstone()
        if tombstone is not None and representation_id == f"erased-generation-{tombstone.generation}":
            return self.enumerate(self.artifact.identity)[0]
        raise TransitionFailure(FaultStage.READBACK, "representation readback is unavailable")

    def authorize_read(
        self, artifact: ArtifactDescriptor, authority: AccessAuthority
    ) -> ArchivalReceipt:
        self._require_artifact(artifact)
        if authority.issuer is not OwnerAuthority.CLASS_ADAPTER or authority.grant_ref.namespace != "heimdal-reader":
            raise TransitionConflict("restore authority is not Heimdal reader authority")
        if authority.grant_ref.token not in raw_read_gate.resolve_read_allowlist():
            raise raw_read_gate.RawReadRefusedError(
                f"reader {authority.grant_ref.token!r} is not permitted to read raw evidence"
            )
        active = [item for item in raw_store.all_raw_representations(self.record.id) if item.active]
        if len(active) != 1:
            raise TransitionFailure(FaultStage.AUTHORIZATION, "active raw representation unavailable")
        self._restore_authority = authority
        return self._receipt(
            stage=TransitionStage.ACTIVE,
            refs=(self.ref_for(active[0]),),
            receipt_id=f"read-gate-{self.record.id}",
        )

    def bind_operation(self, binding: OperationBinding) -> OperationRecord:
        if binding.artifact != self.artifact.identity or binding.generation != self.artifact.generation:
            raise TransitionConflict("archive binding differs from exact Heimdal generation")
        self._binding = binding
        if self._archive_action is None:
            raise TransitionFailure(FaultStage.BINDING, "archive owner action unavailable")
        try:
            self._archive_result = self._archive_action(
                _representation_id(binding.target),
                hashlib.sha256(binding.idempotency_key.encode("utf-8")).hexdigest()[:32],
            )
        except Exception as exc:
            reason = getattr(exc, "reason", "archive_relocation_failed")
            self._failure_reason = str(reason)
            raise TransitionFailure(FaultStage.BINDING_AFTER_EFFECT, str(reason)) from exc
        loaded = self.read_operation(binding.idempotency_key)
        if loaded is None:
            raise TransitionFailure(FaultStage.READBACK, "archive owner receipt unavailable")
        return loaded

    def read_operation(self, idempotency_key: str) -> OperationRecord | None:
        binding = self._binding
        if binding is None or binding.idempotency_key != idempotency_key:
            return None
        target_id = _representation_id(binding.target)
        rows = raw_store.all_raw_representations(self.record.id)
        target = next((row for row in rows if row.id == target_id), None)
        source = next((row for row in rows if row.id == _representation_id(binding.source)), None)
        if target is None:
            return OperationRecord(binding)
        reservation = RepresentationReservation(
            binding.artifact,
            binding.target,
            binding.generation,
            _opaque("heimdal-reservation", target.id),
        )
        completed = bool(target.active and source is not None and not source.active)
        if not completed:
            return OperationRecord(binding, reservation=reservation)
        verification = VerificationResult(
            binding.target,
            binding.generation,
            True,
            _opaque("heimdal-archive-verification", target.id),
        )
        return OperationRecord(
            binding,
            reservation=reservation,
            copied=True,
            verification=verification,
            receipt=self._receipt(
                stage=TransitionStage.RETIRED,
                refs=(binding.source, binding.target),
                receipt_id=f"archive-{target.id}",
            ),
            activated=True,
            retired=True,
            completed=True,
        )

    def reserve(self, binding: OperationBinding) -> RepresentationReservation:
        raise TransitionFailure(FaultStage.RESERVATION, "owner archive transition is atomic")

    def copy(self, binding: OperationBinding, reservation: RepresentationReservation) -> None:
        raise TransitionFailure(FaultStage.BYTES, "owner archive transition is atomic")

    def verify(self, binding: OperationBinding, reservation: RepresentationReservation) -> VerificationResult:
        raise TransitionFailure(FaultStage.VERIFICATION, "owner archive transition is atomic")

    def durable_receipt(
        self,
        binding: OperationBinding,
        reservation: RepresentationReservation,
        verification: VerificationResult,
    ) -> ArchivalReceipt:
        raise TransitionFailure(FaultStage.RECEIPT, "owner archive transition is atomic")

    def activate(
        self,
        binding: OperationBinding,
        reservation: RepresentationReservation,
        verification: VerificationResult,
        receipt: ArchivalReceipt,
    ) -> None:
        raise TransitionFailure(FaultStage.ACTIVATION, "owner archive transition is atomic")

    def retire(self, binding: OperationBinding, representation: Representation, receipt: ArchivalReceipt) -> None:
        raise TransitionFailure(FaultStage.RETIREMENT, "owner archive transition is atomic")

    def complete_operation(self, binding: OperationBinding, receipt: ArchivalReceipt) -> ArchivalReceipt:
        raise TransitionFailure(FaultStage.COMPLETION, "owner archive transition is atomic")

    def restore(
        self,
        artifact: ArtifactDescriptor,
        authority: AccessAuthority,
        representation: RepresentationRef,
    ) -> ArchivalReceipt:
        self._require_artifact(artifact)
        if authority != self._restore_authority:
            raise TransitionConflict("restore authority differs from the authorized gate")
        correlation = hashlib.sha256(
            f"{self.record.id}:{artifact.generation.value}:{_representation_id(representation)}:{authority.grant_ref.token}".encode()
        ).hexdigest()
        restored = raw_read_gate.read_raw_record(
            raw_read_gate.raw_ref_for(self.record),
            reader=authority.grant_ref.token,
            purpose="heimdal_archive_restore_drill",
            payload={_RESTORE_CORRELATION_KEY: correlation},
        )
        self._restored_storage_kind = restored.storage_kind
        if restored.representation_id != _representation_id(representation):
            raise TransitionConflict("restore readback selected a different representation")
        if raw_store.compute_raw_content_identity(restored.plaintext) != self.record.content_identity:
            raise TransitionConflict("restore identity differs from owner-native identity")
        return self._receipt(
            stage=TransitionStage.RESTORED,
            refs=(representation,),
            receipt_id=restored.receipt.id,
        )

    def read_restore(
        self, artifact: ArtifactDescriptor, representation: RepresentationRef
    ) -> ArchivalReceipt | None:
        self._require_artifact(artifact)
        matches = [
            receipt
            for receipt in raw_read_gate.all_raw_read_receipts()
            if receipt.raw_ref == raw_read_gate.raw_ref_for(self.record)
            and receipt.purpose == "heimdal_archive_restore_drill"
            and receipt.payload.get(_RESTORE_CORRELATION_KEY)
        ]
        if not matches:
            return None
        return self._receipt(
            stage=TransitionStage.RESTORED,
            refs=(representation,),
            receipt_id=matches[-1].id,
        )

    def cleanup(self, artifact: ArtifactDescriptor) -> CleanupProof:
        proof = self.read_cleanup(artifact)
        if proof is None:
            raise TransitionFailure(FaultStage.CLEANUP, "HAR-05 all-copy cleanup remains pending")
        return proof

    def read_cleanup(self, artifact: ArtifactDescriptor) -> CleanupProof | None:
        self._require_artifact(artifact)
        tombstone = self._tombstone()
        if tombstone is None or tombstone.generation != artifact.generation.value:
            return None
        receipt = next(
            (item for item in raw_liveness.all_deletion_receipts() if item.id == tombstone.deletion_receipt_id),
            None,
        )
        if receipt is None or raw_store.all_raw_representations(self.record.id):
            return None
        return CleanupProof(
            artifact.identity,
            artifact.generation,
            artifact.policy_profile,
            (_representation_ref(f"erased-generation-{tombstone.generation}"),),
            True,
            _opaque("heimdal-deletion", receipt.id),
        )

    def doctor(self) -> Sequence[DoctorFinding]:
        return ()

    def _project(self, row: RawRepresentation) -> Representation:
        stage = TransitionStage.ACTIVE if row.active else TransitionStage.RETIRED
        state = LivenessState.ACTIVE if row.active else LivenessState.STALE
        return Representation(
            self.artifact.identity,
            self.ref_for(row),
            Generation(row.raw_generation),
            stage,
            Liveness(state, _opaque("heimdal-raw-state", row.id)),
        )

    def _receipt(
        self,
        *,
        stage: TransitionStage,
        refs: tuple[RepresentationRef, ...],
        receipt_id: str,
    ) -> ArchivalReceipt:
        return ArchivalReceipt(
            _opaque("heimdal-archival-receipt", receipt_id),
            self.artifact.identity,
            self.artifact.generation,
            stage,
            self.artifact.policy_profile,
            Liveness(LivenessState.ACTIVE, _opaque("heimdal-raw-state", receipt_id)),
            self.artifact.provenance_refs,
            refs,
        )

    def _tombstone(self) -> raw_liveness.RawDeletionTombstone | None:
        return next(
            (item for item in raw_liveness.all_deletion_tombstones() if item.record_id == self.record.id),
            None,
        )

    def _require_artifact(self, artifact: ArtifactDescriptor) -> None:
        if artifact != self.artifact:
            raise TransitionConflict("artifact differs from exact Heimdal identity/generation")


__all__ = ["ADAPTER_ID", "HeimdalRawMediaAdapter", "describe_raw_media"]
