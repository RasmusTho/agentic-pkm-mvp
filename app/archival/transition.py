"""Owner-bound, provider-neutral archival transition ordering."""

from __future__ import annotations

from dataclasses import replace
from enum import Enum
from threading import RLock

from app.archival.contracts import (
    AccessAuthority,
    ArchivalAdapter,
    ArchivalReceipt,
    ArtifactDescriptor,
    ArtifactIdentity,
    CleanupProof,
    DoctorFinding,
    Generation,
    Liveness,
    LivenessState,
    OpaqueReference,
    OperationBinding,
    OperationRecord,
    PolicyProfile,
    Representation,
    RepresentationRef,
    RepresentationReservation,
    TransitionStage,
    VerificationResult,
)


class FaultStage(str, Enum):
    AUTHORIZATION = "authorization"
    BINDING = "binding"
    BINDING_AFTER_EFFECT = "binding_after_effect"
    RESERVATION = "reservation"
    RESERVATION_AFTER_EFFECT = "reservation_after_effect"
    BYTES = "bytes"
    BYTES_AFTER_EFFECT = "bytes_after_effect"
    VERIFICATION = "verification"
    VERIFICATION_AFTER_EFFECT = "verification_after_effect"
    RECEIPT = "receipt"
    RECEIPT_AFTER_EFFECT = "receipt_after_effect"
    ACTIVATION = "activation"
    ACTIVATION_AFTER_EFFECT = "activation_after_effect"
    RETIREMENT = "retirement"
    RETIREMENT_AFTER_EFFECT = "retirement_after_effect"
    COMPLETION = "completion"
    COMPLETION_AFTER_EFFECT = "completion_after_effect"
    READBACK = "readback"
    RESTORE = "restore"
    RESTORE_AFTER_EFFECT = "restore_after_effect"
    CLEANUP = "cleanup"
    CLEANUP_AFTER_EFFECT = "cleanup_after_effect"


class TransitionFailure(RuntimeError):
    def __init__(self, stage: FaultStage, message: str) -> None:
        super().__init__(message)
        self.stage = stage


class TransitionConflict(RuntimeError):
    """The owner journal or proof contradicts the requested immutable binding."""


class TransitionResult:
    def __init__(
        self,
        stage: TransitionStage,
        liveness: Liveness,
        receipt: ArchivalReceipt | None = None,
    ) -> None:
        self.stage = stage
        self.liveness = liveness
        self.receipt = receipt

    @property
    def terminal(self) -> bool:
        return self.liveness.is_terminal or self.stage in {
            TransitionStage.RETIRED,
            TransitionStage.RESTORED,
        }


def _evidence(token: str) -> OpaqueReference:
    return OpaqueReference("archival-kernel", token)


