from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from app.instance.filesystem_identity import (
    resolve_filesystem_root_identity,
    same_filesystem_root,
)
from app.instance.ownership_ledger import (
    LedgerCollisionError,
    LedgerError,
    LedgerSnapshot,
    LegacyOwner,
    OwnershipLedger,
)
from app.instance.vault_registry import RegistryError, RegistrySnapshot, VaultRegistryStore


_REQUIRED_CONSUMERS = frozenset({"api", "worker", "watcher", "heimdal-capture-watch"})
_BACKUP_SCHEMA = "agentic-pkm.instance-state-backup.v1"
_DEPLOYMENT_FENCE_SCHEMA = "agentic-pkm.instance-state-deployment-fence.v1"
_DEPLOYMENT_LEASE_SCHEMA = "agentic-pkm.host-deployment-lease.v3"
_DEPLOYMENT_COMPATIBILITY_BLOCK_SCHEMA = (
    "agentic-pkm.host-deployment-compatibility-block.v1"
)
_LEGACY_INVENTORY_SCHEMA = "agentic-pkm.legacy-owner-inventory.v1"
_QUIESCENCE_INVENTORY_SCHEMA = "agentic-pkm.host-deployment-quiescence.v2"
_FINAL_EXPORT_SEAL = os.urandom(32)


class InstanceStatePreflightError(RuntimeError):
    """Durable instance state cannot be consumed or recovered safely."""


