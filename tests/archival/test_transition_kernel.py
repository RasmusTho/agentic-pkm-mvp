from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Event, Lock

from app.archival import (
    ArchivalTransitionKernel,
    ArtifactClass,
    ArtifactDescriptor,
    ArtifactIdentity,
    DerivationClass,
    DurableFakeAdapter,
    DurabilityClass,
    FaultStage,
    Generation,
    LivenessState,
    OperationBinding,
    OpaqueReference,
    OwnerAuthority,
    PolicyProfile,
    ProvenanceRef,
    Representation,
    RepresentationRef,
    TransitionStage,
    TransitionFailure,
)
from app.archival.contracts import AccessAuthority, CleanupProof, Liveness


def _fixture() -> tuple[ArtifactDescriptor, RepresentationRef, RepresentationRef, DurableFakeAdapter, ArchivalTransitionKernel]:
    identity = ArtifactIdentity(OwnerAuthority.CLASS_ADAPTER, OpaqueReference("fixture", "source-1"), "fixture")
    descriptor = ArtifactDescriptor(
        identity, ArtifactClass.SOURCE, DerivationClass.SOURCE, DurabilityClass.DURABLE,
        OwnerAuthority.CLASS_ADAPTER, Generation(3),
        (ProvenanceRef("origin", OpaqueReference("fixture", "origin-1")),), PolicyProfile.RETAINED_SOURCE,
    )
    source = RepresentationRef("fixture", OpaqueReference("fixture", "source-1"))
    target = RepresentationRef("fixture", OpaqueReference("fixture", "archive-1"))
    adapter = DurableFakeAdapter()
    adapter.register_source(Representation(
        identity, source, Generation(3), TransitionStage.ACTIVE,
        Liveness(LivenessState.ACTIVE, OpaqueReference("fixture", "live")),
    ))
    return descriptor, source, target, adapter, ArchivalTransitionKernel(adapter)


def test_verified_transition_is_durable_before_source_retirement() -> None:
    descriptor, source, target, adapter, kernel = _fixture()
    result = kernel.transition(descriptor, source, target, "op-1")
    assert result.stage is TransitionStage.RETIRED
    assert adapter.representations[target].stage is TransitionStage.ACTIVE
    assert adapter.source_retired


def test_crash_matrix_preserves_source_and_retry_authority() -> None:
    for stage in (
        FaultStage.BINDING,
        FaultStage.RESERVATION,
        FaultStage.BYTES,
        FaultStage.VERIFICATION,
        FaultStage.RECEIPT,
        FaultStage.ACTIVATION,
        FaultStage.RETIREMENT,
        FaultStage.COMPLETION,
    ):
        descriptor, source, target, adapter, kernel = _fixture()
        adapter.fail_once(stage)
        failed = kernel.transition(descriptor, source, target, f"op-{stage.value}")
        assert failed.liveness.state in {LivenessState.TRANSITION_PENDING, LivenessState.REFUSED}
        retried = kernel.transition(descriptor, source, target, f"op-{stage.value}")
        assert retried.liveness.state is not LivenessState.ERASED


def test_retry_reuses_durable_reservation_and_source_binding() -> None:
    descriptor, source, target, adapter, kernel = _fixture()
    adapter.fail_once(FaultStage.ACTIVATION)
    pending = kernel.transition(descriptor, source, target, "op-resume")
    assert pending.liveness.state is LivenessState.TRANSITION_PENDING
    reservation = adapter.read_operation("op-resume").reservation  # type: ignore[union-attr]
    result = kernel.transition(descriptor, source, target, "op-resume")
    assert result.stage is TransitionStage.RETIRED
    assert adapter.read_operation("op-resume").reservation == reservation  # type: ignore[union-attr]


def test_restore_failure_is_typed_pending() -> None:
    descriptor, source, _target, adapter, kernel = _fixture()
    adapter.fail_once(FaultStage.RESTORE)
    result = kernel.restore(descriptor, AccessAuthority(OwnerAuthority.GOV, OpaqueReference("grant", "r1")), source)
    assert result.liveness.state is LivenessState.RESTORE_PENDING
    assert not result.terminal


