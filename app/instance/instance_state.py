from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from app.instance.ownership_ledger import OwnershipLedger
from app.instance.vault_registry import RegistrySnapshot, VaultRegistryStore


_REQUIRED_CONSUMERS = frozenset({"api", "worker", "watcher", "heimdal-capture-watch"})
_BACKUP_SCHEMA = "agentic-pkm.instance-state-backup.v1"


class InstanceStatePreflightError(RuntimeError):
    """Durable instance state cannot be consumed or recovered safely."""


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
        writers_drained: bool,
        old_api_stopped: bool,
        restart_fence_active: bool,
    ) -> LegacyExport:
        if not (writers_drained and old_api_stopped and restart_fence_active):
            raise InstanceStatePreflightError(
                "legacy writers must be drained and stopped behind a restart fence"
            )
        return self._capture(legacy_path)

    def import_final_export(self, export: LegacyExport) -> RegistrySnapshot:
        if self._capture(export.source_path).fingerprint != export.fingerprint:
            raise InstanceStatePreflightError("legacy registry changed after final export")
        self.layout.ensure()
        if self.layout.registry_path.exists():
            current = VaultRegistryStore(self.layout.registry_path).load()
            if current.revision > 0:
                raise InstanceStatePreflightError("registry import target is already populated")
        _atomic_private_write(self.layout.registry_path, export.payload)
        return VaultRegistryStore(self.layout.registry_path).load_or_migrate()

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
    layout.ensure()
    expected = layout.registry_path.resolve(strict=False)
    resolved = {name: Path(path).expanduser().resolve(strict=False) for name, path in consumer_paths.items()}
    if set(resolved.values()) != {expected}:
        raise InstanceStatePreflightError("all instance-state consumers must resolve identically")
    try:
        VaultRegistryStore(layout.registry_path).load()
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


class InstanceStateBackup:
    """Verified prod backup/restore for channel state plus host ownership state."""

    def __init__(self, layout: InstanceStateLayout, ledger: OwnershipLedger) -> None:
        self.layout = layout
        self.ledger = ledger

    def create(self, backup_root: Path) -> InstanceStateBackupReceipt:
        self.layout.ensure()
        registry_store = VaultRegistryStore(self.layout.registry_path)
        registry_store.load()
        self.ledger.load()
        destination = Path(backup_root).expanduser().resolve(strict=False)
        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(destination, 0o700)
        artifacts = {
            "vault-registry.md": self.layout.registry_path,
            "vault-registry.md.last-good": registry_store.snapshot_path,
            "vault-registry.md.last-good.sha256": registry_store.snapshot_checksum_path,
            "vault-registry.md.legacy-export": registry_store.rollback_export_path,
            "ownership-ledger.json": self.ledger.path,
            "ownership-key.json": self.ledger.key_path,
        }
        checksums: dict[str, str] = {}
        for name, source in artifacts.items():
            if not source.is_file():
                raise InstanceStatePreflightError(f"backup source is incomplete: {name}")
            payload = source.read_bytes()
            _atomic_private_write(destination / name, payload)
            checksums[name] = hashlib.sha256(payload).hexdigest()
        manifest = {
            "schema": _BACKUP_SCHEMA,
            "channel_id": self.layout.channel_id,
            "registry_checksum": checksums["vault-registry.md"],
            "checksums": checksums,
        }
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
        live_channels: Sequence[str],
    ) -> InstanceStateRestoreReceipt:
        if live_channels:
            raise InstanceStatePreflightError("restore requires all live channels to be stopped")
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
        if not all((source / name).is_file() for name in required):
            raise InstanceStatePreflightError("restore requires a complete ledger/key backup")
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
        try:
            checksums = manifest["checksums"]
            for name in required - {"manifest.json"}:
                actual = hashlib.sha256((source / name).read_bytes()).hexdigest()
                if checksums.get(name) != actual:
                    raise ValueError
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise InstanceStatePreflightError("backup verification failed") from exc
        self.layout.ensure()
        self.ledger.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.ledger.root, 0o700)
        registry_store = VaultRegistryStore(self.layout.registry_path)
        _atomic_private_write(
            registry_store.snapshot_path,
            (source / "vault-registry.md.last-good").read_bytes(),
        )
        _atomic_private_write(
            registry_store.snapshot_checksum_path,
            (source / "vault-registry.md.last-good.sha256").read_bytes(),
        )
        _atomic_private_write(
            registry_store.rollback_export_path,
            (source / "vault-registry.md.legacy-export").read_bytes(),
        )
        _atomic_private_write(
            self.ledger.path, (source / "ownership-ledger.json").read_bytes()
        )
        _atomic_private_write(
            self.ledger.key_path, (source / "ownership-key.json").read_bytes()
        )
        _atomic_private_write(
            self.layout.registry_path, (source / "vault-registry.md").read_bytes()
        )
        registry_store.load()
        self.ledger.load()
        return InstanceStateRestoreReceipt(str(manifest["registry_checksum"]))


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


__all__ = [
    "InstanceStateBackup",
    "InstanceStateBackupReceipt",
    "InstanceStateLayout",
    "InstanceStatePreflightError",
    "InstanceStatePreflightReceipt",
    "InstanceStateRestoreReceipt",
    "LegacyExport",
    "LegacyRegistryFinalExport",
    "preflight_instance_state",
    "validate_registry_disjoint_from_content",
]
