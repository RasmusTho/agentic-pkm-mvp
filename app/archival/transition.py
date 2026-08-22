"""Receipt-first, provider-neutral archival transition ordering."""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Protocol

from app.archival.contracts import (
    AccessAuthority, ArtifactDescriptor, ArtifactIdentity, ArchivalReceipt,
    Generation, Liveness, LivenessState, OpaqueReference, PolicyProfile,
    Representation, RepresentationRef, RepresentationReservation, TransitionStage,
    VerificationResult,
)


class FaultStage(str, Enum):
    RESERVATION = "reservation"
    BYTES = "bytes"
    VERIFICATION = "verification"
    RECEIPT = "receipt"
    ACTIVATION = "activation"
    ACTIVATION_AFTER_EFFECT = "activation_after_effect"
    RETIREMENT = "retirement"
    COMPLETION = "completion"
    CLEANUP = "cleanup"


class TransitionFailure(RuntimeError):
    def __init__(self, stage: FaultStage, message: str) -> None:
        super().__init__(message)
        self.stage = stage


@dataclass(frozen=True)
class OperationRecord:
    idempotency_key: str
    artifact: ArtifactIdentity
    generation: Generation
    policy: PolicyProfile
    source: RepresentationRef
    target: RepresentationRef
    reservation: RepresentationReservation
    receipt: ArchivalReceipt
    activated: bool = False
    retired: bool = False


class TransitionAdapter(Protocol):
    """Owner-native durability and access seams; the kernel owns no state."""
    def source(self, reference: RepresentationRef) -> Representation: ...
    def reserve(self, artifact: ArtifactDescriptor, target: RepresentationRef) -> RepresentationReservation: ...
    def persist(self, reservation: RepresentationReservation) -> None: ...
    def verify(self, reservation: RepresentationReservation) -> VerificationResult: ...
    def durable_receipt(self, key: str, source: RepresentationRef, reservation: RepresentationReservation, verification: VerificationResult) -> ArchivalReceipt: ...
    def activate(self, key: str, reservation: RepresentationReservation, receipt: ArchivalReceipt) -> None: ...
    def retire(self, source: Representation, receipt: ArchivalReceipt) -> None: ...
    def authorize_read(self, artifact: ArtifactIdentity, authority: AccessAuthority) -> ArchivalReceipt: ...
    def restore(self, artifact: ArtifactIdentity, authority: AccessAuthority, representation: RepresentationRef) -> ArchivalReceipt: ...
    def cleanup(self, artifact: ArtifactIdentity, generation: Generation, policy: PolicyProfile) -> OpaqueReference: ...
    def find_operation(self, key: str) -> OperationRecord | None: ...
    def complete(self, key: str, receipt: ArchivalReceipt) -> None: ...


@dataclass(frozen=True)
class TransitionResult:
    stage: TransitionStage
    liveness: Liveness
    receipt: ArchivalReceipt | None = None

    @property
    def terminal(self) -> bool:
        return self.liveness.is_terminal or self.stage in {TransitionStage.RETIRED, TransitionStage.RESTORED}


def _evidence(token: str) -> OpaqueReference:
    return OpaqueReference("archival-kernel", token)