def test_post_retirement_crash_reconciles_without_duplicate_retirement() -> None:
    descriptor, source, target, adapter, kernel = _fixture()
    adapter.fail_once(FaultStage.COMPLETION)
    pending = kernel.transition(descriptor, source, target, "op-post-effect")
    assert pending.liveness.state is LivenessState.TRANSITION_PENDING
    assert adapter.source(source).stage is TransitionStage.RETIRED
    result = kernel.transition(descriptor, source, target, "op-post-effect")
    assert result.stage is TransitionStage.RETIRED
    assert adapter.source_retired


def test_post_activation_crash_retries_idempotently() -> None:
    descriptor, source, target, adapter, kernel = _fixture()
    adapter.fail_once(FaultStage.ACTIVATION_AFTER_EFFECT)
    pending = kernel.transition(descriptor, source, target, "op-activation-effect")
    assert pending.liveness.state is LivenessState.TRANSITION_PENDING
    result = kernel.transition(descriptor, source, target, "op-activation-effect")
    assert result.stage is TransitionStage.RETIRED
    assert adapter.representations[target].stage is TransitionStage.ACTIVE


def test_stale_generation_and_binding_fail_closed_before_effect() -> None:
    descriptor, source, target, adapter, kernel = _fixture()
    stale = ArtifactDescriptor(
        descriptor.identity, descriptor.artifact_class, descriptor.derivation, descriptor.durability,
        descriptor.owner, Generation(4), descriptor.provenance_refs, descriptor.policy_profile,
    )
    result = kernel.transition(stale, source, target, "stale")
    assert result.stage is TransitionStage.CONFLICT
    assert target not in adapter.representations


def test_restore_requires_owner_access_gate_and_exact_representation() -> None:
    descriptor, source, _target, adapter, kernel = _fixture()
    result = kernel.restore(descriptor, AccessAuthority(OwnerAuthority.GOV, OpaqueReference("grant", "r1")), source)
    assert result.stage is TransitionStage.RESTORED
    assert adapter.access_gate_called


def test_cleanup_failure_cannot_project_terminal_erasure() -> None:
    descriptor, _source, _target, adapter, kernel = _fixture()
    adapter.fail_once(FaultStage.CLEANUP)
    assert kernel.cleanup(descriptor).liveness.state is LivenessState.ERASURE_PENDING
    assert kernel.cleanup(descriptor).liveness.state is LivenessState.ERASED


def test_pre_receipt_fault_reuses_bound_operation_and_reservation() -> None:
    for fault in (FaultStage.BYTES, FaultStage.VERIFICATION, FaultStage.RECEIPT):
        descriptor, source, target, adapter, kernel = _fixture()
        adapter.fail_once(fault)

        pending = kernel.transition(descriptor, source, target, f"pre-receipt-{fault.value}")
        bound = adapter.read_operation(f"pre-receipt-{fault.value}")

        assert pending.liveness.state is LivenessState.TRANSITION_PENDING
        assert bound is not None
        assert bound.binding == OperationBinding(
            f"pre-receipt-{fault.value}",
            descriptor.identity,
            descriptor.generation,
            descriptor.policy_profile,
            source,
            target,
        )

        completed = kernel.transition(
            descriptor, source, target, f"pre-receipt-{fault.value}"
        )
        assert completed.stage is TransitionStage.RETIRED
        assert len(adapter.reservations) == 1


