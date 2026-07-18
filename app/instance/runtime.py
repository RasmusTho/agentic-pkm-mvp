from __future__ import annotations

import argparse
import fcntl
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterator
from uuid import uuid4

import yaml

from app.instance.filesystem_identity import (
    resolve_filesystem_root_identity,
    same_filesystem_root,
)
from app.instance.instance_state import (
    InstanceStateLayout,
    preflight_instance_state,
    validate_registry_disjoint_from_content,
)
from app.instance.ownership_ledger import (
    LedgerCollisionError,
    LedgerError,
    LedgerSnapshot,
    OwnershipLedger,
)
from app.instance.vault_registry import (
    AppLocalSettings,
    AppLocalSettingsStore,
    CapabilityNotReadyError,
    RegistryError,
    RemovalTombstone,
    TransferLineage,
    VaultRegistration,
    VaultRegistryStore,
)


@dataclass(frozen=True)
class LifecycleActivationProof:
    consumer_floor: bool = False

    @classmethod
    def for_test_activation(cls) -> LifecycleActivationProof:
        return cls(consumer_floor=True)


@dataclass(frozen=True)
class TransferActivationProof:
    foreground_ownership_floor: bool = False

    @classmethod
    def for_test_activation(cls) -> TransferActivationProof:
        return cls(foreground_ownership_floor=True)