class ArchivalTransitionKernel:
    """Orchestrate only from exact owner-native journal and representation readback."""

    def __init__(self, adapter: ArchivalAdapter) -> None:
        self._adapter = adapter

    def transition(
        self,
        artifact: ArtifactDescriptor,
        source: RepresentationRef,
        target: RepresentationRef,
        idempotency_key: str,
    ) -> TransitionResult:
        binding = OperationBinding(
            idempotency_key,
            artifact.identity,
            artifact.generation,
            artifact.policy_profile,
            source,
            target,
        )
        try:
            bound = self._adapter.bind_operation(binding)
            self._validate_operation(binding, bound)
            operation = self._read_operation(binding)
            return self._resume(artifact, binding, operation)
        except TransitionConflict:
            return self._conflict("operation-binding-or-proof-conflict")
        except TransitionFailure:
            return self._uncertain(binding)

    archive = transition

    def _resume(
        self,
        artifact: ArtifactDescriptor,
        binding: OperationBinding,
        operation: OperationRecord,
    ) -> TransitionResult:
        del artifact
        try:
            if operation.completed:
                return self._completed(binding, operation)

            source_representation = self._resolve_exact(
                binding.source,
                binding.artifact,
                binding.generation,
            )
            if source_representation.stage is TransitionStage.RETIRED and not operation.retired:
                raise TransitionFailure(
                    FaultStage.READBACK,
                    "source retirement is not reflected in the owner operation journal",
                )

            if operation.reservation is None:
                reservation = self._adapter.reserve(binding)
                self._validate_reservation(binding, reservation)
                operation = self._read_operation(binding)
            reservation = self._require_reservation(binding, operation)

            if not operation.copied:
                self._adapter.copy(binding, reservation)
                operation = self._read_operation(binding)
            copied_target = self._resolve_exact(
                binding.target, binding.artifact, binding.generation
            )
            expected_target_stage = (
                TransitionStage.ACTIVE
                if operation.activated
                else TransitionStage.VERIFIED
                if operation.verification is not None
                else TransitionStage.RESERVED
            )
            if not operation.copied or copied_target.stage is not expected_target_stage:
                raise TransitionFailure(
                    FaultStage.READBACK,
                    "destination copy state lacks exact owner-native readback",
                )

            if operation.verification is None:
                verification = self._adapter.verify(binding, reservation)
                self._validate_verification(binding, reservation, verification)
                operation = self._read_operation(binding)
            verification = self._require_verification(binding, reservation, operation)
            verified_target = self._resolve_exact(
                binding.target, binding.artifact, binding.generation
            )
            if not operation.activated and verified_target.stage is not TransitionStage.VERIFIED:
                raise TransitionFailure(
                    FaultStage.READBACK,
                    "destination verification lacks exact owner-native readback",
                )

            if operation.receipt is None:
                receipt = self._adapter.durable_receipt(
                    binding, reservation, verification
                )
                self._validate_receipt(binding, receipt, completed=False)
                operation = self._read_operation(binding)
            receipt = self._require_receipt(binding, operation, completed=False)

            if not operation.activated:
                self._adapter.activate(
                    binding, reservation, verification, receipt
                )
                operation = self._read_operation(binding)
            if not operation.activated:
                raise TransitionFailure(
                    FaultStage.READBACK,
                    "activation is absent from the owner operation journal",
                )
            active_target = self._resolve_exact(
                binding.target, binding.artifact, binding.generation
            )
            if active_target.stage is not TransitionStage.ACTIVE:
                raise TransitionFailure(
                    FaultStage.READBACK,
                    "destination activation lacks exact owner-native readback",
                )

            if not operation.retired:
                source_representation = self._resolve_exact(
                    binding.source, binding.artifact, binding.generation
                )
                self._adapter.retire(binding, source_representation, receipt)
                operation = self._read_operation(binding)
            if not operation.retired:
                raise TransitionFailure(
                    FaultStage.READBACK,
                    "retirement is absent from the owner operation journal",
                )
            retired_source = self._resolve_exact(
                binding.source, binding.artifact, binding.generation
            )
            if retired_source.stage is not TransitionStage.RETIRED:
                raise TransitionFailure(
                    FaultStage.READBACK,
                    "source retirement lacks exact owner-native readback",
                )

            if not operation.completed:
                completed = self._adapter.complete_operation(binding, receipt)
                self._validate_receipt(binding, completed, completed=True)
                operation = self._read_operation(binding)
            return self._completed(binding, operation)
        except TransitionConflict:
            return self._conflict("operation-binding-or-proof-conflict")
        except TransitionFailure:
            return self._uncertain(binding)

    def restore(
        self,
        artifact: ArtifactDescriptor,
        authority: AccessAuthority,
        representation: RepresentationRef,
    ) -> TransitionResult:
        try:
            gate = self._adapter.authorize_read(artifact, authority)
        except TransitionFailure:
            return TransitionResult(
                TransitionStage.RESTORE_PENDING,
                Liveness(
                    LivenessState.UNAVAILABLE,
                    _evidence("restore-authorization-unavailable"),
                ),
            )
        if (
            gate.artifact != artifact.identity
            or gate.generation != artifact.generation
            or representation not in gate.representation_refs
        ):
            return self._conflict("restore-authorization-binding-mismatch", gate)
        try:
            receipt = self._adapter.restore(artifact, authority, representation)
            self._validate_restore_receipt(artifact, representation, receipt)
            loaded = self._adapter.read_restore(artifact, representation)
            if loaded is None or loaded != receipt:
                raise TransitionFailure(
                    FaultStage.READBACK, "restore receipt readback is unavailable"
                )
            self._validate_restore_receipt(artifact, representation, loaded)
            return TransitionResult(TransitionStage.RESTORED, loaded.liveness, loaded)
        except TransitionConflict:
            return self._conflict("restore-receipt-mismatch")
        except TransitionFailure:
            try:
                loaded = self._adapter.read_restore(artifact, representation)
            except TransitionFailure:
                return self._unavailable("restore-readback-unavailable")
            if loaded is None:
                return TransitionResult(
                    TransitionStage.RESTORE_PENDING,
                    Liveness(
                        LivenessState.RESTORE_PENDING,
                        _evidence("restore-pending"),
                    ),
                )
            try:
                self._validate_restore_receipt(artifact, representation, loaded)
            except TransitionConflict:
                return self._conflict("restore-readback-mismatch", loaded)
            return TransitionResult(TransitionStage.RESTORED, loaded.liveness, loaded)

    def cleanup(self, artifact: ArtifactDescriptor) -> TransitionResult:
        try:
            loaded = self._adapter.read_cleanup(artifact)
        except TransitionFailure:
            return self._unavailable("cleanup-readback-unavailable")
        if loaded is not None:
            try:
                self._validate_cleanup_proof(artifact, None, loaded)
            except TransitionConflict:
                return self._cleanup_pending("cleanup-readback-mismatch")
            return TransitionResult(
                TransitionStage.ERASED,
                Liveness(LivenessState.ERASED, loaded.evidence_ref),
            )

        try:
            expected = self._cleanup_scope(artifact)
        except TransitionFailure:
            return self._unavailable("cleanup-scope-unavailable")

        try:
            proof = self._adapter.cleanup(artifact)
            self._validate_cleanup_proof(artifact, expected, proof)
            loaded = self._adapter.read_cleanup(artifact)
            if loaded is None or loaded != proof:
                raise TransitionFailure(
                    FaultStage.READBACK, "cleanup proof readback is unavailable"
                )
            self._validate_cleanup_proof(artifact, expected, loaded)
            return TransitionResult(
                TransitionStage.ERASED,
                Liveness(LivenessState.ERASED, loaded.evidence_ref),
            )
        except TransitionConflict:
            return self._cleanup_pending("cleanup-proof-mismatch")
        except TransitionFailure:
            try:
                loaded = self._adapter.read_cleanup(artifact)
            except TransitionFailure:
                return self._unavailable("cleanup-readback-unavailable")
            if loaded is None:
                return self._cleanup_pending("erasure-pending")
            try:
                self._validate_cleanup_proof(artifact, expected, loaded)
            except TransitionConflict:
                return self._cleanup_pending("cleanup-readback-mismatch")
            return TransitionResult(
                TransitionStage.ERASED,
                Liveness(LivenessState.ERASED, loaded.evidence_ref),
            )

    def _read_operation(self, binding: OperationBinding) -> OperationRecord:
        operation = self._adapter.read_operation(binding.idempotency_key)
        if operation is None:
            raise TransitionFailure(
                FaultStage.READBACK, "bound operation is unavailable"
            )
        self._validate_operation(binding, operation)
        return operation

    @staticmethod
    def _validate_operation(
        binding: OperationBinding, operation: OperationRecord
    ) -> None:
        if operation.binding != binding:
            raise TransitionConflict("loaded operation binding differs")
        if operation.reservation is not None:
            ArchivalTransitionKernel._validate_reservation(
                binding, operation.reservation
            )
        if operation.verification is not None:
            if operation.reservation is None:
                raise TransitionConflict("verification has no reservation")
            ArchivalTransitionKernel._validate_verification(
                binding, operation.reservation, operation.verification
            )
        if operation.receipt is not None:
            ArchivalTransitionKernel._validate_receipt(
                binding, operation.receipt, completed=operation.completed
            )
        if operation.copied and operation.reservation is None:
            raise TransitionConflict("copied operation has no reservation")
        if operation.verification is not None and not operation.copied:
            raise TransitionConflict("verified operation has no durable copy")
        if operation.receipt is not None and operation.verification is None:
            raise TransitionConflict("receipted operation has no verification")
        if operation.activated and operation.receipt is None:
            raise TransitionConflict("activated operation has no receipt")
        if operation.retired and not operation.activated:
            raise TransitionConflict("retired operation was not activated")
        if operation.completed and not (
            operation.copied
            and operation.verification is not None
            and operation.receipt is not None
            and operation.activated
            and operation.retired
        ):
            raise TransitionConflict("completed operation has incomplete owner state")

    @staticmethod
    def _validate_reservation(
        binding: OperationBinding, reservation: RepresentationReservation
    ) -> None:
        if (
            reservation.artifact != binding.artifact
            or reservation.generation != binding.generation
            or reservation.target != binding.target
        ):
            raise TransitionConflict("reservation binding differs")

    @staticmethod
    def _validate_verification(
        binding: OperationBinding,
        reservation: RepresentationReservation,
        verification: VerificationResult,
    ) -> None:
        ArchivalTransitionKernel._validate_reservation(binding, reservation)
        if (
            not verification.verified
            or verification.representation != binding.target
            or verification.representation != reservation.target
            or verification.generation != binding.generation
            or verification.generation != reservation.generation
        ):
            raise TransitionConflict("verification binding differs")

    @staticmethod
    def _validate_receipt(
        binding: OperationBinding,
        receipt: ArchivalReceipt,
        *,
        completed: bool,
    ) -> None:
        expected_stage = (
            TransitionStage.RETIRED if completed else TransitionStage.VERIFIED
        )
        if (
            receipt.artifact != binding.artifact
            or receipt.generation != binding.generation
            or receipt.policy_profile is not binding.policy
            or receipt.stage is not expected_stage
            or receipt.representation_refs != (binding.source, binding.target)
        ):
            raise TransitionConflict("receipt binding differs")

    @staticmethod
    def _require_reservation(
        binding: OperationBinding, operation: OperationRecord
    ) -> RepresentationReservation:
        if operation.reservation is None:
            raise TransitionFailure(
                FaultStage.READBACK, "reservation readback is unavailable"
            )
        ArchivalTransitionKernel._validate_reservation(
            binding, operation.reservation
        )
        return operation.reservation

    @staticmethod
    def _require_verification(
        binding: OperationBinding,
        reservation: RepresentationReservation,
        operation: OperationRecord,
    ) -> VerificationResult:
        if operation.verification is None:
            raise TransitionFailure(
                FaultStage.READBACK, "verification readback is unavailable"
            )
        ArchivalTransitionKernel._validate_verification(
            binding, reservation, operation.verification
        )
        return operation.verification

    @staticmethod
    def _require_receipt(
        binding: OperationBinding,
        operation: OperationRecord,
        *,
        completed: bool,
    ) -> ArchivalReceipt:
        if operation.receipt is None:
            raise TransitionFailure(
                FaultStage.READBACK, "receipt readback is unavailable"
            )
        ArchivalTransitionKernel._validate_receipt(
            binding, operation.receipt, completed=completed
        )
        return operation.receipt

    def _resolve_exact(
        self,
        reference: RepresentationRef,
        artifact: ArtifactIdentity,
        generation: Generation,
    ) -> Representation:
        representation = self._adapter.resolve(reference)
        if (
            representation.ref != reference
            or representation.artifact != artifact
            or representation.generation != generation
        ):
            raise TransitionConflict("representation readback binding differs")
        return representation

    @staticmethod
    def _validate_restore_receipt(
        artifact: ArtifactDescriptor,
        representation: RepresentationRef,
        receipt: ArchivalReceipt,
    ) -> None:
        if (
            receipt.artifact != artifact.identity
            or receipt.generation != artifact.generation
            or receipt.policy_profile is not artifact.policy_profile
            or receipt.stage is not TransitionStage.RESTORED
            or receipt.representation_refs != (representation,)
        ):
            raise TransitionConflict("restore receipt binding differs")

    def _cleanup_scope(
        self, artifact: ArtifactDescriptor
    ) -> tuple[RepresentationRef, ...]:
        representations = self._adapter.enumerate(artifact.identity)
        exact = tuple(
            representation.ref
            for representation in representations
            if representation.artifact == artifact.identity
            and representation.generation == artifact.generation
        )
        if not exact:
            raise TransitionFailure(
                FaultStage.READBACK, "cleanup scope has no exact representations"
            )
        return exact

    @staticmethod
    def _validate_cleanup_proof(
        artifact: ArtifactDescriptor,
        expected: tuple[RepresentationRef, ...] | None,
        proof: CleanupProof,
    ) -> None:
        if (
            proof.artifact != artifact.identity
            or proof.generation != artifact.generation
            or proof.policy is not artifact.policy_profile
            or not proof.complete
            or len(proof.representation_refs) != len(set(proof.representation_refs))
            or (
                expected is not None
                and set(proof.representation_refs) != set(expected)
            )
        ):
            raise TransitionConflict("cleanup proof does not cover the exact owner scope")

    @staticmethod
    def _completed(
        binding: OperationBinding, operation: OperationRecord
    ) -> TransitionResult:
        receipt = ArchivalTransitionKernel._require_receipt(
            binding, operation, completed=True
        )
        return TransitionResult(TransitionStage.RETIRED, receipt.liveness, receipt)

    def _uncertain(self, binding: OperationBinding) -> TransitionResult:
        try:
            operation = self._adapter.read_operation(binding.idempotency_key)
        except TransitionFailure:
            return self._unavailable("transition-readback-unavailable")
        if operation is not None:
            try:
                self._validate_operation(binding, operation)
            except TransitionConflict:
                return self._conflict("operation-readback-binding-conflict")
        return TransitionResult(
            TransitionStage.RESERVED,
            Liveness(
                LivenessState.TRANSITION_PENDING,
                _evidence(f"pending-{binding.idempotency_key}"),
            ),
        )

    @staticmethod
    def _conflict(
        reason: str, receipt: ArchivalReceipt | None = None
    ) -> TransitionResult:
        return TransitionResult(
            TransitionStage.CONFLICT,
            Liveness(LivenessState.CONFLICT, _evidence(reason)),
            receipt,
        )

    @staticmethod
    def _unavailable(reason: str) -> TransitionResult:
        return TransitionResult(
            TransitionStage.RESERVED,
            Liveness(LivenessState.UNAVAILABLE, _evidence(reason)),
        )

    @staticmethod
    def _cleanup_pending(reason: str) -> TransitionResult:
        return TransitionResult(
            TransitionStage.ERASE_PENDING,
            Liveness(LivenessState.ERASURE_PENDING, _evidence(reason)),
        )