def test_wrong_binding_proof_cannot_activate_or_retire() -> None:
    class WrongVerificationAdapter(DurableFakeAdapter):
        def verify(self, binding, reservation):  # type: ignore[no-untyped-def]
            proof = super().verify(binding, reservation)
            return replace(
                proof,
                representation=RepresentationRef(
                    "fixture", OpaqueReference("fixture", "wrong-target")
                ),
            )

    descriptor, source, target, _adapter, _kernel = _fixture()
    proof_adapter = WrongVerificationAdapter()
    proof_adapter.register_source(
        Representation(
            descriptor.identity,
            source,
            descriptor.generation,
            TransitionStage.ACTIVE,
            Liveness(LivenessState.ACTIVE, OpaqueReference("fixture", "live")),
        )
    )
    result = ArchivalTransitionKernel(proof_adapter).transition(
        descriptor, source, target, "wrong-proof"
    )
    assert result.stage is TransitionStage.CONFLICT
    assert proof_adapter.effect_counts["activate"] == 0
    assert proof_adapter.effect_counts["retire"] == 0

    class WrongReservationAdapter(DurableFakeAdapter):
        def reserve(self, binding):  # type: ignore[no-untyped-def]
            reservation = super().reserve(binding)
            return replace(
                reservation,
                target=RepresentationRef(
                    "fixture", OpaqueReference("fixture", "wrong-reservation")
                ),
            )

    reservation_adapter = WrongReservationAdapter()
    reservation_adapter.register_source(
        Representation(
            descriptor.identity,
            source,
            descriptor.generation,
            TransitionStage.ACTIVE,
            Liveness(LivenessState.ACTIVE, OpaqueReference("fixture", "live")),
        )
    )
    reservation_result = ArchivalTransitionKernel(reservation_adapter).transition(
        descriptor, source, target, "wrong-reservation"
    )
    assert reservation_result.stage is TransitionStage.CONFLICT
    assert reservation_adapter.effect_counts["activate"] == 0
    assert reservation_adapter.effect_counts["retire"] == 0

    class WrongReceiptAdapter(DurableFakeAdapter):
        def durable_receipt(  # type: ignore[no-untyped-def]
            self, binding, reservation, verification
        ):
            receipt = super().durable_receipt(binding, reservation, verification)
            return replace(receipt, policy_profile=PolicyProfile.HKA_RECOVERY)

    receipt_adapter = WrongReceiptAdapter()
    receipt_adapter.register_source(
        Representation(
            descriptor.identity,
            source,
            descriptor.generation,
            TransitionStage.ACTIVE,
            Liveness(LivenessState.ACTIVE, OpaqueReference("fixture", "live")),
        )
    )
    receipt_result = ArchivalTransitionKernel(receipt_adapter).transition(
        descriptor, source, target, "wrong-receipt"
    )
    assert receipt_result.stage is TransitionStage.CONFLICT
    assert receipt_adapter.effect_counts["activate"] == 0
    assert receipt_adapter.effect_counts["retire"] == 0

    alternate_identity = ArtifactIdentity(
        OwnerAuthority.CLASS_ADAPTER,
        OpaqueReference("fixture", "other-artifact"),
        "fixture",
    )
    alternate_source = RepresentationRef(
        "fixture", OpaqueReference("fixture", "other-source")
    )
    alternate_target = RepresentationRef(
        "fixture", OpaqueReference("fixture", "other-target")
    )
    mutations = (
        {"idempotency_key": "other-key"},
        {"artifact": alternate_identity},
        {"generation": Generation(descriptor.generation.value + 1)},
        {"policy": PolicyProfile.HKA_RECOVERY},
        {"source": alternate_source},
        {"target": alternate_target},
    )
    for index, mutation in enumerate(mutations):
        descriptor, source, target, adapter, kernel = _fixture()
        key = f"wrong-loaded-binding-{index}"
        expected = OperationBinding(
            key,
            descriptor.identity,
            descriptor.generation,
            descriptor.policy_profile,
            source,
            target,
        )
        adapter.bind_operation(expected)
        adapter.operations[key] = replace(
            adapter.operations[key], binding=replace(expected, **mutation)
        )

        loaded_result = kernel.transition(descriptor, source, target, key)
        assert loaded_result.stage is TransitionStage.CONFLICT
        assert adapter.effect_counts["activate"] == 0
        assert adapter.effect_counts["retire"] == 0


def test_resumed_and_after_effect_faults_reconcile_through_readback() -> None:
    fault_stages = (
        FaultStage.BINDING,
        FaultStage.BINDING_AFTER_EFFECT,
        FaultStage.RESERVATION,
        FaultStage.RESERVATION_AFTER_EFFECT,
        FaultStage.BYTES,
        FaultStage.BYTES_AFTER_EFFECT,
        FaultStage.VERIFICATION,
        FaultStage.VERIFICATION_AFTER_EFFECT,
        FaultStage.RECEIPT,
        FaultStage.RECEIPT_AFTER_EFFECT,
        FaultStage.ACTIVATION,
        FaultStage.ACTIVATION_AFTER_EFFECT,
        FaultStage.RETIREMENT,
        FaultStage.RETIREMENT_AFTER_EFFECT,
        FaultStage.COMPLETION,
        FaultStage.COMPLETION_AFTER_EFFECT,
        FaultStage.READBACK,
    )
    for fault in fault_stages:
        descriptor, source, target, adapter, kernel = _fixture()
        key = f"uncertain-{fault.value}"
        adapter.fail_once(fault)

        uncertain = kernel.transition(descriptor, source, target, key)
        if fault is FaultStage.COMPLETION_AFTER_EFFECT:
            assert uncertain.stage is TransitionStage.RETIRED
            assert uncertain.receipt is not None
        else:
            assert uncertain.liveness.state in {
                LivenessState.TRANSITION_PENDING,
                LivenessState.UNAVAILABLE,
            }

        completed = kernel.transition(descriptor, source, target, key)
        assert completed.stage is TransitionStage.RETIRED
        assert len(adapter.reservations) == 1
        assert adapter.effect_counts["reserve"] == 1
        assert adapter.effect_counts["copy"] == 1
        assert adapter.effect_counts["activate"] == 1
        assert adapter.effect_counts["retire"] == 1
        assert adapter.effect_counts["complete"] == 1