class InstanceRegistryRuntime:
    """MVR-01B mechanical runtime; production authority remains legacy scalar."""

    def __init__(
        self,
        layout: InstanceStateLayout,
        ledger: OwnershipLedger,
        *,
        legacy_path: Path | None = None,
    ) -> None:
        self.layout = layout
        self.layout.ensure()
        self.registry = VaultRegistryStore(layout.registry_path)
        self.ledger = ledger
        self._legacy_path = legacy_path or (layout.root / "legacy-app-local.md")

    @classmethod
    def for_paths(
        cls,
        layout: InstanceStateLayout,
        host_global_root: Path,
    ) -> InstanceRegistryRuntime:
        return cls(layout, OwnershipLedger(Path(host_global_root).resolve(strict=False)))

    def bootstrap_env_binding(
        self,
        *,
        vault_root: Path,
        watcher_vault_path: Path,
    ) -> VaultRegistration:
        with self._bootstrap_locked():
            return self._bootstrap_env_binding_locked(
                vault_root=vault_root,
                watcher_vault_path=watcher_vault_path,
            )

    def _bootstrap_env_binding_locked(
        self,
        *,
        vault_root: Path,
        watcher_vault_path: Path,
    ) -> VaultRegistration:
        root_identity = resolve_filesystem_root_identity(vault_root)
        watcher_identity = resolve_filesystem_root_identity(watcher_vault_path)
        if not same_filesystem_root(root_identity, watcher_identity):
            raise RegistryError("conflicting bootstrap roots")
        current = self.registry.load()
        validate_registry_disjoint_from_content(
            self.layout.registry_path,
            [Path(root_identity.canonical_path)]
            + [Path(item.path) for item in current.registrations.values()],
        )
        for registration in current.registrations.values():
            if same_filesystem_root(
                resolve_filesystem_root_identity(registration.path), root_identity
            ):
                return registration
        if current.registrations:
            raise CapabilityNotReadyError("MVR-01C authority cutover seals second registration")
        registration = self._new_registration(Path(root_identity.canonical_path))
        self.ledger.reserve(
            channel_id=self.layout.channel_id,
            vault_binding_id=registration.vault_binding_id,
            root=Path(registration.path),
            allow_same_channel_nested=False,
        )
        try:
            self.registry.register(registration, expected_revision=current.revision)
        except Exception:
            # A retry can recover a prepared lease only when the registry commit exists;
            # otherwise leaving it pending is safer than allowing a conflicting owner.
            raise
        self.ledger.activate(registration.vault_binding_id)
        return registration

    @contextmanager
    def _bootstrap_locked(self) -> Iterator[None]:
        lock_path = self.layout.root / "bootstrap.lock"
        descriptor = os.open(
            lock_path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "a+b", closefd=True) as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def prepare_nested_registration(self, child_root: Path) -> VaultRegistration:
        child = Path(child_root).expanduser()
        identity = resolve_filesystem_root_identity(child)
        current = self.registry.load()
        validate_registry_disjoint_from_content(
            self.layout.registry_path,
            [Path(identity.canonical_path)]
            + [Path(item.path) for item in current.registrations.values()],
        )
        for item in current.registrations.values():
            if same_filesystem_root(resolve_filesystem_root_identity(item.path), identity):
                raise RegistryError("registry path identity collision")
        registration = self._new_registration(Path(identity.canonical_path))
        self.ledger.reserve(
            channel_id=self.layout.channel_id,
            vault_binding_id=registration.vault_binding_id,
            root=Path(registration.path),
            allow_same_channel_nested=True,
        )
        self.registry.register(registration, expected_revision=current.revision)
        self.ledger.activate(registration.vault_binding_id)
        return registration

    def production_register(self, path: Path, *, producer: str) -> VaultRegistration:
        del path, producer
        raise CapabilityNotReadyError("MVR-01C authority cutover seals production registration")

    def prepare_previous_scalar_image(self, legacy_path: Path) -> None:
        self._legacy_path = Path(legacy_path).expanduser().resolve(strict=False)
        # Loading proves that the rollback image remains readable without changing it.
        AppLocalSettingsStore(self._legacy_path).load()

    def production_read(self) -> AppLocalSettings:
        return AppLocalSettingsStore(self._legacy_path).load()

    def transfer_to(
        self,
        destination: InstanceRegistryRuntime,
        vault_binding_id: str,
        *,
        proof: TransferActivationProof | None = None,
        crash_after: str | None = None,
    ) -> str:
        if proof is None or not proof.foreground_ownership_floor:
            raise CapabilityNotReadyError("MVR-05C foreground ownership floor is required")
        source_snapshot = self.registry.load()
        source = source_snapshot.registrations.get(vault_binding_id)
        if source is None:
            raise RegistryError(f"unknown vault_binding_id: {vault_binding_id}")
        destination_binding_id = f"binding-{uuid4()}"
        reservation = self.ledger.begin_transfer(
            source_binding_id=vault_binding_id,
            destination_channel_id=destination.layout.channel_id,
            destination_binding_id=destination_binding_id,
        )
        destination_snapshot = destination.registry.load()
        destination_registration = replace(
            source,
            vault_binding_id=reservation.destination_binding_id,
            ref=f"transfer:{reservation.destination_binding_id}",
        )
        lineage = destination_snapshot.transfer_lineage + (
            TransferLineage(
                source_binding_id=source.vault_binding_id,
                destination_binding_id=destination_registration.vault_binding_id,
                local_instance_id=source.local_instance_id,
                vault_id=source.vault_id,
                source_channel_id=self.layout.channel_id,
                destination_channel_id=destination.layout.channel_id,
                source_registry_revision=source_snapshot.revision + 1,
                destination_registry_revision=destination_snapshot.revision + 1,
                ownership_transfer_id=reservation.transfer_id,
            ),
        )
        registrations = dict(destination_snapshot.registrations)
        registrations[destination_registration.vault_binding_id] = destination_registration
        destination.registry.commit_state(
            registrations=registrations,
            transfer_lineage=lineage,
            expected_revision=destination_snapshot.revision,
        )
        if crash_after == "destination_commit":
            raise RuntimeError("injected crash after destination_commit")
        return self.recover_transfer(destination)

    def recover_transfer(self, destination: InstanceRegistryRuntime) -> str:
        transfer = self.ledger.load().transfer
        if transfer is None:
            lineage = destination.registry.load().transfer_lineage
            if not lineage:
                raise LedgerError("no transfer reservation is recoverable")
            return lineage[-1].destination_binding_id
        if transfer.destination_channel_id != destination.layout.channel_id:
            raise LedgerError("transfer destination channel does not match")
        source_snapshot = self.registry.load()
        destination_snapshot = destination.registry.load()
        destination_registration = destination_snapshot.registrations.get(
            transfer.destination_binding_id
        )
        source_registration = source_snapshot.registrations.get(transfer.source_binding_id)
        if destination_registration is None:
            if source_registration is None:
                raise LedgerError("transfer state has no recoverable registration")
            destination_registration = replace(
                source_registration,
                vault_binding_id=transfer.destination_binding_id,
                ref=f"transfer:{transfer.destination_binding_id}",
            )
            registrations = dict(destination_snapshot.registrations)
            registrations[destination_registration.vault_binding_id] = destination_registration
            lineage = destination_snapshot.transfer_lineage + (
                TransferLineage(
                    source_binding_id=transfer.source_binding_id,
                    destination_binding_id=transfer.destination_binding_id,
                    local_instance_id=source_registration.local_instance_id,
                    vault_id=source_registration.vault_id,
                    source_channel_id=transfer.source_channel_id,
                    destination_channel_id=transfer.destination_channel_id,
                    source_registry_revision=source_snapshot.revision + 1,
                    destination_registry_revision=destination_snapshot.revision + 1,
                    ownership_transfer_id=transfer.transfer_id,
                ),
            )
            destination.registry.commit_state(
                registrations=registrations,
                transfer_lineage=lineage,
                expected_revision=destination_snapshot.revision,
            )
        if source_registration is not None:
            registrations = dict(source_snapshot.registrations)
            del registrations[transfer.source_binding_id]
            tombstones = dict(source_snapshot.removal_tombstones)
            tombstones[transfer.source_binding_id] = _tombstone(source_registration)
            self.registry.commit_state(
                registrations=registrations,
                removal_tombstones=tombstones,
                expected_revision=source_snapshot.revision,
            )
        self.ledger.activate_transfer()
        return transfer.destination_binding_id

    def relocate(
        self,
        vault_binding_id: str,
        destination: Path,
        *,
        proof: LifecycleActivationProof | None = None,
    ) -> VaultRegistration:
        del vault_binding_id, destination
        if proof is None or not proof.consumer_floor:
            raise CapabilityNotReadyError("MVR-06C consumer effect-lease floor is required")
        raise CapabilityNotReadyError("MVR-06C relocation remains dormant")

    def remove(
        self,
        vault_binding_id: str,
        *,
        proof: LifecycleActivationProof | None = None,
    ) -> RemovalTombstone:
        if proof is None or not proof.consumer_floor:
            raise CapabilityNotReadyError("MVR-06B consumer drain floor is required")
        current = self.registry.load()
        registration = current.registrations.get(vault_binding_id)
        if registration is None:
            raise RegistryError(f"unknown vault_binding_id: {vault_binding_id}")
        registrations = dict(current.registrations)
        del registrations[vault_binding_id]
        tombstones = dict(current.removal_tombstones)
        retired = _tombstone(registration)
        tombstones[vault_binding_id] = retired
        self.registry.commit_state(
            registrations=registrations,
            removal_tombstones=tombstones,
            expected_revision=current.revision,
        )
        self.ledger.release_to_tombstone(vault_binding_id)
        return retired

    def reactivate_removed(
        self,
        root: Path,
        *,
        proof: LifecycleActivationProof | None = None,
    ) -> VaultRegistration:
        if proof is None or not proof.consumer_floor:
            raise CapabilityNotReadyError("MVR-06B consumer drain floor is required")
        current = self.registry.load()
        matched: RemovalTombstone | None = None
        for tombstone in current.removal_tombstones.values():
            try:
                self.ledger.reactivate(
                    tombstone.vault_binding_id,
                    channel_id=self.layout.channel_id,
                    root=root,
                )
                matched = tombstone
                break
            except LedgerCollisionError:
                continue
        if matched is None:
            raise LedgerCollisionError("root does not match immutable predecessor lineage")
        registration = VaultRegistration(
            vault_binding_id=matched.vault_binding_id,
            ref=matched.ref,
            path=str(Path(root).expanduser().resolve(strict=False)),
            vault_id=matched.vault_id,
            local_instance_id=matched.local_instance_id,
            extensions={"contentEpoch": matched.content_epoch + 1},
        )
        registrations = dict(current.registrations)
        registrations[registration.vault_binding_id] = registration
        self.registry.commit_state(
            registrations=registrations,
            expected_revision=current.revision,
        )
        return registration

    def rotate_ledger_key(self, *, crash_after: str | None = None) -> LedgerSnapshot:
        return self.ledger.rotate_key(crash_after=crash_after)

    def require_initialized(self, vault_binding_id: str) -> VaultRegistration:
        registration = self.registry.lookup(vault_binding_id)
        if registration is None:
            raise RegistryError(f"unknown vault_binding_id: {vault_binding_id}")
        if registration.vault_id is None:
            raise CapabilityNotReadyError("uninitialized binding is read-only")
        return registration

    def complete_initialization(
        self,
        vault_binding_id: str,
        *,
        vault_id: str,
        local_instance_id: str,
    ) -> VaultRegistration:
        current = self.registry.lookup(vault_binding_id)
        if current is None:
            raise RegistryError(f"unknown vault_binding_id: {vault_binding_id}")
        if current.local_instance_id != local_instance_id:
            raise RegistryError("local clone identity does not match binding")
        updated = replace(
            current,
            vault_id=vault_id,
            extensions={**current.extensions, "status": "initialized"},
        )
        self.registry.update_registration(updated)
        return updated

    def _new_registration(self, root: Path) -> VaultRegistration:
        vault_id, local_instance_id = _read_vault_identity(root)
        identity = resolve_filesystem_root_identity(root)
        binding_id = f"binding-{uuid4()}"
        return VaultRegistration(
            vault_binding_id=binding_id,
            ref=f"path:{identity.canonical_path}",
            path=identity.canonical_path,
            vault_id=vault_id,
            local_instance_id=local_instance_id or f"local-{uuid4()}",
            extensions={
                "status": "initialized" if vault_id is not None else "uninitialized",
                "contentEpoch": 1,
                "provenance": "legacy_env_bootstrap",
            },
        )


