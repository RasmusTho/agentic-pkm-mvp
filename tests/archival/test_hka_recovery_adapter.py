"""GAF-05 contract tests for portable, owner-governed HKA recovery."""

from __future__ import annotations

import hashlib

from app.archival import (
    ArtifactClass,
    ArtifactDescriptor,
    ArtifactIdentity,
    DerivationClass,
    DurabilityClass,
    Generation,
    OpaqueReference,
    OwnerAuthority,
    PolicyProfile,
    ProvenanceRef,
)
from app.archival.adapters.hka_recovery import (
    HkaGovernedWriteAuthority,
    HkaNewerGenerationConflict,
    HkaOwnerVersion,
    HkaRecoveryAdapter,
    HkaRecoveryConflict,
    HkaRecoveryExport,
    HkaRecoveryReceipt,
    HkaRecoveryStage,
    HkaRecoveryVaultPortAdapter,
    HkaRecoveryVerification,
)
from app.ports.vault_port import DummyVaultPort, VaultPort


class _HkaVaultPort(DummyVaultPort):
    """Owner-native test seam; HKA state remains here, never in the adapter."""

    contract = "VaultPort"
    owner_subsystem = "HKA"

    def __init__(self, descriptor: ArtifactDescriptor) -> None:
        super().__init__()
        self.descriptor = descriptor
        self.current_generation = descriptor.generation
        self.calls: list[str] = []
        self.production_writes = 0
        self.raw_delete_calls = 0
        self.racing_owner: HkaOwnerVersion | None = None
        self._stage: HkaRecoveryStage | None = None

    def stage_hka_recovery(self, export: HkaRecoveryExport) -> HkaRecoveryStage:
        self.calls.append("stage")
        self._stage = HkaRecoveryStage(
            export=export,
            stage_ref=OpaqueReference("hka-recovery-stage", "stage-42"),
        )
        return self._stage

    def verify_hka_recovery(self, stage: HkaRecoveryStage) -> HkaRecoveryVerification:
        self.calls.append("verify")
        assert stage == self._stage
        return HkaRecoveryVerification(
            stage_ref=stage.stage_ref,
            integrity_digest=stage.export.integrity_digest,
        )

    def read_hka_owner_version(self, identity: ArtifactIdentity) -> HkaOwnerVersion:
        assert identity == self.descriptor.identity
        return HkaOwnerVersion(
            identity=self.descriptor.identity,
            generation=self.current_generation,
            representation_ref=OpaqueReference("hka-owner-representation", "note-42"),
        )

    def governed_write_hka_recovery(
        self,
        stage: HkaRecoveryStage,
        verification: HkaRecoveryVerification,
        authority: HkaGovernedWriteAuthority,
    ) -> HkaRecoveryReceipt:
        self.calls.append("governed_write")
        assert stage == self._stage
        assert verification.integrity_digest == stage.export.integrity_digest
        assert authority.reference.namespace == "hka-governed-write"
        if self.racing_owner is not None:
            raise HkaNewerGenerationConflict(self.racing_owner)
        self.production_writes += 1
        self.current_generation = stage.export.generation
        return HkaRecoveryReceipt(
            receipt_ref=OpaqueReference("hka-governed-write-receipt", "write-42"),
            identity=stage.export.identity,
            generation=stage.export.generation,
            provenance_refs=stage.export.provenance_refs,
            policy_profile=stage.export.policy_profile,
        )


def _fixture() -> tuple[HkaRecoveryAdapter, _HkaVaultPort, ArtifactDescriptor]:
    body = "# Durable note\n\nA human-readable recovery representation.\n"
    identity = ArtifactIdentity(
        OwnerAuthority.HKA,
        OpaqueReference("hka-artifact", "note-42"),
    )
    descriptor = ArtifactDescriptor(
        identity=identity,
        artifact_class=ArtifactClass.HUMAN,
        derivation=DerivationClass.SOURCE,
        durability=DurabilityClass.DURABLE,
        owner=OwnerAuthority.HKA,
        generation=Generation(4),
        provenance_refs=(
            ProvenanceRef("origin", OpaqueReference("hka-origin", "human-42")),
            ProvenanceRef(
                "content",
                OpaqueReference("content-sha256", hashlib.sha256(body.encode()).hexdigest()),
            ),
        ),
        policy_profile=PolicyProfile.HKA_RECOVERY,
    )
    port = _HkaVaultPort(descriptor)
    return HkaRecoveryAdapter(port), port, descriptor


def _authority() -> HkaGovernedWriteAuthority:
    return HkaGovernedWriteAuthority(OpaqueReference("hka-governed-write", "grant-42"))


def test_human_artifact_export_is_portable_and_provenance_complete() -> None:
    adapter, _port, descriptor = _fixture()

    exported = adapter.export(descriptor, "# Durable note\n\nA human-readable recovery representation.\n")

    assert exported.content == "# Durable note\n\nA human-readable recovery representation.\n"
    assert exported.identity == descriptor.identity
    assert exported.generation == descriptor.generation
    assert exported.provenance_refs == descriptor.provenance_refs
    assert exported.format == "text/markdown"
    assert exported.policy_profile is PolicyProfile.HKA_RECOVERY
    assert exported.integrity_digest == hashlib.sha256(exported.content.encode("utf-8")).hexdigest()