class DurableFakeAdapter:
    """Thread-safe test-only owner adapter with an immutable operation journal."""

    def __init__(self) -> None:
        self.representations: dict[RepresentationRef, Representation] = {}
        self.reservations: dict[OpaqueReference, RepresentationReservation] = {}
        self.operations: dict[str, OperationRecord] = {}
        self.effect_counts = {
            "bind": 0,
            "reserve": 0,
            "copy": 0,
            "verify": 0,
            "receipt": 0,
            "activate": 0,
            "retire": 0,
            "complete": 0,
            "restore": 0,
            "cleanup": 0,
        }
        self._restores: dict[
            tuple[ArtifactIdentity, Generation, RepresentationRef], ArchivalReceipt
        ] = {}
        self._cleanups: dict[
            tuple[ArtifactIdentity, Generation, PolicyProfile], CleanupProof
        ] = {}
        self._lock = RLock()
        self.fault: FaultStage | None = None
        self.source_retired = False
        self.access_gate_called = False

    def register_source(self, representation: Representation) -> None:
        with self._lock:
            self.representations[representation.ref] = representation

    def fail_once(self, stage: FaultStage) -> None:
        with self._lock:
            self.fault = stage

    def _fault(self, stage: FaultStage) -> None:
        if self.fault is stage:
            self.fault = None
            raise TransitionFailure(stage, f"injected failure at {stage.value}")

    @staticmethod
    def _validate_exact_binding(
        expected: OperationBinding, actual: OperationBinding
    ) -> None:
        if expected != actual:
            raise TransitionConflict("immutable operation binding differs")

    def _operation(self, binding: OperationBinding) -> OperationRecord:
        operation = self.operations.get(binding.idempotency_key)
        if operation is None:
            raise TransitionFailure(
                FaultStage.READBACK, "operation journal record is missing"
            )
        self._validate_exact_binding(binding, operation.binding)
        return operation

    def enumerate(self, artifact: ArtifactIdentity) -> tuple[Representation, ...]:
        with self._lock:
            return tuple(
                representation
                for representation in self.representations.values()
                if representation.artifact == artifact
            )

    def resolve(self, reference: RepresentationRef) -> Representation:
        with self._lock:
            self._fault(FaultStage.READBACK)
            try:
                return self.representations[reference]
            except KeyError as exc:
                raise TransitionFailure(
                    FaultStage.READBACK, "representation is unavailable"
                ) from exc

    def source(self, reference: RepresentationRef) -> Representation:
        """Compatibility helper for focused tests; not part of the public seam."""

        return self.resolve(reference)

    def authorize_read(
        self, artifact: ArtifactDescriptor, authority: AccessAuthority
    ) -> ArchivalReceipt:
        del authority
        with self._lock:
            self._fault(FaultStage.AUTHORIZATION)
            self.access_gate_called = True
            refs = tuple(
                reference
                for reference, representation in self.representations.items()
                if representation.artifact == artifact.identity
                and representation.generation == artifact.generation
                and representation.stage
                not in {TransitionStage.RETIRED, TransitionStage.ERASED}
            )
            return ArchivalReceipt(
                OpaqueReference("access-receipt", "read-1"),
                artifact.identity,
                artifact.generation,
                TransitionStage.ACTIVE,
                artifact.policy_profile,
                Liveness(LivenessState.ACTIVE, _evidence("access-granted")),
                (),
                refs,
            )

    def bind_operation(self, binding: OperationBinding) -> OperationRecord:
        with self._lock:
            existing = self.operations.get(binding.idempotency_key)
            if existing is not None:
                self._validate_exact_binding(binding, existing.binding)
                return existing
            self._fault(FaultStage.BINDING)
            for operation in self.operations.values():
                candidate = operation.binding
                if (
                    candidate.artifact == binding.artifact
                    and candidate.generation == binding.generation
                    and candidate.source == binding.source
                    and candidate != binding
                ):
                    raise TransitionConflict(
                        "another immutable operation binding already owns the source"
                    )
            operation = OperationRecord(binding)
            self.operations[binding.idempotency_key] = operation
            self.effect_counts["bind"] += 1
            self._fault(FaultStage.BINDING_AFTER_EFFECT)
            return operation

    def read_operation(self, idempotency_key: str) -> OperationRecord | None:
        with self._lock:
            self._fault(FaultStage.READBACK)
            return self.operations.get(idempotency_key)

    def reserve(self, binding: OperationBinding) -> RepresentationReservation:
        with self._lock:
            operation = self._operation(binding)
            if operation.reservation is not None:
                return operation.reservation
            self._fault(FaultStage.RESERVATION)
            existing = self.representations.get(binding.target)
            if existing is not None and (
                existing.artifact != binding.artifact
                or existing.generation != binding.generation
            ):
                raise TransitionConflict("destination binding is stale")
            reservation = RepresentationReservation(
                binding.artifact,
                binding.target,
                binding.generation,
                OpaqueReference("reservation", f"r-{len(self.reservations) + 1}"),
            )
            self.reservations[reservation.reservation_ref] = reservation
            self.operations[binding.idempotency_key] = replace(
                operation, reservation=reservation
            )
            self.effect_counts["reserve"] += 1
            self._fault(FaultStage.RESERVATION_AFTER_EFFECT)
            return reservation

    def copy(
        self, binding: OperationBinding, reservation: RepresentationReservation
    ) -> None:
        with self._lock:
            operation = self._operation(binding)
            self._validate_reservation(binding, reservation)
            if operation.copied:
                return
            self._fault(FaultStage.BYTES)
            self.representations[binding.target] = Representation(
                binding.artifact,
                binding.target,
                binding.generation,
                TransitionStage.RESERVED,
                Liveness(
                    LivenessState.TRANSITION_PENDING,
                    _evidence(reservation.reservation_ref.token),
                ),
            )
            self.operations[binding.idempotency_key] = replace(
                operation, copied=True
            )
            self.effect_counts["copy"] += 1
            self._fault(FaultStage.BYTES_AFTER_EFFECT)

    def verify(
        self, binding: OperationBinding, reservation: RepresentationReservation
    ) -> VerificationResult:
        with self._lock:
            operation = self._operation(binding)
            self._validate_reservation(binding, reservation)
            if operation.verification is not None:
                return operation.verification
            self._fault(FaultStage.VERIFICATION)
            representation = self.representations.get(binding.target)
            if (
                representation is None
                or representation.artifact != binding.artifact
                or representation.generation != binding.generation
            ):
                raise TransitionConflict("destination is not durable for the binding")
            verification = VerificationResult(
                binding.target,
                binding.generation,
                True,
                _evidence(f"verified-{reservation.reservation_ref.token}"),
            )
            self.representations[binding.target] = replace(
                representation, stage=TransitionStage.VERIFIED
            )
            self.operations[binding.idempotency_key] = replace(
                operation, verification=verification
            )
            self.effect_counts["verify"] += 1
            self._fault(FaultStage.VERIFICATION_AFTER_EFFECT)
            return verification

    def durable_receipt(
        self,
        binding: OperationBinding,
        reservation: RepresentationReservation,
        verification: VerificationResult,
    ) -> ArchivalReceipt:
        with self._lock:
            operation = self._operation(binding)
            self._validate_reservation(binding, reservation)
            self._validate_verification(binding, verification)
            if operation.receipt is not None:
                return operation.receipt
            self._fault(FaultStage.RECEIPT)
            receipt = ArchivalReceipt(
                OpaqueReference("receipt", reservation.reservation_ref.token),
                binding.artifact,
                binding.generation,
                TransitionStage.VERIFIED,
                binding.policy,
                Liveness(
                    LivenessState.ACTIVE,
                    _evidence(f"receipt-{reservation.reservation_ref.token}"),
                ),
                (),
                (binding.source, binding.target),
            )
            self.operations[binding.idempotency_key] = replace(
                operation, receipt=receipt
            )
            self.effect_counts["receipt"] += 1
            self._fault(FaultStage.RECEIPT_AFTER_EFFECT)
            return receipt

    def activate(
        self,
        binding: OperationBinding,
        reservation: RepresentationReservation,
        verification: VerificationResult,
        receipt: ArchivalReceipt,
    ) -> None:
        with self._lock:
            operation = self._operation(binding)
            self._validate_reservation(binding, reservation)
            self._validate_verification(binding, verification)
            self._validate_receipt(binding, receipt, completed=False)
            if operation.activated:
                return
            self._fault(FaultStage.ACTIVATION)
            representation = self.representations[binding.target]
            self.representations[binding.target] = replace(
                representation,
                stage=TransitionStage.ACTIVE,
                liveness=receipt.liveness,
            )
            self.operations[binding.idempotency_key] = replace(
                operation, activated=True
            )
            self.effect_counts["activate"] += 1
            self._fault(FaultStage.ACTIVATION_AFTER_EFFECT)

    def retire(
        self,
        binding: OperationBinding,
        representation: Representation,
        receipt: ArchivalReceipt,
    ) -> None:
        with self._lock:
            operation = self._operation(binding)
            self._validate_receipt(binding, receipt, completed=False)
            if representation.ref != binding.source:
                raise TransitionConflict("retirement source binding differs")
            if operation.retired:
                return
            if not operation.activated:
                raise TransitionConflict("source cannot retire before activation")
            self._fault(FaultStage.RETIREMENT)
            self.source_retired = True
            self.representations[binding.source] = replace(
                representation,
                stage=TransitionStage.RETIRED,
                liveness=receipt.liveness,
            )
            self.operations[binding.idempotency_key] = replace(
                operation, retired=True
            )
            self.effect_counts["retire"] += 1
            self._fault(FaultStage.RETIREMENT_AFTER_EFFECT)

    def complete_operation(
        self, binding: OperationBinding, receipt: ArchivalReceipt
    ) -> ArchivalReceipt:
        with self._lock:
            operation = self._operation(binding)
            if operation.completed:
                if operation.receipt is None:
                    raise TransitionConflict("completed operation has no receipt")
                return operation.receipt
            self._validate_receipt(binding, receipt, completed=False)
            if not operation.retired:
                raise TransitionConflict("operation cannot complete before retirement")
            self._fault(FaultStage.COMPLETION)
            completed = replace(receipt, stage=TransitionStage.RETIRED)
            self.operations[binding.idempotency_key] = replace(
                operation, receipt=completed, completed=True
            )
            self.effect_counts["complete"] += 1
            self._fault(FaultStage.COMPLETION_AFTER_EFFECT)
            return completed

    def restore(
        self,
        artifact: ArtifactDescriptor,
        authority: AccessAuthority,
        representation: RepresentationRef,
    ) -> ArchivalReceipt:
        del authority
        with self._lock:
            key = (artifact.identity, artifact.generation, representation)
            existing = self._restores.get(key)
            if existing is not None:
                return existing
            self._fault(FaultStage.RESTORE)
            restored = self.representations.get(representation)
            if (
                restored is None
                or restored.artifact != artifact.identity
                or restored.generation != artifact.generation
                or restored.stage in {TransitionStage.RETIRED, TransitionStage.ERASED}
            ):
                raise TransitionConflict("exact representation is unavailable")
            receipt = ArchivalReceipt(
                OpaqueReference("restore-receipt", representation.opaque_id.token),
                artifact.identity,
                artifact.generation,
                TransitionStage.RESTORED,
                artifact.policy_profile,
                Liveness(LivenessState.ACTIVE, _evidence("restored")),
                (),
                (representation,),
            )
            self._restores[key] = receipt
            self.effect_counts["restore"] += 1
            self._fault(FaultStage.RESTORE_AFTER_EFFECT)
            return receipt

    def read_restore(
        self, artifact: ArtifactDescriptor, representation: RepresentationRef
    ) -> ArchivalReceipt | None:
        with self._lock:
            self._fault(FaultStage.READBACK)
            return self._restores.get(
                (artifact.identity, artifact.generation, representation)
            )

    def cleanup(self, artifact: ArtifactDescriptor) -> CleanupProof:
        with self._lock:
            key = (artifact.identity, artifact.generation, artifact.policy_profile)
            existing = self._cleanups.get(key)
            if existing is not None:
                return existing
            self._fault(FaultStage.CLEANUP)
            references = tuple(
                reference
                for reference, representation in self.representations.items()
                if representation.artifact == artifact.identity
                and representation.generation == artifact.generation
            )
            if not references:
                raise TransitionFailure(
                    FaultStage.CLEANUP, "no representations are available for cleanup"
                )
            proof = CleanupProof(
                artifact.identity,
                artifact.generation,
                artifact.policy_profile,
                references,
                True,
                _evidence("cleanup-proven"),
            )
            for reference in references:
                self.representations[reference] = replace(
                    self.representations[reference],
                    stage=TransitionStage.ERASED,
                    liveness=Liveness(
                        LivenessState.ERASED, proof.evidence_ref
                    ),
                )
            self._cleanups[key] = proof
            self.effect_counts["cleanup"] += 1
            self._fault(FaultStage.CLEANUP_AFTER_EFFECT)
            return proof

    def read_cleanup(self, artifact: ArtifactDescriptor) -> CleanupProof | None:
        with self._lock:
            self._fault(FaultStage.READBACK)
            return self._cleanups.get(
                (artifact.identity, artifact.generation, artifact.policy_profile)
            )

    def doctor(self) -> tuple[DoctorFinding, ...]:
        return ()

    @staticmethod
    def _validate_reservation(
        binding: OperationBinding, reservation: RepresentationReservation
    ) -> None:
        if (
            reservation.artifact != binding.artifact
            or reservation.generation != binding.generation
            or reservation.target != binding.target
        ):
            raise TransitionConflict("reservation binding differs")

    @staticmethod
    def _validate_verification(
        binding: OperationBinding, verification: VerificationResult
    ) -> None:
        if (
            not verification.verified
            or verification.representation != binding.target
            or verification.generation != binding.generation
        ):
            raise TransitionConflict("verification binding differs")

    @staticmethod
    def _validate_receipt(
        binding: OperationBinding,
        receipt: ArchivalReceipt,
        *,
        completed: bool,
    ) -> None:
        expected_stage = (
            TransitionStage.RETIRED if completed else TransitionStage.VERIFIED
        )
        if (
            receipt.artifact != binding.artifact
            or receipt.generation != binding.generation
            or receipt.policy_profile is not binding.policy
            or receipt.stage is not expected_stage
            or receipt.representation_refs != (binding.source, binding.target)
        ):
            raise TransitionConflict("receipt binding differs")