def _read_vault_identity(root: Path) -> tuple[str | None, str | None]:
    def frontmatter(path: Path) -> dict[str, object]:
        if not path.is_file():
            return {}
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            return {}
        parts = text.split("---", 2)
        value = yaml.safe_load(parts[1]) or {}
        return value if isinstance(value, dict) else {}

    shared = frontmatter(root / "settings" / "vault.md")
    local = frontmatter(root / "settings" / "local.md")
    vault_id = str(shared.get("vaultId") or "").strip() or None
    local_instance_id = str(local.get("localInstanceId") or "").strip() or None
    return vault_id, local_instance_id


def _tombstone(registration: VaultRegistration) -> RemovalTombstone:
    epoch = registration.extensions.get("contentEpoch", 1)
    return RemovalTombstone(
        vault_binding_id=registration.vault_binding_id,
        ref=registration.ref,
        path=registration.path,
        vault_id=registration.vault_id,
        local_instance_id=registration.local_instance_id,
        content_epoch=epoch if isinstance(epoch, int) and epoch >= 1 else 1,
    )


def _read_revision(registry_path: Path, consumer: str) -> int:
    if consumer not in {"api", "worker", "watcher", "heimdal-capture-watch"}:
        raise RegistryError("unknown instance-state consumer")
    snapshot = VaultRegistryStore(registry_path).load()
    print(
        json.dumps(
            {
                "consumer": consumer,
                "revision": snapshot.revision,
                "path_identity": str(registry_path.resolve(strict=False)),
            },
            sort_keys=True,
        )
    )
    return 0