def test_first_success_and_retry_return_identical_completed_receipt() -> None:
    descriptor, source, target, adapter, kernel = _fixture()

    first = kernel.transition(descriptor, source, target, "canonical-completed")
    retried = kernel.transition(descriptor, source, target, "canonical-completed")
    operation = adapter.read_operation("canonical-completed")

    assert first.stage is TransitionStage.RETIRED
    assert first.receipt is not None
    assert first.receipt.stage is TransitionStage.RETIRED
    assert first.receipt == retried.receipt
    assert operation is not None
    assert first.receipt == operation.receipt


def test_completion_after_effect_returns_canonical_completed_receipt() -> None:
    descriptor, source, target, adapter, kernel = _fixture()
    adapter.fail_once(FaultStage.COMPLETION_AFTER_EFFECT)

    first = kernel.transition(
        descriptor, source, target, "completion-after-effect-canonical"
    )
    retried = kernel.transition(
        descriptor, source, target, "completion-after-effect-canonical"
    )
    operation = adapter.read_operation("completion-after-effect-canonical")

    assert first.stage is TransitionStage.RETIRED
    assert first.terminal
    assert first.receipt is not None
    assert first.receipt == retried.receipt
    assert operation is not None
    assert operation.completed
    assert first.receipt == operation.receipt


def test_concurrent_same_key_and_competing_bindings_converge_or_conflict() -> None:
    descriptor, source, target, adapter, kernel = _fixture()
    barrier = Barrier(2)

    def same_key_call():  # type: ignore[no-untyped-def]
        barrier.wait()
        return kernel.transition(descriptor, source, target, "same-key")

    with ThreadPoolExecutor(max_workers=2) as executor:
        same_key_results = list(executor.map(lambda _index: same_key_call(), range(2)))

    assert {result.stage for result in same_key_results} == {TransitionStage.RETIRED}
    assert same_key_results[0].receipt == same_key_results[1].receipt
    assert len(adapter.reservations) == 1
    assert adapter.effect_counts["retire"] == 1

    descriptor, source, target, adapter, kernel = _fixture()
    competing_target = RepresentationRef(
        "fixture", OpaqueReference("fixture", "archive-2")
    )
    barrier = Barrier(2)

    def competing_call(key: str, selected_target: RepresentationRef):
        barrier.wait()
        return kernel.transition(descriptor, source, selected_target, key)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(competing_call, "competing-a", target),
            executor.submit(competing_call, "competing-b", competing_target),
        )
        competing_results = [future.result() for future in futures]

    assert sorted(result.stage.value for result in competing_results) == [
        TransitionStage.CONFLICT.value,
        TransitionStage.RETIRED.value,
    ]
    assert len(adapter.reservations) == 1
    assert adapter.effect_counts["retire"] == 1


