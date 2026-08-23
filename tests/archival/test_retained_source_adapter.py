"""GAF-04 production-path contract tests for curated retained sources."""

from __future__ import annotations

import hashlib

import pytest

from app.archival import (
    AccessAuthority,
    ArchivalTransitionKernel,
    ArtifactClass,
    ArtifactDescriptor,
    ArtifactIdentity,
    DerivationClass,
    DurableFakeAdapter,
    DurabilityClass,
    Generation,
    Liveness,
    LivenessState,
    OpaqueReference,
    OwnerAuthority,
    PolicyProfile,
    ProvenanceRef,
    Representation,
    RepresentationRef,
    TransitionStage,
)
from app.archival.adapters.retained_source import (
    OwnerKeepDecision,
    RetainedSourceAdmission,
    RetainedSourceAdapter,
    RetainedSourceKind,
    RetainedSourceRetirement,
)
from app.archival.transition import TransitionConflict, TransitionFailure


class _StorePort(DurableFakeAdapter):
    """Authorized PDM test binding; it exposes no DSN or filesystem location."""

    contract = "StorePort"
    owner_subsystem = "PDM"

    def __init__(self, source: RepresentationRef, payload: bytes) -> None:
        super().__init__()
        self.payloads = {source: payload}
        self.restored: dict[OpaqueReference, bytes] = {}
        self.receipt_metadata = {}
        self.restore_receipts = {}
        self.admissions = {"keep-42"}
        self.retirements = {"retire-42"}
        self.read_calls = 0
        self.write_calls = 0
        self.fail_cleanup = False

    def read_bytes(self, reference: RepresentationRef) -> bytes:
        self.read_calls += 1
        return self.payloads[reference]

    def write_restored(
        self,
        destination: OpaqueReference,
        payload: bytes,
        *,
        generation: Generation,
        format: str,
    ) -> None:
        self.write_calls += 1
        self.restored[destination] = payload

    def copy_bytes(self, source: RepresentationRef, target: RepresentationRef) -> None:
        self.payloads[target] = self.payloads[source]

    def record_retained_source_receipt(self, receipt, metadata) -> None:  # type: ignore[no-untyped-def]
        self.receipt_metadata[receipt.receipt_ref] = metadata

    def validate_admission(self, admission) -> None:  # type: ignore[no-untyped-def]
        if admission.keep_decision.reference.token not in self.admissions:
            raise TransitionConflict("retained-source admission is not owner-issued")

    def authorize_retirement(self, decision) -> None:  # type: ignore[no-untyped-def]
        if decision.reference.token not in self.retirements:
            raise TransitionConflict("retained-source retirement is not owner-issued")

    def record_restore_receipt(self, receipt) -> None:  # type: ignore[no-untyped-def]
        self.restore_receipts[(receipt.artifact, receipt.representation_refs[0])] = receipt

    def read_restore(self, artifact, representation):  # type: ignore[no-untyped-def]
        return self.restore_receipts.get((artifact.identity, representation))

    def cleanup(self, artifact: ArtifactDescriptor):  # type: ignore[no-untyped-def]
        if self.fail_cleanup:
            raise TransitionFailure("cleanup", "physical cleanup pending")
        return super().cleanup(artifact)


def _fixture(
    *,
    kind: RetainedSourceKind = RetainedSourceKind.MEDIA_ORIGINAL,
    format: str = "image/jpeg",
    payload: bytes = b"\x89JPEG-curated-original",
) -> tuple[RetainedSourceAdapter, _StorePort, ArtifactDescriptor, RepresentationRef, RepresentationRef]:
    identity = ArtifactIdentity(
        OwnerAuthority.CLASS_ADAPTER,
        OpaqueReference("retained-source", "owner-kept-42"),
        "retained_source",
    )
    descriptor = ArtifactDescriptor(
        identity=identity,
        artifact_class=ArtifactClass.SOURCE,
        derivation=DerivationClass.SOURCE,
        durability=DurabilityClass.DURABLE,
        owner=OwnerAuthority.CLASS_ADAPTER,
        generation=Generation(7),
        provenance_refs=(
            ProvenanceRef("content", OpaqueReference("content-sha256", hashlib.sha256(payload).hexdigest())),
            ProvenanceRef("origin", OpaqueReference("owner-provenance", "catalog-entry-42")),
        ),
        policy_profile=PolicyProfile.RETAINED_SOURCE,
    )
    source = RepresentationRef("retained_source", OpaqueReference("retained-source-representation", "primary-42"))
    target = RepresentationRef("retained_source", OpaqueReference("retained-source-representation", "archive-42"))
    store = _StorePort(source, payload)
    store.register_source(
        Representation(
            identity,
            source,
            descriptor.generation,
            TransitionStage.ACTIVE,
            Liveness(LivenessState.ACTIVE, OpaqueReference("retained-source-liveness", "source-live")),
        )
    )
    admission = RetainedSourceAdmission(
        descriptor=descriptor,
        source=source,
        kind=kind,
        format=format,
        keep_decision=OwnerKeepDecision(OpaqueReference("retained-source-admission", "keep-42")),
        restore_destination=_owner_gate(),
    )
    return RetainedSourceAdapter(admission, store), store, descriptor, source, target


def _owner_gate() -> OpaqueReference:
    return OpaqueReference("retained-source-destination", "reader-42")