def _preflight_runtime(
    *,
    channel: str,
    instance_state_root: Path,
    host_global_root: Path,
    consumer: str,
) -> int:
    consumers = {"api", "worker", "watcher", "heimdal-capture-watch"}
    if consumer not in consumers:
        raise RegistryError("unknown instance-state consumer")
    layout = InstanceStateLayout.for_channel(instance_state_root, channel)
    configured_roots = [
        value
        for name in ("VAULT_ROOT", f"VAULT_ROOT_{channel.upper()}")
        if (value := os.getenv(name, "").strip())
    ]
    # Reject a content-owned registry override before creating any state there.
    validate_registry_disjoint_from_content(
        layout.registry_path,
        [Path(value) for value in configured_roots],
    )
    preflight_instance_state(
        layout,
        consumer_paths={name: layout.registry_path for name in consumers},
    )
    runtime = InstanceRegistryRuntime.for_paths(layout, host_global_root)
    runtime.ledger.load()
    known_roots = [Path(item.path) for item in runtime.registry.load().registrations.values()]
    validate_registry_disjoint_from_content(
        layout.registry_path,
        [Path(value) for value in configured_roots] + known_roots,
    )
    if configured_roots:
        watcher_root = os.getenv("WATCHER_VAULT_PATH", "").strip() or configured_roots[0]
        registration = runtime.bootstrap_env_binding(
            vault_root=Path(configured_roots[0]),
            watcher_vault_path=Path(watcher_root),
        )
        binding_id: str | None = registration.vault_binding_id
    else:
        binding_id = None
    print(
        json.dumps(
            {
                "channel": channel,
                "consumer": consumer,
                "registry_path": str(layout.registry_path),
                "vault_binding_id": binding_id,
            },
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    read = subparsers.add_parser("read-revision")
    read.add_argument("--registry-path", type=Path, required=True)
    read.add_argument("--consumer", required=True)
    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--channel", required=True)
    preflight.add_argument("--instance-state-root", type=Path, required=True)
    preflight.add_argument("--host-global-root", type=Path, required=True)
    preflight.add_argument("--consumer", required=True)
    args = parser.parse_args(argv)
    if args.command == "read-revision":
        return _read_revision(args.registry_path, args.consumer)
    if args.command == "preflight":
        return _preflight_runtime(
            channel=args.channel,
            instance_state_root=args.instance_state_root,
            host_global_root=args.host_global_root,
            consumer=args.consumer,
        )
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "InstanceRegistryRuntime",
    "LifecycleActivationProof",
    "TransferActivationProof",
]