def test_restore_and_cleanup_require_exact_owner_native_proof() -> None:
    descriptor, source, target, adapter, kernel = _fixture()
    kernel.transition(descriptor, source, target, "prepare-restore")
    authority = AccessAuthority(
        OwnerAuthority.GOV, OpaqueReference("grant", "restore-1")
    )

    adapter.fail_once(FaultStage.RESTORE_AFTER_EFFECT)
    restored = kernel.restore(descriptor, authority, target)
    assert restored.stage is TransitionStage.RESTORED
    assert restored.receipt is not None
    assert restored.receipt.representation_refs == (target,)

    wrong_representation = RepresentationRef(
        "fixture", OpaqueReference("fixture", "not-authorized")
    )
    refused_restore = kernel.restore(descriptor, authority, wrong_representation)
    assert refused_restore.stage is TransitionStage.CONFLICT

    adapter.fail_once(FaultStage.CLEANUP)
    pending_cleanup = kernel.cleanup(descriptor)
    assert pending_cleanup.liveness.state is LivenessState.ERASURE_PENDING

    adapter.fail_once(FaultStage.CLEANUP_AFTER_EFFECT)
    completed_cleanup = kernel.cleanup(descriptor)
    proof = adapter.read_cleanup(descriptor)
    assert completed_cleanup.stage is TransitionStage.ERASED
    assert isinstance(proof, CleanupProof)
    assert proof.complete
    assert set(proof.representation_refs) == set(adapter.representations)

    class InexactCleanupAdapter(DurableFakeAdapter):
        def cleanup(self, artifact):  # type: ignore[no-untyped-def]
            proof = super().cleanup(artifact)
            return replace(
                proof,
                representation_refs=(
                    RepresentationRef(
                        "fixture", OpaqueReference("fixture", "wrong-cleanup")
                    ),
                ),
            )

    descriptor, source, _target, _adapter, _kernel = _fixture()
    inexact = InexactCleanupAdapter()
    inexact.register_source(
        Representation(
            descriptor.identity,
            source,
            descriptor.generation,
            TransitionStage.ACTIVE,
            Liveness(LivenessState.ACTIVE, OpaqueReference("fixture", "live")),
        )
    )
    inexact_result = ArchivalTransitionKernel(inexact).cleanup(descriptor)
    assert inexact_result.liveness.state is LivenessState.ERASURE_PENDING


def test_restore_does_not_reuse_receipt_when_current_authorization_fails() -> None:
    descriptor, source, _target, adapter, kernel = _fixture()
    first_authority = AccessAuthority(
        OwnerAuthority.GOV, OpaqueReference("grant", "restore-first")
    )
    current_authority = AccessAuthority(
        OwnerAuthority.GOV, OpaqueReference("grant", "restore-current")
    )
    first = kernel.restore(descriptor, first_authority, source)
    assert first.stage is TransitionStage.RESTORED

    adapter.fail_once(FaultStage.AUTHORIZATION)
    refused = kernel.restore(descriptor, current_authority, source)

    assert refused.stage is not TransitionStage.RESTORED
    assert refused.liveness.state in {
        LivenessState.RESTORE_PENDING,
        LivenessState.UNAVAILABLE,
    }
    assert refused.receipt is None


def test_cleanup_retry_reads_durable_proof_before_live_enumeration() -> None:
    class RemovingCleanupAdapter(DurableFakeAdapter):
        def cleanup(self, artifact):  # type: ignore[no-untyped-def]
            try:
                proof = super().cleanup(artifact)
            except TransitionFailure:
                proof = self.read_cleanup(artifact)
                if proof is not None:
                    for reference in proof.representation_refs:
                        self.representations.pop(reference, None)
                raise
            for reference in proof.representation_refs:
                self.representations.pop(reference, None)
            return proof

    descriptor, source, _target, _adapter, _kernel = _fixture()
    adapter = RemovingCleanupAdapter()
    adapter.register_source(
        Representation(
            descriptor.identity,
            source,
            descriptor.generation,
            TransitionStage.ACTIVE,
            Liveness(LivenessState.ACTIVE, OpaqueReference("fixture", "live")),
        )
    )
    kernel = ArchivalTransitionKernel(adapter)
    adapter.fail_once(FaultStage.CLEANUP_AFTER_EFFECT)

    first = kernel.cleanup(descriptor)
    retried = kernel.cleanup(descriptor)

    assert adapter.enumerate(descriptor.identity) == ()
    assert first.stage is TransitionStage.ERASED
    assert retried.stage is TransitionStage.ERASED
    assert first.liveness == retried.liveness
    assert adapter.effect_counts["cleanup"] == 1


def test_equal_source_and_target_fail_closed_before_binding() -> None:
    descriptor, source, _target, adapter, kernel = _fixture()

    result = kernel.transition(descriptor, source, source, "same-representation")

    assert result.stage is TransitionStage.CONFLICT
    assert adapter.source(source).stage is TransitionStage.ACTIVE
    assert all(count == 0 for count in adapter.effect_counts.values())