@dataclass(frozen=True)
class DeploymentQuiescenceProof:
    """Validated, durable evidence that the host-wide writer inventory is stopped.

    This deliberately replaces boolean caller assertions and channel-only lists.
    Production proofs are bound to the private host-global deployment lease.
    """

    channel_id: str
    nonce: str
    inventory_digest: str
    lease_path: Path | None = None
    controller_pid: int | None = None
    controller_start_token: str | None = None
    owner_receipt_digest: str | None = None

    def require_valid(self, *, channel_id: str | None = None) -> None:
        if channel_id is not None and self.channel_id != channel_id:
            raise InstanceStatePreflightError("quiescence proof targets another channel")
        if self.lease_path is None:
            raise InstanceStatePreflightError("durable quiescence proof is required")
        try:
            payload = json.loads(self.lease_path.read_text(encoding="utf-8"))
            controller = payload.get("controller")
            expected_controller = None
            if self.controller_pid is not None or self.controller_start_token is not None:
                if self.controller_pid is None or self.controller_start_token is None:
                    raise ValueError
                expected_controller = {
                    "pid": self.controller_pid,
                    "start_token": self.controller_start_token,
                }
            if (
                payload.get("schema") != _DEPLOYMENT_LEASE_SCHEMA
                or payload.get("channel_id") != self.channel_id
                or payload.get("nonce") != self.nonce
                or payload.get("phase") != "proved"
                or payload.get("inventory_digest") != self.inventory_digest
                or payload.get("all_consumers_stopped") is not True
                or (expected_controller is not None and controller != expected_controller)
                or (
                    self.owner_receipt_digest is not None
                    and payload.get("owner_receipt_digest") != self.owner_receipt_digest
                )
            ):
                raise ValueError
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise InstanceStatePreflightError("durable quiescence proof is required") from exc

    def require_canonical_authority(
        self,
        *,
        channel_id: str,
        host_global_root: Path,
        owner_receipt_path: Path | None,
        legacy_path: Path | None = None,
    ) -> Mapping[str, object]:
        """Authenticate the complete host-global deployment authority in place."""

        root = Path(host_global_root).expanduser().resolve(strict=False)
        canonical_lease = (
            root / "deployment-public" / "deployment-host-global-lease.json"
        )
        canonical_compatibility_block = (
            root / "deployment-host-global-lease.json"
        )
        canonical_inventory = root / "deployment-quiescence-inventory.json"
        canonical_receipt = root / "legacy-owner-inventory.json"
        canonical_fence = root / f"deployment-{channel_id}-restart-fence.json"
        proof_lease = (
            None
            if self.lease_path is None
            else Path(self.lease_path).expanduser().resolve(strict=False)
        )
        receipt = (
            None
            if owner_receipt_path is None
            else Path(owner_receipt_path).expanduser().resolve(strict=False)
        )
        expected_legacy_path = (
            None
            if legacy_path is None
            else Path(legacy_path).expanduser().resolve(strict=False)
        )
        try:
            root_metadata = root.lstat()
            if (
                not stat.S_ISDIR(root_metadata.st_mode)
                or root_metadata.st_uid != os.geteuid()
                or root_metadata.st_mode & 0o777 != 0o700
                or proof_lease != canonical_lease
                or receipt != canonical_receipt
            ):
                raise ValueError
            self.require_valid(channel_id=channel_id)
            lease = _read_private_json(canonical_lease)
            compatibility_block = _read_private_json(
                canonical_compatibility_block
            )
            fence = _read_private_json(canonical_fence)
            inventory_bytes = _read_private_bytes(canonical_inventory)
            inventory = json.loads(inventory_bytes)
            owner_payload = _read_private_json(canonical_receipt)
            controller = {
                "pid": self.controller_pid,
                "start_token": self.controller_start_token,
            }
            empty_domains: dict[str, list[object]] = {
                domain: [] for domain in ("dev", "native", "prod", "test")
            }
            empty_digest = hashlib.sha256(
                json.dumps(
                    empty_domains, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
            source_evidence = owner_payload.get("source_evidence")
            receipt_payload = {
                key: value
                for key, value in owner_payload.items()
                if key != "receipt_digest"
            }
            receipt_digest = hashlib.sha256(
                json.dumps(
                    receipt_payload, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
            source_digest = hashlib.sha256(
                json.dumps(
                    source_evidence, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
            if (
                self.controller_pid is None
                or self.controller_start_token is None
                or self.owner_receipt_digest is None
                or lease.get("schema") != _DEPLOYMENT_LEASE_SCHEMA
                or lease.get("channel_id") != channel_id
                or lease.get("nonce") != self.nonce
                or lease.get("phase") != "proved"
                or lease.get("inventory_digest") != self.inventory_digest
                or lease.get("owner_receipt_digest") != self.owner_receipt_digest
                or lease.get("controller") != controller
                or lease.get("all_consumers_stopped") is not True
                or compatibility_block.get("schema")
                != _DEPLOYMENT_COMPATIBILITY_BLOCK_SCHEMA
                or compatibility_block.get("channel_id") != channel_id
                or compatibility_block.get("nonce") != self.nonce
                or compatibility_block.get("compatibility_v3_nonce")
                != self.nonce
                or compatibility_block.get("phase") != "proved"
                or compatibility_block.get("controller") != controller
                or compatibility_block.get("legacy_path")
                != lease.get("legacy_path")
                or compatibility_block.get("inventory_digest")
                != self.inventory_digest
                or compatibility_block.get("all_consumers_stopped")
                is not True
                or compatibility_block.get("owner_receipt_digest")
                != self.owner_receipt_digest
                or fence.get("schema") != _DEPLOYMENT_FENCE_SCHEMA
                or fence.get("channel_id") != channel_id
                or fence.get("deployment_nonce") != self.nonce
                or fence.get("controller") != controller
                or (
                    expected_legacy_path is not None
                    and Path(str(fence.get("legacy_path") or ""))
                    .expanduser()
                    .resolve(strict=False)
                    != expected_legacy_path
                )
                or hashlib.sha256(inventory_bytes).hexdigest() != self.inventory_digest
                or inventory.get("schema") != _QUIESCENCE_INVENTORY_SCHEMA
                or inventory.get("inventory_complete") is not True
                or inventory.get("all_consumers_stopped") is not True
                or inventory.get("probe_count") != 2
                or inventory.get("controller") != controller
                or inventory.get("domains") != empty_domains
                or inventory.get("snapshot_digests") != [empty_digest, empty_digest]
                or owner_payload.get("schema") != _LEGACY_INVENTORY_SCHEMA
                or owner_payload.get("inventory_complete") is not True
                or owner_payload.get("writers_drained") is not True
                or owner_payload.get("source_probe_count") != 2
                or owner_payload.get("validated_after_quiescence") is not True
                or not isinstance(source_evidence, dict)
                or source_evidence.get("owners") != owner_payload.get("owners")
                or owner_payload.get("source_digest") != source_digest
                or owner_payload.get("deployment_nonce") != self.nonce
                or owner_payload.get("controller") != controller
                or owner_payload.get("quiescence_inventory_digest")
                != self.inventory_digest
                or owner_payload.get("receipt_digest") != self.owner_receipt_digest
                or receipt_digest != self.owner_receipt_digest
            ):
                raise ValueError
        except (
            OSError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
            InstanceStatePreflightError,
        ) as exc:
            raise InstanceStatePreflightError(
                "canonical quiescence authority is required"
            ) from exc
        return owner_payload


@dataclass(frozen=True)
class InstanceStateLayout:
    root: Path
    channel_id: str
    registry_path: Path

    @classmethod
    def for_channel(cls, root: Path, channel_id: str) -> InstanceStateLayout:
        normalized = Path(root).expanduser().resolve(strict=False)
        app_root = normalized / "agentic-pkm"
        return cls(app_root, channel_id, app_root / "vault-registry.md")

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.require_existing()

    def require_existing(self) -> None:
        """Verify the mounted channel state root without creating or repairing it."""

        if not self.root.is_dir():
            raise InstanceStatePreflightError("instance-state mount/root is missing")
        metadata = self.root.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o777 != 0o700
        ):
            raise InstanceStatePreflightError("instance-state directory is not private")


@dataclass(frozen=True)
class LegacyExport:
    source_path: Path
    payload: bytes
    fingerprint: str


@dataclass(frozen=True)
class _FinalLegacyExport:
    source_path: Path
    payload: bytes
    fingerprint: str
    _authority: bytes


class LegacyRegistryFinalExport:
    """Quiescence-gated exact export of the legacy scalar authority."""

    def __init__(self, layout: InstanceStateLayout) -> None:
        self.layout = layout

    def capture_diagnostic_snapshot(self, legacy_path: Path) -> LegacyExport:
        return self._capture(legacy_path)

    def export_final_after_stop(
        self,
        legacy_path: Path,
        *,
        quiescence_proof: DeploymentQuiescenceProof | None,
        host_global_root: Path,
        owner_receipt_path: Path,
    ) -> _FinalLegacyExport:
        if quiescence_proof is None:
            raise InstanceStatePreflightError("durable quiescence proof is required")
        source_path = Path(legacy_path).expanduser().resolve(strict=False)
        quiescence_proof.require_canonical_authority(
            channel_id=self.layout.channel_id,
            host_global_root=host_global_root,
            owner_receipt_path=owner_receipt_path,
            legacy_path=source_path,
        )
        captured = self._capture(source_path)
        authority = self._authority_digest(
            source_path=captured.source_path,
            payload_digest=captured.fingerprint,
            quiescence_proof=quiescence_proof,
            host_global_root=host_global_root,
            owner_receipt_path=owner_receipt_path,
        )
        return _FinalLegacyExport(
            captured.source_path,
            captured.payload,
            captured.fingerprint,
            authority,
        )

    def import_final_export(
        self,
        export: object,
        *,
        quiescence_proof: DeploymentQuiescenceProof | None = None,
        host_global_root: Path | None = None,
        owner_receipt_path: Path | None = None,
    ) -> RegistrySnapshot:
        self._require_final_authority(
            export,
            quiescence_proof=quiescence_proof,
            host_global_root=host_global_root,
            owner_receipt_path=owner_receipt_path,
        )
        assert isinstance(export, _FinalLegacyExport)
        if self._capture(export.source_path).fingerprint != export.fingerprint:
            raise InstanceStatePreflightError("legacy registry changed after final export")
        self.layout.ensure()
        if self.layout.registry_path.exists():
            current = VaultRegistryStore(self.layout.registry_path).load()
            if current.revision > 0:
                raise InstanceStatePreflightError("registry import target is already populated")
        self.preserve_final_export(
            export,
            quiescence_proof=quiescence_proof,
            host_global_root=host_global_root,
            owner_receipt_path=owner_receipt_path,
        )
        self._require_final_authority(
            export,
            quiescence_proof=quiescence_proof,
            host_global_root=host_global_root,
            owner_receipt_path=owner_receipt_path,
        )
        if self._capture(export.source_path).fingerprint != export.fingerprint:
            raise InstanceStatePreflightError("legacy registry changed after final export")
        _atomic_private_write(self.layout.registry_path, export.payload)
        return VaultRegistryStore(self.layout.registry_path).load_or_migrate()

    def preserve_final_export(
        self,
        export: object,
        *,
        quiescence_proof: DeploymentQuiescenceProof | None = None,
        host_global_root: Path | None = None,
        owner_receipt_path: Path | None = None,
    ) -> Path:
        """Persist the post-stop legacy authority without changing registry authority."""

        self._require_final_authority(
            export,
            quiescence_proof=quiescence_proof,
            host_global_root=host_global_root,
            owner_receipt_path=owner_receipt_path,
        )
        assert isinstance(export, _FinalLegacyExport)
        if self._capture(export.source_path).fingerprint != export.fingerprint:
            raise InstanceStatePreflightError("legacy registry changed after final export")
        self.layout.ensure()
        target = self.layout.root / "legacy-final-export.md"
        _atomic_private_write(target, export.payload)
        _atomic_private_write(
            self.layout.root / "legacy-final-export.md.sha256",
            (export.fingerprint + "\n").encode("ascii"),
        )
        return target

    def _require_final_authority(
        self,
        export: object,
        *,
        quiescence_proof: DeploymentQuiescenceProof | None,
        host_global_root: Path | None,
        owner_receipt_path: Path | None,
    ) -> None:
        if (
            not isinstance(export, _FinalLegacyExport)
            or not isinstance(export._authority, bytes)
            or quiescence_proof is None
            or host_global_root is None
        ):
            raise InstanceStatePreflightError("final export authority is required")
        source_path = Path(export.source_path).expanduser().resolve(strict=False)
        payload_digest = hashlib.sha256(export.payload).hexdigest()
        if (
            export.source_path != source_path
            or export.fingerprint != payload_digest
        ):
            raise InstanceStatePreflightError("final export binding is invalid")
        quiescence_proof.require_canonical_authority(
            channel_id=self.layout.channel_id,
            host_global_root=host_global_root,
            owner_receipt_path=owner_receipt_path,
            legacy_path=source_path,
        )
        expected_authority = self._authority_digest(
            source_path=source_path,
            payload_digest=payload_digest,
            quiescence_proof=quiescence_proof,
            host_global_root=host_global_root,
            owner_receipt_path=owner_receipt_path,
        )
        if not hmac.compare_digest(export._authority, expected_authority):
            raise InstanceStatePreflightError("final export binding is invalid")

    def _authority_digest(
        self,
        *,
        source_path: Path,
        payload_digest: str,
        quiescence_proof: DeploymentQuiescenceProof,
        host_global_root: Path,
        owner_receipt_path: Path | None,
    ) -> bytes:
        evidence = {
            "channel_id": self.layout.channel_id,
            "controller_pid": quiescence_proof.controller_pid,
            "controller_start_token": quiescence_proof.controller_start_token,
            "host_global_root": str(
                Path(host_global_root).expanduser().resolve(strict=False)
            ),
            "inventory_digest": quiescence_proof.inventory_digest,
            "lease_path": (
                None
                if quiescence_proof.lease_path is None
                else str(
                    Path(quiescence_proof.lease_path)
                    .expanduser()
                    .resolve(strict=False)
                )
            ),
            "nonce": quiescence_proof.nonce,
            "owner_receipt_digest": quiescence_proof.owner_receipt_digest,
            "owner_receipt_path": (
                None
                if owner_receipt_path is None
                else str(
                    Path(owner_receipt_path).expanduser().resolve(strict=False)
                )
            ),
            "payload_digest": payload_digest,
            "source_path": str(source_path),
        }
        return hmac.digest(
            _FINAL_EXPORT_SEAL,
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            "sha256",
        )

    def _capture(self, legacy_path: Path) -> LegacyExport:
        path = Path(legacy_path).expanduser().resolve(strict=False)
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise InstanceStatePreflightError("legacy registry export source is unreadable") from exc
        return LegacyExport(path, payload, hashlib.sha256(payload).hexdigest())


@dataclass(frozen=True)
class InstanceStatePreflightReceipt:
    channel_id: str
    registry_path: str
    consumers: tuple[str, ...]


def preflight_instance_state(
    layout: InstanceStateLayout,
    *,
    consumer_paths: Mapping[str, Path],
) -> InstanceStatePreflightReceipt:
    if set(consumer_paths) != _REQUIRED_CONSUMERS:
        raise InstanceStatePreflightError("instance-state preflight must cover all consumers")
    layout.require_existing()
    expected = layout.registry_path.resolve(strict=False)
    resolved = {name: Path(path).expanduser().resolve(strict=False) for name, path in consumer_paths.items()}
    if set(resolved.values()) != {expected}:
        raise InstanceStatePreflightError("all instance-state consumers must resolve identically")
    store = VaultRegistryStore(layout.registry_path)
    if not layout.registry_path.is_file() and not (
        store.snapshot_path.is_file() and store.snapshot_checksum_path.is_file()
    ):
        raise InstanceStatePreflightError("instance-state registry producer has not initialized")
    try:
        store.load()
    except Exception as exc:
        raise InstanceStatePreflightError("registry is not durably readable and writable") from exc
    return InstanceStatePreflightReceipt(
        channel_id=layout.channel_id,
        registry_path=str(expected),
        consumers=tuple(sorted(resolved)),
    )


def validate_registry_disjoint_from_content(
    registry_path: Path,
    content_roots: Sequence[Path],
) -> None:
    registry = Path(registry_path).expanduser().resolve(strict=False)
    for candidate in content_roots:
        root = Path(candidate).expanduser().resolve(strict=False)
        try:
            registry.relative_to(root)
        except ValueError:
            continue
        raise InstanceStatePreflightError(
            "instance registry path cannot be owned by a content root"
        )


@dataclass(frozen=True)
class InstanceStateBackupReceipt:
    manifest_path: Path


@dataclass(frozen=True)
class InstanceStateRestoreReceipt:
    registry_checksum: str
    ownership_key_id: str
    ownership_generation: int


class InstanceStateBackup:
    """Verified prod backup/restore for channel state plus host ownership state."""

    def __init__(self, layout: InstanceStateLayout, ledger: OwnershipLedger) -> None:
        self.layout = layout
        self.ledger = ledger

    def create(
        self,
        backup_root: Path,
        *,
        quiescence_proof: DeploymentQuiescenceProof | None,
        owner_receipt_path: Path | None = None,
        require_materialized_owner_roots: bool = True,
    ) -> InstanceStateBackupReceipt:
        if quiescence_proof is None:
            raise InstanceStatePreflightError(
                "canonical quiescence authority is required"
            )
        owner_payload = quiescence_proof.require_canonical_authority(
            channel_id=self.layout.channel_id,
            host_global_root=self.ledger.root,
            owner_receipt_path=owner_receipt_path,
        )
        self.layout.require_existing()
        registry_store = VaultRegistryStore(self.layout.registry_path)
        destination = Path(backup_root).expanduser().resolve(strict=False)
        try:
            payloads = self.ledger.capture_backup_artifacts(
                capture_registry_artifacts=registry_store.capture_backup_artifacts,
            )
        except LedgerCollisionError as exc:
            raise InstanceStatePreflightError(
                "backup registry/ledger ownership is not unambiguous"
            ) from exc
        except (LedgerError, OSError, RegistryError) as exc:
            raise InstanceStatePreflightError(
                "backup registry/ledger capture failed"
            ) from exc
        final_export = self.layout.root / "legacy-final-export.md"
        final_checksum = self.layout.root / "legacy-final-export.md.sha256"
        if final_export.exists() != final_checksum.exists():
            raise InstanceStatePreflightError("final legacy export backup source is incomplete")
        if final_export.is_file():
            payloads["legacy-final-export.md"] = final_export.read_bytes()
            payloads["legacy-final-export.md.sha256"] = final_checksum.read_bytes()
        ledger, _ = self._verify_staged_backup(
            payloads=payloads,
            owner_payload=owner_payload,
            require_materialized_owner_roots=require_materialized_owner_roots,
        )
        checksums = {
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in payloads.items()
        }
        manifest = {
            "schema": _BACKUP_SCHEMA,
            "channel_id": self.layout.channel_id,
            "registry_checksum": checksums["vault-registry.md"],
            "ownership_key_id": ledger.key_id,
            "ownership_generation": ledger.generation,
            "checksums": checksums,
        }
        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(destination, 0o700)
        for name, payload in payloads.items():
            _atomic_private_write(destination / name, payload)
        manifest_path = destination / "manifest.json"
        _atomic_private_write(
            manifest_path,
            (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        )
        return InstanceStateBackupReceipt(manifest_path)

    def restore(
        self,
        backup_root: Path,
        *,
        quiescence_proof: DeploymentQuiescenceProof | None,
        owner_receipt_path: Path | None = None,
    ) -> InstanceStateRestoreReceipt:
        if quiescence_proof is None:
            raise InstanceStatePreflightError("durable quiescence proof is required")
        owner_payload = quiescence_proof.require_canonical_authority(
            channel_id=self.layout.channel_id,
            host_global_root=self.ledger.root,
            owner_receipt_path=owner_receipt_path,
        )
        source = Path(backup_root).expanduser().resolve(strict=False)
        required = {
            "manifest.json",
            "vault-registry.md",
            "vault-registry.md.last-good",
            "vault-registry.md.last-good.sha256",
            "vault-registry.md.legacy-export",
            "ownership-ledger.json",
            "ownership-key.json",
        }
        try:
            manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
            if manifest.get("schema") != _BACKUP_SCHEMA:
                raise ValueError
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise InstanceStatePreflightError("backup verification failed") from exc
        if manifest.get("channel_id") != self.layout.channel_id:
            raise InstanceStatePreflightError(
                "backup channel_id does not match restore target"
            )
        checksums = manifest.get("checksums")
        if not isinstance(checksums, dict):
            raise InstanceStatePreflightError("backup verification failed")
        optional_final = {
            "legacy-final-export.md",
            "legacy-final-export.md.sha256",
        }
        selected_optional = optional_final.intersection(checksums)
        if selected_optional and selected_optional != optional_final:
            raise InstanceStatePreflightError("backup final legacy export is incomplete")
        required |= selected_optional
        if not all((source / name).is_file() for name in required):
            raise InstanceStatePreflightError(
                "restore requires a complete ledger/key backup; keep the global fence "
                "until fenced re-key and ledger reconstruction complete"
            )
        payloads: dict[str, bytes] = {}
        try:
            for name in required - {"manifest.json"}:
                payload = (source / name).read_bytes()
                payloads[name] = payload
                actual = hashlib.sha256(payload).hexdigest()
                if checksums.get(name) != actual:
                    raise ValueError
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise InstanceStatePreflightError("backup verification failed") from exc
        # Restore is the mutating path: never skip a lease-less inventory
        # owner here. Restore already requires materialized roots, so the
        # candidate skip that keeps mount-blind backup creation green (#4371)
        # would only mask a staged ledger that lost a live lease.
        staged_ledger, global_live_owners = self._verify_staged_backup(
            payloads=payloads,
            owner_payload=owner_payload,
            skip_unadopted_owners=False,
        )
        manifest_key_id = manifest.get("ownership_key_id")
        manifest_generation = manifest.get("ownership_generation")
        has_manifest_key_id = "ownership_key_id" in manifest
        has_manifest_generation = "ownership_generation" in manifest
        if (
            manifest.get("registry_checksum") != checksums.get("vault-registry.md")
            or has_manifest_key_id != has_manifest_generation
            or (
                has_manifest_key_id
                and (
                    not isinstance(manifest_key_id, str)
                    or not isinstance(manifest_generation, int)
                    or isinstance(manifest_generation, bool)
                    or manifest_key_id != staged_ledger.key_id
                    or manifest_generation != staged_ledger.generation
                )
            )
        ):
            raise InstanceStatePreflightError(
                "backup key identity is inconsistent; keep the global fence until "
                "fenced re-key and ledger reconstruction complete"
            )
        self.layout.ensure()
        self.ledger.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.ledger.root, 0o700)
        registry_store = VaultRegistryStore(self.layout.registry_path)
        _atomic_private_write(
            registry_store.snapshot_path,
            payloads["vault-registry.md.last-good"],
        )
        _atomic_private_write(
            registry_store.snapshot_checksum_path,
            payloads["vault-registry.md.last-good.sha256"],
        )
        _atomic_private_write(
            registry_store.rollback_export_path,
            payloads["vault-registry.md.legacy-export"],
        )
        _atomic_private_write(self.ledger.path, payloads["ownership-ledger.json"])
        _atomic_private_write(self.ledger.key_path, payloads["ownership-key.json"])
        _atomic_private_write(self.layout.registry_path, payloads["vault-registry.md"])
        for name in sorted(selected_optional):
            _atomic_private_write(self.layout.root / name, payloads[name])
        if not selected_optional:
            (self.layout.root / "legacy-final-export.md").unlink(missing_ok=True)
            (self.layout.root / "legacy-final-export.md.sha256").unlink(missing_ok=True)
        restored_registry = registry_store.load()
        restored_ledger = self._require_registry_ledger_consistency(
            registry=restored_registry,
            ledger=self.ledger,
            global_live_owners=global_live_owners,
        )
        if (
            restored_ledger.key_id != staged_ledger.key_id
            or restored_ledger.generation != staged_ledger.generation
        ):
            raise InstanceStatePreflightError(
                "restored ownership key identity does not match the verified backup"
            )
        return InstanceStateRestoreReceipt(
            str(manifest["registry_checksum"]),
            restored_ledger.key_id,
            restored_ledger.generation,
        )

    def _verify_staged_backup(
        self,
        *,
        payloads: Mapping[str, bytes],
        owner_payload: Mapping[str, object],
        require_materialized_owner_roots: bool = True,
        skip_unadopted_owners: bool = True,
    ) -> tuple[LedgerSnapshot, tuple[LegacyOwner, ...]]:
        try:
            with tempfile.TemporaryDirectory(
                prefix="agentic-pkm-instance-state-verify-"
            ) as temporary_root:
                scratch_root = Path(temporary_root)
                scratch_layout = InstanceStateLayout.for_channel(
                    scratch_root / "instance-state",
                    self.layout.channel_id,
                )
                scratch_layout.ensure()
                scratch_ledger = OwnershipLedger(scratch_root / "host-global")
                scratch_ledger.root.mkdir(mode=0o700)
                for name, payload in payloads.items():
                    if name.startswith("ownership-"):
                        target = scratch_ledger.root / name
                    else:
                        target = scratch_layout.root / name
                    _atomic_private_write(target, payload)
                registry = VaultRegistryStore(scratch_layout.registry_path).load()
                global_live_owners = self._global_live_owners(
                    owner_payload=owner_payload,
                    registry=registry,
                    ledger=scratch_ledger,
                    require_materialized_owner_roots=(
                        require_materialized_owner_roots
                    ),
                    skip_unadopted_owners=skip_unadopted_owners,
                )
                ledger = self._require_registry_ledger_consistency(
                    registry=registry,
                    ledger=scratch_ledger,
                    global_live_owners=global_live_owners,
                    require_materialized_owner_roots=(
                        require_materialized_owner_roots
                    ),
                )
                return ledger, global_live_owners
        except InstanceStatePreflightError as exc:
            # Surface the underlying cause in the top-level message (#4371):
            # the chained traceback is not always visible in step output, and
            # the generic fence text alone sends readers to the wrong
            # subsystem.
            raise InstanceStatePreflightError(
                f"backup registry/ledger consistency verification failed: {exc};"
                " keep the global fence until fenced re-key and ledger "
                "reconstruction complete"
            ) from exc
        except Exception as exc:
            raise InstanceStatePreflightError(
                "backup registry/ledger consistency verification failed "
                f"({type(exc).__name__}); keep the global fence until fenced "
                "re-key and ledger reconstruction complete"
            ) from exc

    def _require_registry_ledger_consistency(
        self,
        *,
        registry: RegistrySnapshot,
        ledger: OwnershipLedger,
        global_live_owners: Sequence[LegacyOwner],
        require_materialized_owner_roots: bool = True,
    ) -> LedgerSnapshot:
        try:
            return ledger.require_registry_consistency(
                channel_id=self.layout.channel_id,
                registrations={
                    binding_id: (
                        Path(registration.path)
                        if require_materialized_owner_roots
                        else None
                    )
                    for binding_id, registration in registry.registrations.items()
                },
                tombstones={
                    binding_id: (
                        Path(tombstone.path)
                        if require_materialized_owner_roots
                        else None
                    )
                    for binding_id, tombstone in registry.removal_tombstones.items()
                },
                transfer_lineage=tuple(
                    {
                        "ownership_transfer_id": item.ownership_transfer_id,
                        "source_channel_id": item.source_channel_id,
                        "source_binding_id": item.source_binding_id,
                        "destination_channel_id": item.destination_channel_id,
                        "destination_binding_id": item.destination_binding_id,
                    }
                    for item in registry.transfer_lineage
                ),
                global_live_owners=global_live_owners,
                require_materialized_roots=require_materialized_owner_roots,
            )
        except LedgerError as exc:
            raise InstanceStatePreflightError(
                f"registry/ledger consistency verification failed: {exc}"
            ) from exc

    def _global_live_owners(
        self,
        *,
        owner_payload: Mapping[str, object],
        registry: RegistrySnapshot,
        ledger: OwnershipLedger,
        require_materialized_owner_roots: bool = True,
        skip_unadopted_owners: bool = True,
    ) -> tuple[LegacyOwner, ...]:
        raw_owners = owner_payload.get("owners")
        if not isinstance(raw_owners, list):
            raise InstanceStatePreflightError(
                "canonical global live-owner inventory is invalid: the drained "
                "owner receipt carries no owners list"
            )
        owners: list[LegacyOwner] = []
        for index, item in enumerate(raw_owners):
            if not isinstance(item, dict):
                raise InstanceStatePreflightError(
                    "canonical global live-owner inventory is invalid: "
                    f"owners[{index}] is not an owner entry"
                )
            channel_id = str(item.get("channel_id") or "").strip()
            raw_root = str(item.get("root") or "").strip()
            binding_id = str(item.get("vault_binding_id") or "").strip()
            if not channel_id:
                raise InstanceStatePreflightError(
                    "canonical global live-owner inventory is invalid: "
                    f"owners[{index}].channel_id is missing"
                )
            if not raw_root or not Path(raw_root).expanduser().is_absolute():
                raise InstanceStatePreflightError(
                    "canonical global live-owner inventory is invalid: "
                    f"owners[{index}].root is missing or not absolute"
                )
            if not require_materialized_owner_roots and not binding_id:
                raise InstanceStatePreflightError(
                    "canonical global live-owner inventory is invalid: "
                    f"owners[{index}].vault_binding_id is missing"
                )
            # Owner-root materialization is not re-checked here (#4371): the
            # host-side inventory producer proved every root twice and the
            # receipt is digest-bound to the deployment lease, while this
            # verification may run in another mount namespace (the
            # deployment-finish container). A root that is not locally
            # visible resolves to canonical-path identity, whose fingerprints
            # cannot match an inode-fingerprinted lease minted where the root
            # was materialized — such an owner therefore resolves to no lease
            # and is handled by the unadopted-candidate rule in
            # resolve_live_owner_bindings below.
            root = Path(raw_root).expanduser().resolve(strict=False)
            if (
                require_materialized_owner_roots
                and channel_id == self.layout.channel_id
            ):
                for registration in registry.registrations.values():
                    if same_filesystem_root(
                        resolve_filesystem_root_identity(root),
                        resolve_filesystem_root_identity(registration.path),
                    ):
                        binding_id = registration.vault_binding_id
                        break
            owners.append(LegacyOwner(channel_id, binding_id, root))
        try:
            # Config-derived inventories (materialized-roots mode) may name
            # candidates the ledger never adopted after legacy bootstrap
            # completed; when such a root is also invisible to this process,
            # the verifier cannot adjudicate it and the ledger holds no lease
            # for it, so it is excluded from lease consistency. A lease-less
            # owner whose root is locally materialized stays fail-closed, and
            # lease-only payloads always carry binding ids.
            resolved = ledger.resolve_live_owner_bindings(
                owners,
                skip_unadopted=(
                    skip_unadopted_owners and require_materialized_owner_roots
                ),
            )
        except LedgerError as exc:
            raise InstanceStatePreflightError(
                f"canonical global live-owner binding identity is invalid: {exc}"
            ) from exc
        if len({owner.vault_binding_id for owner in resolved}) != len(resolved):
            raise InstanceStatePreflightError(
                "canonical global live-owner inventory repeats a binding identity"
            )
        return resolved


def _atomic_private_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _read_private_bytes(path: Path) -> bytes:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o777 != 0o600
    ):
        raise ValueError
    return path.read_bytes()


def _read_private_json(path: Path) -> dict[str, object]:
    payload = json.loads(_read_private_bytes(path))
    if not isinstance(payload, dict):
        raise ValueError
    return payload


__all__ = [
    "InstanceStateBackup",
    "InstanceStateBackupReceipt",
    "DeploymentQuiescenceProof",
    "InstanceStateLayout",
    "InstanceStatePreflightError",
    "InstanceStatePreflightReceipt",
    "InstanceStateRestoreReceipt",
    "LegacyExport",
    "LegacyRegistryFinalExport",
    "preflight_instance_state",
    "validate_registry_disjoint_from_content",
]