class ArchivalTransitionKernel:
    """Resume durable operation records; never infer completion from process state."""
    def __init__(self, adapter: TransitionAdapter) -> None:
        self._adapter = adapter

    def transition(self, artifact: ArtifactDescriptor, source: RepresentationRef, target: RepresentationRef, idempotency_key: str) -> TransitionResult:
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise ValueError("idempotency_key is required")
        existing = self._adapter.find_operation(idempotency_key)
        if existing is not None:
            if (existing.artifact != artifact.identity or existing.generation != artifact.generation
                    or existing.policy is not artifact.policy_profile or existing.source != source
                    or existing.target != target):
                return self._refused("idempotency-binding-conflict")
            if existing.retired:
                return TransitionResult(existing.receipt.stage, existing.receipt.liveness, existing.receipt)
            reservation = existing.reservation
            current_source = self._adapter.source(source)
            if current_source.artifact != artifact.identity or current_source.generation != artifact.generation:
                return self._refused("stale-generation-or-source-binding")
            if not existing.activated:
                self._adapter.activate(idempotency_key, reservation, existing.receipt)
            if current_source.stage is not TransitionStage.RETIRED:
                self._adapter.retire(current_source, existing.receipt)
            self._adapter.complete(idempotency_key, existing.receipt)
            return TransitionResult(TransitionStage.RETIRED, existing.receipt.liveness, existing.receipt)
        source_rep = self._adapter.source(source)
        if source_rep.artifact != artifact.identity or source_rep.generation != artifact.generation:
            return self._refused("stale-generation-or-source-binding")
        try:
            reservation = self._adapter.reserve(artifact, target)
            self._adapter.persist(reservation)
            verification = self._adapter.verify(reservation)
            if not verification.verified or verification.generation != artifact.generation:
                return self._refused("destination-verification-failed")
            receipt = self._adapter.durable_receipt(idempotency_key, source, reservation, verification)
            self._adapter.activate(idempotency_key, reservation, receipt)
            self._adapter.retire(source_rep, receipt)
            self._adapter.complete(idempotency_key, receipt)
            return TransitionResult(TransitionStage.RETIRED, receipt.liveness, receipt)
        except TransitionFailure as failure:
            return TransitionResult(
                TransitionStage.REFUSED if failure.stage is FaultStage.RESERVATION else TransitionStage.RESERVED,
                Liveness(LivenessState.TRANSITION_PENDING, _evidence(f"pending-{idempotency_key}")),
            )

    archive = transition

    def restore(self, artifact: ArtifactDescriptor, authority: AccessAuthority, representation: RepresentationRef) -> TransitionResult:
        gate = self._adapter.authorize_read(artifact.identity, authority)
        if representation not in gate.representation_refs:
            return TransitionResult(TransitionStage.CONFLICT, Liveness(LivenessState.CONFLICT, _evidence("restore-representation-mismatch")), gate)
        try:
            receipt = self._adapter.restore(artifact.identity, authority, representation)
        except TransitionFailure:
            return TransitionResult(TransitionStage.RESTORE_PENDING, Liveness(LivenessState.RESTORE_PENDING, _evidence("restore-pending")), gate)
        if receipt.artifact != artifact.identity or receipt.generation != artifact.generation or representation not in receipt.representation_refs:
            return TransitionResult(TransitionStage.CONFLICT, Liveness(LivenessState.CONFLICT, _evidence("restore-receipt-mismatch")), receipt)
        return TransitionResult(TransitionStage.RESTORED, receipt.liveness, receipt)

    def cleanup(self, artifact: ArtifactDescriptor) -> TransitionResult:
        try:
            evidence = self._adapter.cleanup(artifact.identity, artifact.generation, artifact.policy_profile)
        except TransitionFailure:
            return TransitionResult(TransitionStage.ERASE_PENDING, Liveness(LivenessState.ERASURE_PENDING, _evidence("erasure-pending")))
        return TransitionResult(TransitionStage.ERASED, Liveness(LivenessState.ERASED, evidence))

    @staticmethod
    def _refused(reason: str) -> TransitionResult:
        return TransitionResult(TransitionStage.REFUSED, Liveness(LivenessState.REFUSED, _evidence(reason)))