def test_unreadable_source_cannot_reserve_copy_or_complete() -> None:
    descriptor, source, target, adapter, kernel = _fixture()
    adapter.representations[source] = replace(
        adapter.representations[source],
        stage=TransitionStage.ERASED,
        liveness=Liveness(
            LivenessState.ERASED, OpaqueReference("fixture", "source-erased")
        ),
    )

    result = kernel.transition(descriptor, source, target, "unreadable-source")

    assert result.stage is not TransitionStage.RETIRED
    assert result.liveness.state is LivenessState.CONFLICT
    assert target not in adapter.representations
    assert adapter.effect_counts["reserve"] == 0
    assert adapter.effect_counts["copy"] == 0
    assert adapter.effect_counts["complete"] == 0


def test_stale_cleanup_proof_cannot_hide_new_live_representation() -> None:
    descriptor, _source, _target, adapter, kernel = _fixture()
    completed = kernel.cleanup(descriptor)
    assert completed.stage is TransitionStage.ERASED

    new_representation = RepresentationRef(
        "fixture", OpaqueReference("fixture", "post-cleanup-live")
    )
    adapter.register_source(
        Representation(
            descriptor.identity,
            new_representation,
            descriptor.generation,
            TransitionStage.ACTIVE,
            Liveness(
                LivenessState.ACTIVE, OpaqueReference("fixture", "new-live")
            ),
        )
    )

    retried = kernel.cleanup(descriptor)

    assert retried.stage is TransitionStage.ERASE_PENDING
    assert retried.liveness.state is LivenessState.ERASURE_PENDING
    assert adapter.effect_counts["cleanup"] == 1


def test_same_key_stale_snapshot_rereads_concurrent_completion() -> None:
    class OrderedSameKeyAdapter(DurableFakeAdapter):
        def __init__(self, source: RepresentationRef) -> None:
            super().__init__()
            self._source = source
            self._source_calls = 0
            self._control_lock = Lock()
            self._first_source_waiting = Event()
            self._operation_completed = Event()

        def resolve(self, reference):  # type: ignore[no-untyped-def]
            if reference == self._source:
                with self._control_lock:
                    self._source_calls += 1
                    source_call = self._source_calls
                if source_call == 1:
                    self._first_source_waiting.set()
                    assert self._operation_completed.wait(timeout=5)
                elif source_call == 2:
                    assert self._first_source_waiting.wait(timeout=5)
            return super().resolve(reference)

        def complete_operation(self, binding, receipt):  # type: ignore[no-untyped-def]
            completed = super().complete_operation(binding, receipt)
            self._operation_completed.set()
            return completed

    descriptor, source, target, _adapter, _kernel = _fixture()
    adapter = OrderedSameKeyAdapter(source)
    adapter.register_source(
        Representation(
            descriptor.identity,
            source,
            descriptor.generation,
            TransitionStage.ACTIVE,
            Liveness(LivenessState.ACTIVE, OpaqueReference("fixture", "live")),
        )
    )
    kernel = ArchivalTransitionKernel(adapter)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _index: kernel.transition(
                    descriptor, source, target, "ordered-same-key"
                ),
                range(2),
            )
        )

    assert {result.stage for result in results} == {TransitionStage.RETIRED}
    assert results[0].receipt == results[1].receipt
    assert adapter.effect_counts["retire"] == 1
    assert adapter.effect_counts["complete"] == 1


def test_same_key_completion_between_readback_checkpoints_converges() -> None:
    class OrderedReservationAdapter(DurableFakeAdapter):
        def __init__(self) -> None:
            super().__init__()
            self._reserve_calls = 0
            self._control_lock = Lock()
            self._first_reservation_waiting = Event()
            self._operation_completed = Event()

        def reserve(self, binding):  # type: ignore[no-untyped-def]
            with self._control_lock:
                self._reserve_calls += 1
                reserve_call = self._reserve_calls
            if reserve_call == 1:
                self._first_reservation_waiting.set()
                assert self._operation_completed.wait(timeout=5)
            elif reserve_call == 2:
                assert self._first_reservation_waiting.wait(timeout=5)
            return super().reserve(binding)

        def complete_operation(self, binding, receipt):  # type: ignore[no-untyped-def]
            completed = super().complete_operation(binding, receipt)
            self._operation_completed.set()
            return completed

    descriptor, source, target, _adapter, _kernel = _fixture()
    adapter = OrderedReservationAdapter()
    adapter.register_source(
        Representation(
            descriptor.identity,
            source,
            descriptor.generation,
            TransitionStage.ACTIVE,
            Liveness(LivenessState.ACTIVE, OpaqueReference("fixture", "live")),
        )
    )
    kernel = ArchivalTransitionKernel(adapter)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _index: kernel.transition(
                    descriptor, source, target, "checkpoint-same-key"
                ),
                range(2),
            )
        )

    assert {result.stage for result in results} == {TransitionStage.RETIRED}
    assert results[0].receipt == results[1].receipt
    assert adapter.effect_counts["reserve"] == 1
    assert adapter.effect_counts["complete"] == 1