def test_human_artifact_export_preserves_portable_integrity_across_line_endings() -> None:
    adapter, _port, descriptor = _fixture()

    exported = adapter.export(
        descriptor,
        "# Durable note\r\n\r\nA human-readable recovery representation.\r\n",
    )

    assert exported.content.endswith("\r\n")
    assert exported.integrity_digest == next(
        item.reference.token
        for item in descriptor.provenance_refs
        if item.kind == "content"
    )


def test_hka_recovery_invokes_production_governed_write_after_verification() -> None:
    adapter, port, descriptor = _fixture()

    exported = adapter.export(descriptor, "# Durable note\n\nA human-readable recovery representation.\n")
    result = adapter.recover(exported, _authority())

    assert result.receipt is not None
    assert result.receipt.identity == descriptor.identity
    assert result.receipt.generation == descriptor.generation
    assert port.calls == ["stage", "verify", "governed_write"]
    assert port.production_writes == 1


def test_human_artifact_recovery_refuses_newer_generation_overwrite() -> None:
    adapter, port, descriptor = _fixture()
    port.current_generation = Generation(descriptor.generation.value + 1)

    exported = adapter.export(descriptor, "# Durable note\n\nA human-readable recovery representation.\n")
    result = adapter.recover(exported, _authority())

    assert result.receipt is None
    assert isinstance(result.conflict, HkaRecoveryConflict)
    assert result.conflict.owner_generation == Generation(5)
    assert result.conflict.exported_generation == descriptor.generation
    assert result.conflict.owner_identity == descriptor.identity
    assert result.conflict.export.identity == descriptor.identity
    assert port.calls == ["stage", "verify"]
    assert port.production_writes == 0

    racing_adapter, racing_port, racing_descriptor = _fixture()
    racing_port.racing_owner = HkaOwnerVersion(
        identity=racing_descriptor.identity,
        generation=Generation(5),
        representation_ref=OpaqueReference("hka-owner-representation", "newer-42"),
    )
    racing_export = racing_adapter.export(
        racing_descriptor,
        "# Durable note\n\nA human-readable recovery representation.\n",
    )
    raced = racing_adapter.recover(racing_export, _authority())

    assert isinstance(raced.conflict, HkaRecoveryConflict)
    assert raced.conflict.owner.representation_ref.token == "newer-42"
    assert racing_port.calls == ["stage", "verify", "governed_write"]
    assert racing_port.production_writes == 0


def test_hka_adapter_uses_governed_write_and_never_raw_delete_policy() -> None:
    adapter, port, _descriptor = _fixture()

    exported = adapter.export(_descriptor, "# Durable note\n\nA human-readable recovery representation.\n")
    result = adapter.recover(exported, _authority())

    assert result.receipt is not None
    assert result.receipt.policy_profile is PolicyProfile.HKA_RECOVERY
    assert port.production_writes == 1
    assert port.raw_delete_calls == 0
    assert "governed_write" in port.calls


def test_hka_recovery_consumes_export_on_a_clean_target_through_concrete_vault_bridge() -> None:
    source_adapter, _source_port, descriptor = _fixture()
    exported = source_adapter.export(descriptor, "# Durable note\n\nA human-readable recovery representation.\n")
    target_vault = DummyVaultPort()
    calls: list[str] = []

    def stage(vault_port: VaultPort, export: HkaRecoveryExport) -> HkaRecoveryStage:
        assert vault_port is target_vault
        calls.append("stage")
        return HkaRecoveryStage(export, OpaqueReference("hka-recovery-stage", "clean-stage-42"))

    def verify(vault_port: VaultPort, stage: HkaRecoveryStage) -> HkaRecoveryVerification:
        assert vault_port is target_vault
        calls.append("verify")
        return HkaRecoveryVerification(stage.stage_ref, stage.export.integrity_digest)

    def read_owner(vault_port: VaultPort, identity: ArtifactIdentity) -> HkaOwnerVersion:
        assert vault_port is target_vault
        calls.append("read_owner")
        return HkaOwnerVersion(identity, Generation(0), OpaqueReference("hka-owner-representation", "clean-42"))

    def governed_write(
        vault_port: VaultPort,
        stage: HkaRecoveryStage,
        verification: HkaRecoveryVerification,
        authority: HkaGovernedWriteAuthority,
    ) -> HkaRecoveryReceipt:
        calls.append("governed_write")
        assert vault_port is target_vault
        assert verification.integrity_digest == stage.export.integrity_digest
        assert authority == _authority()
        return HkaRecoveryReceipt(
            OpaqueReference("hka-governed-write-receipt", "clean-write-42"),
            stage.export.identity,
            stage.export.generation,
            stage.export.provenance_refs,
            stage.export.policy_profile,
        )

    target = HkaRecoveryAdapter(
        HkaRecoveryVaultPortAdapter(
            target_vault,
            stage_writer=stage,
            stage_verifier=verify,
            owner_version_reader=read_owner,
            governed_writer=governed_write,
        )
    )
    result = target.recover(exported, _authority())

    assert result.receipt is not None
    assert result.receipt.identity == exported.identity
    assert calls == ["stage", "verify", "read_owner", "governed_write"]
