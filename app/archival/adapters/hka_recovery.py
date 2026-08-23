"""Portable HKA recovery through the owner-native VaultPort governed-write seam.

The adapter owns only portable values and transition ordering. HKA remains the
sole source for identity, generation, staging, and authority; this module has
no registry, generation ledger, or durable content store.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, Protocol

from app.archival.contracts import (
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
from app.ports.vault_port import VaultPort


ADAPTER_ID = "hka_recovery"
_FORMAT = "text/markdown"


@dataclass(frozen=True)
class HkaGovernedWriteAuthority:
    """Opaque GOV/HKA approval consumed only by the production write seam."""

    reference: OpaqueReference

    def __post_init__(self) -> None:
        if not isinstance(self.reference, OpaqueReference):
            raise ValueError("HKA recovery authority must be an opaque reference")
        if self.reference.namespace != "hka-governed-write":
            raise ValueError("HKA recovery requires production governed-write authority")


@dataclass(frozen=True)
class HkaRecoveryExport:
    """Portable, human-readable ArtifactContract material; never HKA authority."""

    identity: ArtifactIdentity
    artifact_class: ArtifactClass
    derivation: DerivationClass
    durability: DurabilityClass
    owner: OwnerAuthority
    generation: Generation
    provenance_refs: tuple[ProvenanceRef, ...]
    format: str
    policy_profile: PolicyProfile
    content: str
    integrity_digest: str

    def __post_init__(self) -> None:
        _require_export_contract(self)


@dataclass(frozen=True)
class HkaRecoveryStage:
    """Owner-native staged descriptor; a stage is explicitly non-authoritative."""

    export: HkaRecoveryExport
    stage_ref: OpaqueReference

    def __post_init__(self) -> None:
        if not isinstance(self.export, HkaRecoveryExport):
            raise ValueError("HKA recovery stage requires a portable export")
        if not isinstance(self.stage_ref, OpaqueReference):
            raise ValueError("HKA recovery stage requires an opaque stage reference")
        if self.stage_ref.namespace != "hka-recovery-stage":
            raise ValueError("HKA recovery stage must be owner-native")


@dataclass(frozen=True)
class HkaRecoveryVerification:
    """Integrity readback for one exact staged representation."""

    stage_ref: OpaqueReference
    integrity_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.stage_ref, OpaqueReference):
            raise ValueError("HKA recovery verification requires an opaque stage reference")
        if not isinstance(self.integrity_digest, str) or len(self.integrity_digest) != 64:
            raise ValueError("HKA recovery verification requires a SHA-256 integrity digest")


@dataclass(frozen=True)
class HkaOwnerVersion:
    """Read-only owner-native side of a recovery conflict."""

    identity: ArtifactIdentity
    generation: Generation
    representation_ref: OpaqueReference

    def __post_init__(self) -> None:
        if not isinstance(self.identity, ArtifactIdentity) or not isinstance(self.generation, Generation):
            raise ValueError("HKA owner version requires identity and generation")
        if not isinstance(self.representation_ref, OpaqueReference):
            raise ValueError("HKA owner version requires an opaque representation reference")


@dataclass(frozen=True)
class HkaRecoveryReceipt:
    """Owner-native proof that the production governed write succeeded."""

    receipt_ref: OpaqueReference
    identity: ArtifactIdentity
    generation: Generation
    provenance_refs: tuple[ProvenanceRef, ...]
    policy_profile: PolicyProfile

    def __post_init__(self) -> None:
        if not isinstance(self.receipt_ref, OpaqueReference):
            raise ValueError("HKA recovery receipt requires an opaque receipt reference")
        if not isinstance(self.identity, ArtifactIdentity) or not isinstance(self.generation, Generation):
            raise ValueError("HKA recovery receipt requires identity and generation")
        if not isinstance(self.provenance_refs, tuple) or not self.provenance_refs:
            raise ValueError("HKA recovery receipt requires provenance")
        if self.policy_profile is not PolicyProfile.HKA_RECOVERY:
            raise ValueError("HKA recovery receipt must retain HKA recovery policy")


@dataclass(frozen=True)
class HkaRecoveryConflict:
    """Typed, owner-resolvable conflict that keeps both representations available."""

    owner: HkaOwnerVersion
    export: HkaRecoveryExport
    stage: HkaRecoveryStage

    @property
    def owner_identity(self) -> ArtifactIdentity:
        return self.owner.identity

    @property
    def owner_generation(self) -> Generation:
        return self.owner.generation

    @property
    def exported_generation(self) -> Generation:
        return self.export.generation


@dataclass(frozen=True)
class HkaRecoveryResult:
    """A governed-write receipt or a conflict, never synthetic authority state."""

    receipt: HkaRecoveryReceipt | None = None
    conflict: HkaRecoveryConflict | None = None

    def __post_init__(self) -> None:
        if (self.receipt is None) == (self.conflict is None):
            raise ValueError("HKA recovery result must contain exactly one terminal outcome")


class HkaNewerGenerationConflict(RuntimeError):
    """Raised by the atomic owner seam when a newer generation wins a race."""

    def __init__(self, owner: HkaOwnerVersion) -> None:
        super().__init__("HKA recovery cannot overwrite a newer owner generation")
        self.owner = owner


class HkaRecoveryVaultPort(VaultPort, Protocol):
    """Existing VaultPort extended by owner-native HKA recovery operations."""

    contract: str
    owner_subsystem: str

    def stage_hka_recovery(self, export: HkaRecoveryExport) -> HkaRecoveryStage: ...
    def verify_hka_recovery(self, stage: HkaRecoveryStage) -> HkaRecoveryVerification: ...
    def read_hka_owner_version(self, identity: ArtifactIdentity) -> HkaOwnerVersion: ...
    def governed_write_hka_recovery(self, stage: HkaRecoveryStage, verification: HkaRecoveryVerification, authority: HkaGovernedWriteAuthority) -> HkaRecoveryReceipt: ...


class HkaOwnerVersionReader(Protocol):
    """Existing HKA owner lookup behind its VaultPort implementation."""

    def __call__(self, vault_port: VaultPort, identity: ArtifactIdentity) -> HkaOwnerVersion: ...


class HkaRecoveryStager(Protocol):
    """Owner-native durable stage creation behind the existing VaultPort seam."""

    def __call__(self, vault_port: VaultPort, export: HkaRecoveryExport) -> HkaRecoveryStage: ...


class HkaRecoveryStageVerifier(Protocol):
    """Owner-native stage readback; it must not confer HKA authority."""

    def __call__(self, vault_port: VaultPort, stage: HkaRecoveryStage) -> HkaRecoveryVerification: ...


class HkaProductionGovernedWriter(Protocol):
    """The production HKA write seam; it owns mutation and its GOV receipt."""

    def __call__(self, vault_port: VaultPort, stage: HkaRecoveryStage, verification: HkaRecoveryVerification, authority: HkaGovernedWriteAuthority) -> HkaRecoveryReceipt: ...


class HkaRecoveryVaultPortAdapter(HkaRecoveryVaultPort):
    """Concrete bridge from the existing VaultPort to HKA recovery operations.

    The bridge stores no recovery state: the owner receives every stage and the
    injected production writer remains the only authority-changing call.
    """

    contract = "VaultPort"
    owner_subsystem = "HKA"

    def __init__(self, vault_port: VaultPort, *, stage_writer: HkaRecoveryStager, stage_verifier: HkaRecoveryStageVerifier, owner_version_reader: HkaOwnerVersionReader, governed_writer: HkaProductionGovernedWriter) -> None:
        self._vault = vault_port
        self._stage_writer = stage_writer
        self._stage_verifier = stage_verifier
        self._read_owner_version = owner_version_reader
        self._governed_writer = governed_writer

    def stage_hka_recovery(self, export: HkaRecoveryExport) -> HkaRecoveryStage:
        _require_export_contract(export)
        stage = self._stage_writer(self._vault, export)
        if not isinstance(stage, HkaRecoveryStage) or stage.export != export:
            raise ValueError("HKA stage writer differs from the portable export")
        return stage

    def verify_hka_recovery(self, stage: HkaRecoveryStage) -> HkaRecoveryVerification:
        return self._stage_verifier(self._vault, stage)

    def read_hka_owner_version(self, identity: ArtifactIdentity) -> HkaOwnerVersion:
        owner = self._read_owner_version(self._vault, identity)
        if not isinstance(owner, HkaOwnerVersion) or owner.identity != identity:
            raise ValueError("HKA owner lookup differs from recovery identity")
        return owner

    def governed_write_hka_recovery(self, stage: HkaRecoveryStage, verification: HkaRecoveryVerification, authority: HkaGovernedWriteAuthority) -> HkaRecoveryReceipt:
        return self._governed_writer(self._vault, stage, verification, authority)

    def read_note(self, path: Path):  # type: ignore[no-untyped-def]
        return self._vault.read_note(path)

    def ensure_uuid(self, note, *, expected_mtime_ns: int | None = None):  # type: ignore[no-untyped-def]
        return self._vault.ensure_uuid(note, expected_mtime_ns=expected_mtime_ns)

    def write_frontmatter(self, path: Path, frontmatter: dict[str, Any], body: str, *, expected_mtime_ns: int | None = None, expected_version: str | None = None) -> bool:
        return self._vault.write_frontmatter(path, frontmatter, body, expected_mtime_ns=expected_mtime_ns, expected_version=expected_version)

    def rename_note(self, uuid_value: str, new_path: Path) -> None:
        self._vault.rename_note(uuid_value, new_path)

    def delete_note(self, path: Path, *, uuid_value: str | None = None) -> None:
        self._vault.delete_note(path, uuid_value=uuid_value)

    def upsert_note_object(self, path: Path, frontmatter: dict[str, Any], body: str, fm_changed: bool, body_changed: bool) -> None:
        self._vault.upsert_note_object(path, frontmatter, body, fm_changed, body_changed)

    def append_inbox_item(self, message: str, *, vault_path: Path | None = None, uri: str | None = None) -> None:
        self._vault.append_inbox_item(message, vault_path=vault_path, uri=uri)


class HkaRecoveryAdapter:
    """Thin portable adapter over the owner-native VaultPort governed-write seam."""

    def __init__(self, vault_port: HkaRecoveryVaultPort) -> None:
        if getattr(vault_port, "contract", None) != "VaultPort" or getattr(vault_port, "owner_subsystem", None) != "HKA":
            raise ValueError("HKA recovery must use the existing HKA VaultPort seam")
        self._vault = vault_port

    def export(self, artifact: ArtifactDescriptor, content: str, format: str = _FORMAT) -> HkaRecoveryExport:
        """Create portable material without assigning it HKA authority."""
        _require_hka_artifact(artifact)
        content_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        _require_content_provenance(artifact, content_digest)
        return HkaRecoveryExport(artifact.identity, artifact.artifact_class, artifact.derivation, artifact.durability, artifact.owner, artifact.generation, artifact.provenance_refs, format, artifact.policy_profile, content, content_digest)

    def recover(self, export: HkaRecoveryExport, authority: HkaGovernedWriteAuthority) -> HkaRecoveryResult:
        """Stage and verify one portable export before the atomic governed write."""
        _require_export_contract(export)
        if not isinstance(authority, HkaGovernedWriteAuthority):
            raise ValueError("HKA recovery requires governed-write authority")
        stage = self._vault.stage_hka_recovery(export)
        verification = self._vault.verify_hka_recovery(stage)
        self._require_verified_stage(stage, verification)
        owner = self._vault.read_hka_owner_version(export.identity)
        self._require_owner_identity(owner, export)
        if owner.generation.value > export.generation.value:
            return HkaRecoveryResult(conflict=HkaRecoveryConflict(owner, export, stage))
        try:
            receipt = self._vault.governed_write_hka_recovery(stage, verification, authority)
        except HkaNewerGenerationConflict as exc:
            self._require_owner_identity(exc.owner, export)
            return HkaRecoveryResult(conflict=HkaRecoveryConflict(exc.owner, export, stage))
        self._require_receipt(receipt, export)
        return HkaRecoveryResult(receipt=receipt)

    @staticmethod
    def _require_verified_stage(stage: HkaRecoveryStage, verification: HkaRecoveryVerification) -> None:
        if verification.stage_ref != stage.stage_ref or verification.integrity_digest != stage.export.integrity_digest:
            raise ValueError("HKA recovery staging verification differs from the exported representation")

    @staticmethod
    def _require_owner_identity(owner: HkaOwnerVersion, export: HkaRecoveryExport) -> None:
        if not isinstance(owner, HkaOwnerVersion) or owner.identity != export.identity:
            raise ValueError("HKA owner version differs from the exported artifact identity")

    @staticmethod
    def _require_receipt(receipt: HkaRecoveryReceipt, export: HkaRecoveryExport) -> None:
        if not isinstance(receipt, HkaRecoveryReceipt):
            raise ValueError("HKA governed write returned no owner-native receipt")
        if receipt.identity != export.identity or receipt.generation != export.generation or receipt.provenance_refs != export.provenance_refs or receipt.policy_profile is not PolicyProfile.HKA_RECOVERY:
            raise ValueError("HKA governed-write receipt differs from the verified export")


def _require_export_contract(export: HkaRecoveryExport) -> None:
    if not isinstance(export.identity, ArtifactIdentity) or export.identity.owner is not OwnerAuthority.HKA:
        raise ValueError("HKA recovery export requires HKA artifact identity")
    if export.artifact_class is not ArtifactClass.HUMAN or export.derivation is not DerivationClass.SOURCE or export.durability is not DurabilityClass.DURABLE or export.owner is not OwnerAuthority.HKA or export.policy_profile is not PolicyProfile.HKA_RECOVERY:
        raise ValueError("HKA recovery export differs from the HKA ArtifactContract")
    if not isinstance(export.provenance_refs, tuple) or not export.provenance_refs or not all(isinstance(item, ProvenanceRef) for item in export.provenance_refs):
        raise ValueError("HKA recovery export requires typed provenance")
    if export.format != _FORMAT or not isinstance(export.content, str) or not export.content.strip():
        raise ValueError("HKA recovery export must be human-readable text/markdown")
    if export.integrity_digest != hashlib.sha256(export.content.encode("utf-8")).hexdigest():
        raise ValueError("HKA recovery export integrity digest differs from content")


def _require_hka_artifact(artifact: ArtifactDescriptor) -> None:
    if not isinstance(artifact, ArtifactDescriptor):
        raise ValueError("HKA recovery requires an ArtifactContract descriptor")
    if artifact.identity.owner is not OwnerAuthority.HKA or artifact.artifact_class is not ArtifactClass.HUMAN or artifact.derivation is not DerivationClass.SOURCE or artifact.durability is not DurabilityClass.DURABLE or artifact.owner is not OwnerAuthority.HKA or artifact.policy_profile is not PolicyProfile.HKA_RECOVERY:
        raise ValueError("HKA recovery must preserve the HKA ArtifactContract policy")


def _require_content_provenance(artifact: ArtifactDescriptor, content_digest: str) -> None:
    matches = tuple(item.reference.token for item in artifact.provenance_refs if item.kind == "content" and item.reference.namespace == "content-sha256")
    if matches != (content_digest,):
        raise ValueError("HKA recovery content differs from HKA provenance")


__all__ = ["ADAPTER_ID", "HkaGovernedWriteAuthority", "HkaNewerGenerationConflict", "HkaOwnerVersion", "HkaOwnerVersionReader", "HkaProductionGovernedWriter", "HkaRecoveryAdapter", "HkaRecoveryConflict", "HkaRecoveryExport", "HkaRecoveryReceipt", "HkaRecoveryResult", "HkaRecoveryStage", "HkaRecoveryStageVerifier", "HkaRecoveryStager", "HkaRecoveryVaultPort", "HkaRecoveryVaultPortAdapter", "HkaRecoveryVerification"]
