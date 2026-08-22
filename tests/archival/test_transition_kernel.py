from __future__ import annotations

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
    OpaqueReference,
    OwnerAuthority,
    PolicyProfile,
    ProvenanceRef,
    Representation,
    RepresentationRef,
    TransitionStage,
)
from app.archival.contracts import AccessAuthority, Liveness


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
    for stage in FaultStage:
        if stage is FaultStage.CLEANUP:
            continue
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
    reservation = adapter.find_operation("op-resume").reservation  # type: ignore[union-attr]
    result = kernel.transition(descriptor, source, target, "op-resume")
    assert result.stage is TransitionStage.RETIRED
    assert adapter.find_operation("op-resume").reservation == reservation  # type: ignore[union-attr]


def test_restore_failure_is_typed_pending() -> None:
    descriptor, source, _target, adapter, kernel = _fixture()
    adapter.fail_once(FaultStage.VERIFICATION)
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
    assert result.stage is TransitionStage.REFUSED
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