def test_restore_requires_successful_exact_authorization_gate() -> None:
    class InexactAuthorizationAdapter(DurableFakeAdapter):
        def __init__(self, mutation):  # type: ignore[no-untyped-def]
            super().__init__()
            self._mutation = mutation

        def authorize_read(self, artifact, authority):  # type: ignore[no-untyped-def]
            return replace(super().authorize_read(artifact, authority), **self._mutation)

    descriptor, source, _target, _adapter, _kernel = _fixture()
    authority = AccessAuthority(
        OwnerAuthority.GOV, OpaqueReference("grant", "exact-gate")
    )
    mutations = (
        {"stage": TransitionStage.REFUSED},
        {
            "liveness": Liveness(
                LivenessState.REFUSED, OpaqueReference("fixture", "gate-refused")
            )
        },
        {"policy_profile": PolicyProfile.HKA_RECOVERY},
    )

    for mutation in mutations:
        adapter = InexactAuthorizationAdapter(mutation)
        adapter.register_source(
            Representation(
                descriptor.identity,
                source,
                descriptor.generation,
                TransitionStage.ACTIVE,
                Liveness(
                    LivenessState.ACTIVE, OpaqueReference("fixture", "live")
                ),
            )
        )
        result = ArchivalTransitionKernel(adapter).restore(
            descriptor, authority, source
        )

        assert result.stage is TransitionStage.CONFLICT
        assert adapter.effect_counts["restore"] == 0


def test_restore_receipt_requires_terminal_active_liveness() -> None:
    class PendingReceiptAdapter(DurableFakeAdapter):
        def restore(self, artifact, authority, representation):  # type: ignore[no-untyped-def]
            receipt = super().restore(artifact, authority, representation)
            return replace(
                receipt,
                liveness=Liveness(
                    LivenessState.RESTORE_PENDING,
                    OpaqueReference("fixture", "restore-indeterminate"),
                ),
            )

    descriptor, source, _target, _adapter, _kernel = _fixture()
    adapter = PendingReceiptAdapter()
    adapter.register_source(
        Representation(
            descriptor.identity,
            source,
            descriptor.generation,
            TransitionStage.ACTIVE,
            Liveness(LivenessState.ACTIVE, OpaqueReference("fixture", "live")),
        )
    )

    result = ArchivalTransitionKernel(adapter).restore(
        descriptor,
        AccessAuthority(
            OwnerAuthority.GOV, OpaqueReference("grant", "pending-receipt")
        ),
        source,
    )

    assert result.stage is TransitionStage.CONFLICT
    assert not result.terminal


def test_indeterminate_transition_receipt_cannot_activate_or_retire() -> None:
    class PendingTransitionReceiptAdapter(DurableFakeAdapter):
        def durable_receipt(self, binding, reservation, verification):  # type: ignore[no-untyped-def]
            receipt = super().durable_receipt(binding, reservation, verification)
            return replace(
                receipt,
                liveness=Liveness(
                    LivenessState.TRANSITION_PENDING,
                    OpaqueReference("fixture", "transition-indeterminate"),
                ),
            )

    descriptor, source, target, _adapter, _kernel = _fixture()
    adapter = PendingTransitionReceiptAdapter()
    adapter.register_source(
        Representation(
            descriptor.identity,
            source,
            descriptor.generation,
            TransitionStage.ACTIVE,
            Liveness(LivenessState.ACTIVE, OpaqueReference("fixture", "live")),
        )
    )

    result = ArchivalTransitionKernel(adapter).transition(
        descriptor, source, target, "pending-transition-receipt"
    )

    assert result.stage is TransitionStage.CONFLICT
    assert not result.terminal
    assert adapter.effect_counts["activate"] == 0
    assert adapter.effect_counts["retire"] == 0