class DurableFakeAdapter:
    """Test-only durable double. Production adapters are intentionally unwired."""
    def __init__(self) -> None:
        self.representations: dict[RepresentationRef, Representation] = {}
        self.reservations: dict[OpaqueReference, RepresentationReservation] = {}
        self.operations: dict[str, OperationRecord] = {}
        self._policies: dict[RepresentationRef, PolicyProfile] = {}
        self.fault: FaultStage | None = None
        self.source_retired = False
        self.access_gate_called = False

    def register_source(self, representation: Representation) -> None:
        self.representations[representation.ref] = representation

    def fail_once(self, stage: FaultStage) -> None:
        self.fault = stage

    def _fault(self, stage: FaultStage) -> None:
        if self.fault is stage:
            self.fault = None
            raise TransitionFailure(stage, f"injected failure at {stage.value}")

    def source(self, reference: RepresentationRef) -> Representation:
        return self.representations[reference]

    def reserve(self, artifact: ArtifactDescriptor, target: RepresentationRef) -> RepresentationReservation:
        self._fault(FaultStage.RESERVATION)
        existing = self.representations.get(target)
        if existing is not None and (existing.artifact != artifact.identity or existing.generation != artifact.generation):
            raise TransitionFailure(FaultStage.RESERVATION, "destination binding is stale")
        old_policy = self._policies.get(target)
        if old_policy is not None and old_policy is not artifact.policy_profile:
            raise TransitionFailure(FaultStage.RESERVATION, "destination policy binding changed")
        self._policies[target] = artifact.policy_profile
        reservation = RepresentationReservation(artifact.identity, target, artifact.generation, OpaqueReference("reservation", f"r-{len(self.reservations)+1}"))
        self.reservations[reservation.reservation_ref] = reservation
        return reservation

    def persist(self, reservation: RepresentationReservation) -> None:
        self._fault(FaultStage.BYTES)
        self.representations[reservation.target] = Representation(reservation.artifact, reservation.target, reservation.generation, TransitionStage.VERIFIED, Liveness(LivenessState.TRANSITION_PENDING, _evidence(reservation.reservation_ref.token)))

    def verify(self, reservation: RepresentationReservation) -> VerificationResult:
        self._fault(FaultStage.VERIFICATION)
        representation = self.representations.get(reservation.target)
        if representation is None or representation.generation != reservation.generation:
            raise TransitionFailure(FaultStage.VERIFICATION, "destination is not durable")
        return VerificationResult(reservation.target, reservation.generation, True, _evidence(f"verified-{reservation.reservation_ref.token}"))

    def durable_receipt(self, key: str, source: RepresentationRef, reservation: RepresentationReservation, verification: VerificationResult) -> ArchivalReceipt:
        self._fault(FaultStage.RECEIPT)
        receipt = ArchivalReceipt(OpaqueReference("receipt", reservation.reservation_ref.token), reservation.artifact, reservation.generation, TransitionStage.VERIFIED, self._policies[reservation.target], Liveness(LivenessState.ACTIVE, _evidence(f"receipt-{reservation.reservation_ref.token}")), (), (reservation.target,))
        self.operations[key] = OperationRecord(key, reservation.artifact, reservation.generation, self._policies[reservation.target], source, reservation.target, reservation, receipt)
        return receipt

    def activate(self, key: str, reservation: RepresentationReservation, receipt: ArchivalReceipt) -> None:
        self._fault(FaultStage.ACTIVATION)
        representation = self.representations[reservation.target]
        self.representations[reservation.target] = replace(representation, stage=TransitionStage.ACTIVE, liveness=receipt.liveness)
        if self.fault is FaultStage.ACTIVATION_AFTER_EFFECT:
            self.fault = None
            raise TransitionFailure(FaultStage.ACTIVATION_AFTER_EFFECT, "activation committed before progress receipt")
        operation = self.operations.get(key)
        if operation is not None:
            self.operations[key] = replace(operation, activated=True)

    def retire(self, source: Representation, receipt: ArchivalReceipt) -> None:
        self._fault(FaultStage.RETIREMENT)
        self.source_retired = True
        self.representations[source.ref] = replace(source, stage=TransitionStage.RETIRED, liveness=receipt.liveness)

    def find_operation(self, key: str) -> OperationRecord | None:
        return self.operations.get(key)

    def complete(self, key: str, receipt: ArchivalReceipt) -> None:
        self._fault(FaultStage.COMPLETION)
        operation = self.operations[key]
        self.operations[key] = replace(operation, receipt=replace(receipt, stage=TransitionStage.RETIRED), activated=True, retired=True)

    def authorize_read(self, artifact: ArtifactIdentity, authority: AccessAuthority) -> ArchivalReceipt:
        self.access_gate_called = True
        refs = tuple(ref for ref, rep in self.representations.items() if rep.artifact == artifact and rep.stage is not TransitionStage.RETIRED)
        generation = next((rep.generation for rep in self.representations.values() if rep.artifact == artifact), Generation(0))
        return ArchivalReceipt(OpaqueReference("access-receipt", "read-1"), artifact, generation, TransitionStage.ACTIVE, PolicyProfile.HKA_RECOVERY, Liveness(LivenessState.ACTIVE, _evidence("access-granted")), (), refs)

    def restore(self, artifact: ArtifactIdentity, authority: AccessAuthority, representation: RepresentationRef) -> ArchivalReceipt:
        self._fault(FaultStage.VERIFICATION)
        if representation not in self.representations:
            raise TransitionFailure(FaultStage.VERIFICATION, "exact representation is unavailable")
        return ArchivalReceipt(OpaqueReference("restore-receipt", representation.opaque_id.token), artifact, self.representations[representation].generation, TransitionStage.RESTORED, PolicyProfile.HKA_RECOVERY, Liveness(LivenessState.ACTIVE, _evidence("restored")), (), (representation,))

    def cleanup(self, artifact: ArtifactIdentity, generation: Generation, policy: PolicyProfile) -> OpaqueReference:
        self._fault(FaultStage.CLEANUP)
        return _evidence("cleanup-proven")