def test_retained_source_round_trip_preserves_identity_and_provenance() -> None:
    for kind, format, payload in (
        (RetainedSourceKind.MEDIA_ORIGINAL, "image/jpeg", b"\x89JPEG-curated-original"),
        (RetainedSourceKind.DOCUMENT_ORIGINAL, "application/pdf", b"%PDF-curated-document"),
    ):
        adapter, store, descriptor, source, target = _fixture(kind=kind, format=format, payload=payload)

        archived = ArchivalTransitionKernel(adapter).archive(descriptor, source, target, f"archive-{kind.value}")
        restored = adapter.restore_to(descriptor, target, _owner_gate())

        assert archived.stage is TransitionStage.RETIRED
        assert archived.receipt is not None
        assert archived.receipt.artifact == descriptor.identity
        assert archived.receipt.generation == descriptor.generation
        assert archived.receipt.policy_profile is PolicyProfile.RETAINED_SOURCE
        assert store.receipt_metadata[archived.receipt.receipt_ref].provenance_refs == descriptor.provenance_refs
        assert restored.provenance_refs == descriptor.provenance_refs
        assert store.receipt_metadata[archived.receipt.receipt_ref].format == format
        assert store.restored[_owner_gate()] == payload
        assert adapter.read_restore(descriptor, target) == restored


def test_retained_source_admission_requires_owner_keep_decision() -> None:
    _adapter, _store, descriptor, source, _target = _fixture()

    invalid = (
        (RetainedSourceKind.EXTERNAL_RAW, OwnerKeepDecision(OpaqueReference("retained-source-admission", "keep-raw"))),
        (RetainedSourceKind.COMPANION_NOTE, OwnerKeepDecision(OpaqueReference("retained-source-admission", "keep-note"))),
        (RetainedSourceKind.MEDIA_ORIGINAL, None),
    )
    for kind, decision in invalid:
        with pytest.raises(ValueError, match="explicit owner keep decision|not a retained-source admission"):
            RetainedSourceAdmission(descriptor, source, kind, "image/jpeg", decision, _owner_gate())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="typed opaque reference"):
        RetainedSourceAdmission(  # type: ignore[arg-type]
            descriptor, "/private/source.jpg", RetainedSourceKind.MEDIA_ORIGINAL, "image/jpeg",
            OwnerKeepDecision(OpaqueReference("retained-source-admission", "keep-path")), _owner_gate(),
        )
    for location_like_format in ("file:///private/source", r"C:\\private\\source.pdf", "/private/source.pdf"):
        with pytest.raises(ValueError, match="non-location format"):
            RetainedSourceAdmission(
                descriptor, source, RetainedSourceKind.MEDIA_ORIGINAL, location_like_format,
                OwnerKeepDecision(OpaqueReference("retained-source-admission", "keep-format")), _owner_gate(),
            )


def test_retained_source_uses_store_port_and_redacted_receipts() -> None:
    adapter, store, descriptor, source, target = _fixture()

    archived = ArchivalTransitionKernel(adapter).archive(descriptor, source, target, "store-port")
    restored = adapter.restore_to(descriptor, target, _owner_gate())

    assert archived.receipt is not None and archived.receipt.redacted
    assert restored.redacted
    assert store.read_calls == 2  # archive verification plus gated restore
    assert store.write_calls == 1
    assert all("/" not in reference.opaque_id.token for reference in archived.receipt.representation_refs)


def test_retained_source_restore_is_gated_and_generation_bound() -> None:
    adapter, store, descriptor, source, _target = _fixture()

    stale = ArtifactDescriptor(
        descriptor.identity, descriptor.artifact_class, descriptor.derivation, descriptor.durability,
        descriptor.owner, Generation(8), descriptor.provenance_refs, descriptor.policy_profile,
    )
    with pytest.raises(TransitionConflict, match="generation"):
        adapter.restore_to(stale, source, _owner_gate())
    assert store.write_calls == 0

    with pytest.raises(TransitionConflict, match="destination"):
        adapter.restore_to(descriptor, source, OpaqueReference("retained-source-destination", "other-destination"))
    assert store.write_calls == 0

    restored = adapter.restore_to(descriptor, source, _owner_gate())
    assert restored.stage is TransitionStage.RESTORED
    assert store.write_calls == 1

    forged_gate = AccessAuthority(
        OwnerAuthority.CLASS_ADAPTER,
        OpaqueReference("retained-source-owner", "forged-destination"),
    )
    with pytest.raises(TransitionConflict, match="owner gate"):
        ArchivalTransitionKernel(adapter).restore(descriptor, forged_gate, source)


def test_retained_source_policy_does_not_inherit_raw_ttl() -> None:
    adapter, store, descriptor, source, target = _fixture()
    kernel = ArchivalTransitionKernel(adapter)
    kernel.archive(descriptor, source, target, "retire-policy")

    pending = kernel.cleanup(descriptor)
    assert pending.liveness.state is LivenessState.ERASURE_PENDING

    adapter.authorize_retirement(RetainedSourceRetirement(descriptor.identity, descriptor.generation, OpaqueReference("retained-source-retirement", "retire-42")))
    with pytest.raises(TransitionConflict, match="not owner-issued"):
        adapter.authorize_retirement(
            RetainedSourceRetirement(descriptor.identity, descriptor.generation, OpaqueReference("retained-source-retirement", "forged-retire"))
        )
    store.fail_cleanup = True
    pending_on_failure = kernel.cleanup(descriptor)
    assert pending_on_failure.liveness.state is LivenessState.ERASURE_PENDING
    assert not pending_on_failure.terminal

    store.fail_cleanup = False
    assert kernel.cleanup(descriptor).stage is TransitionStage.ERASED
