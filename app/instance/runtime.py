from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Iterator, Mapping
from uuid import uuid4

import yaml

from app.instance.filesystem_identity import (
    resolve_filesystem_root_identity,
    same_filesystem_root,
)
from app.instance.instance_state import (
    DeploymentQuiescenceProof,
    InstanceStateBackup,
    InstanceStateLayout,
    InstanceStatePreflightError,
    LegacyRegistryFinalExport,
    preflight_instance_state,
    validate_registry_disjoint_from_content,
)
from app.instance.ownership_ledger import (
    LegacyOwner,
    LedgerError,
    LedgerSnapshot,
    OwnershipLedger,
)
from app.instance.vault_registry import (
    AppLocalSettings,
    AppLocalSettingsStore,
    CapabilityNotReadyError,
    RegistryError,
    RegistrySnapshot,
    RemovalTombstone,
    VaultRegistration,
    VaultRegistryStore,
)


class InstanceRegistryRuntime:
    """MVR-01B mechanical runtime; production authority remains legacy scalar."""

    def __init__(
        self,
        layout: InstanceStateLayout,
        ledger: OwnershipLedger,
        *,
        legacy_path: Path | None = None,
        initialize_layout: bool = True,
    ) -> None:
        self.layout = layout
        if initialize_layout:
            self.layout.ensure()
        else:
            self.layout.require_existing()
        self.registry = VaultRegistryStore(layout.registry_path)
        self.ledger = ledger
        self._legacy_path = legacy_path or (layout.root / "legacy-app-local.md")

    @classmethod
    def for_paths(
        cls,
        layout: InstanceStateLayout,
        host_global_root: Path,
        *,
        initialize_layout: bool = True,
    ) -> InstanceRegistryRuntime:
        return cls(
            layout,
            OwnershipLedger(Path(host_global_root).resolve(strict=False)),
            initialize_layout=initialize_layout,
        )

    def bootstrap_env_binding(
        self,
        *,
        vault_root: Path,
        watcher_vault_path: Path,
    ) -> VaultRegistration:
        self._require_established_ownership(self.registry.load())
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
        self._require_established_ownership(current)
        validate_registry_disjoint_from_content(
            self.layout.registry_path,
            [Path(root_identity.canonical_path)]
            + [Path(item.path) for item in current.registrations.values()],
        )
        for registration in current.registrations.values():
            if same_filesystem_root(
                resolve_filesystem_root_identity(registration.path), root_identity
            ):
                self.ledger.recover_or_require_active(
                    registration.vault_binding_id,
                    channel_id=self.layout.channel_id,
                    root=Path(root_identity.canonical_path),
                )
                return registration
        for tombstone in current.removal_tombstones.values():
            if same_filesystem_root(
                resolve_filesystem_root_identity(tombstone.path), root_identity
            ):
                raise CapabilityNotReadyError(
                    "MVR-06B consumer drain floor seals tombstone reactivation"
                )
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

    def _require_established_ownership(self, current: RegistrySnapshot) -> None:
        if current.revision > 0:
            self.ledger.require_existing()

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
        del child_root
        raise CapabilityNotReadyError("MVR-01C authority cutover seals second registration")

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
    ) -> str:
        del destination, vault_binding_id
        raise CapabilityNotReadyError("MVR-05C foreground ownership floor is required")

    def recover_transfer(self, destination: InstanceRegistryRuntime) -> str:
        del destination
        raise CapabilityNotReadyError("MVR-05C foreground ownership floor is required")

    def relocate(
        self,
        vault_binding_id: str,
        destination: Path,
    ) -> VaultRegistration:
        del vault_binding_id, destination
        raise CapabilityNotReadyError("MVR-06C consumer effect-lease floor is required")

    def remove(
        self,
        vault_binding_id: str,
    ) -> RemovalTombstone:
        del vault_binding_id
        raise CapabilityNotReadyError("MVR-06B consumer drain floor is required")

    def reactivate_removed(
        self,
        root: Path,
    ) -> VaultRegistration:
        del root
        raise CapabilityNotReadyError("MVR-06B consumer drain floor is required")

    def rotate_ledger_key(
        self,
        *,
        quiescence_proof: DeploymentQuiescenceProof | None = None,
        legacy_owner_inventory_path: Path | None = None,
        crash_after: str | None = None,
    ) -> LedgerSnapshot:
        """Rotate only inside the existing lease-bound all-owner drain fence."""

        if quiescence_proof is None:
            raise InstanceStatePreflightError("durable quiescence proof is required")
        if legacy_owner_inventory_path is None:
            raise InstanceStatePreflightError("complete drained legacy-owner inventory is required")
        expected_lease_path = _deployment_lease_path(self.ledger.root).resolve(strict=False)
        proof_lease_path = (
            None
            if quiescence_proof.lease_path is None
            else Path(quiescence_proof.lease_path).expanduser().resolve(strict=False)
        )
        inventory_path = Path(legacy_owner_inventory_path).expanduser().resolve(strict=False)
        ownership_root = self.ledger.root.expanduser().resolve(strict=False)

        def require_rotation_authority(
            current: LedgerSnapshot, live_roots: Mapping[str, Path]
        ) -> None:
            if (
                proof_lease_path != expected_lease_path
                or inventory_path.parent != ownership_root
                or quiescence_proof.controller_pid is None
                or quiescence_proof.controller_start_token is None
                or quiescence_proof.owner_receipt_digest is None
            ):
                raise InstanceStatePreflightError(
                    "key rotation authority is not bound to this host-global ownership root"
                )
            quiescence_proof.require_valid(channel_id=self.layout.channel_id)
            expected_controller = {
                "pid": quiescence_proof.controller_pid,
                "start_token": quiescence_proof.controller_start_token,
            }
            try:
                lease_metadata = expected_lease_path.lstat()
                lease = json.loads(expected_lease_path.read_text(encoding="utf-8"))
                if (
                    not stat.S_ISREG(lease_metadata.st_mode)
                    or lease_metadata.st_uid != os.geteuid()
                    or lease_metadata.st_mode & 0o777 != 0o600
                    or lease.get("schema") != _DEPLOYMENT_LEASE_SCHEMA
                    or lease.get("channel_id") != self.layout.channel_id
                    or lease.get("nonce") != quiescence_proof.nonce
                    or lease.get("phase") != "proved"
                    or lease.get("inventory_digest") != quiescence_proof.inventory_digest
                    or lease.get("all_consumers_stopped") is not True
                    or lease.get("controller") != expected_controller
                    or lease.get("owner_receipt_digest")
                    != quiescence_proof.owner_receipt_digest
                ):
                    raise ValueError
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                raise InstanceStatePreflightError(
                    "durable quiescence proof is required for key rotation"
                ) from exc
            fence = _read_deployment_fence(ownership_root, self.layout.channel_id)
            if (
                fence.get("deployment_nonce") != quiescence_proof.nonce
                or fence.get("controller") != lease.get("controller")
            ):
                raise InstanceStatePreflightError(
                    "key rotation quiescence proof does not match the active restart fence"
                )
            owners = _load_legacy_owner_inventory(
                inventory_path,
                registry=self.registry.load(),
                channel=self.layout.channel_id,
                quiescence_proof=quiescence_proof,
            )
            represented = {(owner.channel_id, owner.vault_binding_id) for owner in owners}
            live = {(lease.channel_id, binding_id) for binding_id, lease in current.leases.items()}
            owner_by_binding = {owner.vault_binding_id: owner for owner in owners}
            if (
                represented != live
                or any(
                    not same_filesystem_root(
                        resolve_filesystem_root_identity(owner_by_binding[binding_id].root),
                        resolve_filesystem_root_identity(live_root),
                    )
                    for binding_id, live_root in live_roots.items()
                )
            ):
                raise InstanceStatePreflightError(
                    "complete drained legacy-owner inventory does not match live ownership"
                )

        return self.ledger.rotate_key(
            precondition=require_rotation_authority,
            crash_after=crash_after,
        )

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
    if not instance_state_root.is_dir() or not host_global_root.is_dir():
        raise RegistryError("instance-state and host-global mounts must already exist")
    if _deployment_lease_path(host_global_root).exists():
        raise RegistryError("host-global deployment lease blocks every runtime consumer")
    if _deployment_fence_path(host_global_root, channel).exists():
        raise RegistryError("channel restart is fenced pending instance-state finalization")
    preflight_instance_state(
        layout,
        consumer_paths={name: layout.registry_path for name in consumers},
    )
    runtime = InstanceRegistryRuntime.for_paths(
        layout,
        host_global_root,
        initialize_layout=False,
    )
    ledger = runtime.ledger.require_existing()
    if not ledger.legacy_bootstrap_complete:
        raise RegistryError("host-global legacy owner inventory bootstrap is incomplete")
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


_DEPLOYMENT_FENCE_SCHEMA = "agentic-pkm.instance-state-deployment-fence.v1"
_LEGACY_INVENTORY_SCHEMA = "agentic-pkm.legacy-owner-inventory.v1"
_LEGACY_INVENTORY_SOURCE_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_DEPLOYMENT_LEASE_SCHEMA = "agentic-pkm.host-deployment-lease.v2"
_QUIESCENCE_INVENTORY_SCHEMA = "agentic-pkm.host-deployment-quiescence.v2"
_CONTROLLER_START_TOKEN_RE = re.compile(r"^(?:linux|darwin):[0-9a-f]{64}$")


def _deployment_fence_path(host_global_root: Path, channel: str) -> Path:
    return Path(host_global_root) / f"deployment-{channel}-restart-fence.json"


def _deployment_lease_path(host_global_root: Path) -> Path:
    return Path(host_global_root) / "deployment-host-global-lease.json"


def _assert_mount_root(path: Path, label: str) -> Path:
    root = Path(path).expanduser().resolve(strict=False)
    if not root.is_dir():
        raise InstanceStatePreflightError(f"{label} mount is missing")
    metadata = root.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
        raise InstanceStatePreflightError(f"{label} mount ownership is unsafe")
    return root


def _write_private_json(path: Path, payload: dict[str, object]) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=True) as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _replace_private_json(path: Path, payload: dict[str, object]) -> None:
    """Atomically replace an established private JSON authority artifact."""

    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o777 != 0o600
    ):
        raise InstanceStatePreflightError("private deployment authority file is unsafe")
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _read_deployment_fence(host_global_root: Path, channel: str) -> dict[str, object]:
    path = _deployment_fence_path(host_global_root, channel)
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o777 != 0o600
        ):
            raise ValueError
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != _DEPLOYMENT_FENCE_SCHEMA
            or payload.get("channel_id") != channel
        ):
            raise ValueError
        return payload
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise InstanceStatePreflightError("valid channel restart fence is required") from exc


def _begin_instance_state_deployment(
    *,
    channel: str,
    instance_state_root: Path,
    host_global_root: Path,
    legacy_path: Path,
    controller_pid: int,
    controller_start_token: str,
) -> dict[str, object]:
    """Install the restart fence before any legacy writer is stopped."""

    state_mount = _assert_mount_root(instance_state_root, "instance-state")
    ownership_root = _assert_mount_root(host_global_root, "host-global")
    if controller_pid <= 0 or _CONTROLLER_START_TOKEN_RE.fullmatch(controller_start_token) is None:
        raise InstanceStatePreflightError("valid deployment controller identity is required")
    os.chmod(ownership_root, 0o700)
    layout = InstanceStateLayout.for_channel(state_mount, channel)
    layout.ensure()
    source = Path(legacy_path).expanduser().resolve(strict=False)
    diagnostic_fingerprint: str | None = None
    if source.is_file():
        diagnostic_fingerprint = LegacyRegistryFinalExport(
            layout
        ).capture_diagnostic_snapshot(source).fingerprint
    lease_path = _deployment_lease_path(ownership_root)
    nonce = uuid4().hex
    lease: dict[str, object] = {
        "schema": _DEPLOYMENT_LEASE_SCHEMA,
        "channel_id": channel,
        "nonce": nonce,
        "phase": "claimed",
        "controller": {
            "pid": controller_pid,
            "start_token": controller_start_token,
        },
    }
    if lease_path.exists():
        raise InstanceStatePreflightError("another host-global deployment lease is active")
    _write_private_json(lease_path, lease)
    payload: dict[str, object] = {
        "schema": _DEPLOYMENT_FENCE_SCHEMA,
        "channel_id": channel,
        "deployment_nonce": nonce,
        "controller": {
            "pid": controller_pid,
            "start_token": controller_start_token,
        },
        "legacy_path": str(source),
        "diagnostic_fingerprint": diagnostic_fingerprint,
    }
    fence_path = _deployment_fence_path(ownership_root, channel)
    if fence_path.exists():
        lease_path.unlink(missing_ok=True)
        existing = _read_deployment_fence(ownership_root, channel)
        if existing.get("legacy_path") != str(source):
            raise InstanceStatePreflightError("existing restart fence targets another legacy store")
        return existing
    _write_private_json(fence_path, payload)
    return payload


def _prove_instance_state_quiescence(
    *, channel: str, host_global_root: Path, inventory_path: Path
) -> DeploymentQuiescenceProof:
    """Bind two-pass all-domain stopped inventory evidence to the host lease."""
    root = _assert_mount_root(host_global_root, "host-global")
    lease_path = _deployment_lease_path(root)
    try:
        lease = json.loads(lease_path.read_text(encoding="utf-8"))
        inventory_file = Path(inventory_path)
        inventory_metadata = inventory_file.lstat()
        if (
            not stat.S_ISREG(inventory_metadata.st_mode)
            or inventory_metadata.st_uid != os.geteuid()
            or inventory_metadata.st_mode & 0o777 != 0o600
        ):
            raise ValueError
        inventory_bytes = inventory_file.read_bytes()
        inventory = json.loads(inventory_bytes)
        domains = inventory.get("domains")
        controller = lease.get("controller")
        inventory_controller = inventory.get("controller")
        empty_domains: dict[str, list[object]] = {
            domain: [] for domain in ("dev", "native", "prod", "test")
        }
        empty_digest = hashlib.sha256(
            json.dumps(empty_domains, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if (
            lease.get("schema") != _DEPLOYMENT_LEASE_SCHEMA
            or lease.get("channel_id") != channel
            or lease.get("phase") != "claimed"
            or not isinstance(lease.get("nonce"), str)
            or not isinstance(controller, dict)
            or not isinstance(controller.get("pid"), int)
            or _CONTROLLER_START_TOKEN_RE.fullmatch(
                str(controller.get("start_token") or "")
            )
            is None
            or inventory.get("schema") != _QUIESCENCE_INVENTORY_SCHEMA
            or inventory.get("inventory_complete") is not True
            or inventory.get("all_consumers_stopped") is not True
            or inventory.get("probe_count") != 2
            or inventory_controller != controller
            or domains != empty_domains
            or inventory.get("snapshot_digests") != [empty_digest, empty_digest]
        ):
            raise ValueError
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise InstanceStatePreflightError("complete two-pass host-wide quiescence inventory is required") from exc
    digest = hashlib.sha256(inventory_bytes).hexdigest()
    lease |= {"phase": "proved", "inventory_digest": digest, "all_consumers_stopped": True}
    _replace_private_json(lease_path, lease)
    proof_path = root / "deployment-quiescence-proof.json"
    controller = lease["controller"]
    if not isinstance(controller, dict):
        raise InstanceStatePreflightError("valid deployment controller identity is required")
    proof_payload: dict[str, object] = {
        "channel_id": channel,
        "nonce": str(lease["nonce"]),
        "inventory_digest": digest,
        "lease_path": str(lease_path),
        "controller": controller,
    }
    proof_path.unlink(missing_ok=True)
    _write_private_json(proof_path, proof_payload)
    return DeploymentQuiescenceProof(
        channel,
        str(lease["nonce"]),
        digest,
        lease_path,
        int(controller["pid"]),
        str(controller["start_token"]),
    )


def _canonical_json_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _legacy_owner_receipt_digest(payload: Mapping[str, object]) -> str:
    return _canonical_json_digest(
        {key: value for key, value in payload.items() if key != "receipt_digest"}
    )


def _load_legacy_owner_inventory_payload(inventory_path: Path) -> dict[str, object]:
    try:
        inventory = Path(inventory_path)
        metadata = inventory.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o777 != 0o600
        ):
            raise ValueError
        payload = json.loads(inventory.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError
        source_evidence = payload.get("source_evidence")
        owners = payload.get("owners")
        if (
            payload.get("schema") != _LEGACY_INVENTORY_SCHEMA
            or payload.get("inventory_complete") is not True
            or payload.get("writers_drained") is not True
            or payload.get("source_probe_count") != 2
            or payload.get("validated_after_quiescence") is not True
            or not isinstance(source_evidence, dict)
            or not isinstance(owners, list)
            or source_evidence.get("owners") != owners
            or not isinstance(source_evidence.get("docker"), list)
            or not isinstance(source_evidence.get("config"), list)
            or not isinstance(source_evidence.get("owner_identities"), list)
            or any(
                not isinstance(item, str)
                or (
                    item != "docker:empty"
                    and _LEGACY_INVENTORY_SOURCE_DIGEST_RE.fullmatch(item) is None
                )
                for item in source_evidence["docker"]
            )
            or any(
                not isinstance(item, str)
                or _LEGACY_INVENTORY_SOURCE_DIGEST_RE.fullmatch(item) is None
                for item in source_evidence["config"]
            )
            or payload.get("source_digest") != _canonical_json_digest(source_evidence)
        ):
            raise ValueError
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise InstanceStatePreflightError(
            "complete drained legacy-owner inventory is required"
        ) from exc
    return payload


def _bind_legacy_owner_inventory_to_proof(
    *,
    inventory_path: Path,
    quiescence_proof: DeploymentQuiescenceProof,
    channel: str,
    host_global_root: Path,
) -> DeploymentQuiescenceProof:
    """Bind the drained-owner receipt to the already-proved deployment lease."""

    ownership_root = Path(host_global_root).expanduser().resolve(strict=False)
    inventory = Path(inventory_path).expanduser().resolve(strict=False)
    lease_path = _deployment_lease_path(ownership_root).resolve(strict=False)
    proof_lease_path = (
        None
        if quiescence_proof.lease_path is None
        else Path(quiescence_proof.lease_path).expanduser().resolve(strict=False)
    )
    if inventory.parent != ownership_root or proof_lease_path != lease_path:
        raise InstanceStatePreflightError(
            "drained legacy-owner receipt is not bound to this host-global ownership root"
        )
    quiescence_proof.require_valid(channel_id=channel)
    controller_pid = quiescence_proof.controller_pid
    controller_start_token = quiescence_proof.controller_start_token
    if controller_pid is None or controller_start_token is None:
        raise InstanceStatePreflightError(
            "durable quiescence proof is required for drained-owner binding"
        )
    try:
        lease_metadata = lease_path.lstat()
        lease = json.loads(lease_path.read_text(encoding="utf-8"))
        controller = lease.get("controller")
        expected_controller = {
            "pid": controller_pid,
            "start_token": controller_start_token,
        }
        if (
            not stat.S_ISREG(lease_metadata.st_mode)
            or lease_metadata.st_uid != os.geteuid()
            or lease_metadata.st_mode & 0o777 != 0o600
            or lease.get("schema") != _DEPLOYMENT_LEASE_SCHEMA
            or lease.get("channel_id") != channel
            or lease.get("nonce") != quiescence_proof.nonce
            or lease.get("phase") != "proved"
            or lease.get("inventory_digest") != quiescence_proof.inventory_digest
            or lease.get("all_consumers_stopped") is not True
            or controller != expected_controller
        ):
            raise ValueError
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise InstanceStatePreflightError(
            "durable quiescence proof is required for drained-owner binding"
        ) from exc
    fence = _read_deployment_fence(ownership_root, channel)
    if (
        fence.get("deployment_nonce") != quiescence_proof.nonce
        or fence.get("controller") != controller
    ):
        raise InstanceStatePreflightError(
            "drained legacy-owner receipt does not match the active restart fence"
        )
    payload = _load_legacy_owner_inventory_payload(inventory)
    binding_fields = {
        "deployment_nonce": quiescence_proof.nonce,
        "controller": controller,
        "quiescence_inventory_digest": quiescence_proof.inventory_digest,
    }
    existing_binding = {
        key: payload.get(key)
        for key in (*binding_fields, "receipt_digest")
        if key in payload
    }
    if existing_binding:
        receipt_digest = str(payload.get("receipt_digest") or "")
        if (
            any(payload.get(key) != value for key, value in binding_fields.items())
            or _LEGACY_INVENTORY_SOURCE_DIGEST_RE.fullmatch(receipt_digest) is None
            or receipt_digest != _legacy_owner_receipt_digest(payload)
        ):
            raise InstanceStatePreflightError(
                "drained legacy-owner receipt is stale or forged"
            )
        bound_payload = payload
    else:
        bound_payload = payload | binding_fields
        receipt_digest = _legacy_owner_receipt_digest(bound_payload)
        bound_payload = bound_payload | {"receipt_digest": receipt_digest}

    existing_lease_digest = lease.get("owner_receipt_digest")
    if existing_lease_digest not in (None, receipt_digest):
        raise InstanceStatePreflightError(
            "proved deployment lease is bound to another drained-owner receipt"
        )
    if not existing_binding:
        _replace_private_json(inventory, bound_payload)
    if existing_lease_digest is None:
        lease = lease | {"owner_receipt_digest": receipt_digest}
        _replace_private_json(lease_path, lease)

    bound_proof = replace(
        quiescence_proof,
        controller_pid=controller_pid,
        controller_start_token=controller_start_token,
        owner_receipt_digest=receipt_digest,
    )
    proof_path = ownership_root / "deployment-quiescence-proof.json"
    proof_payload: dict[str, object] = {
        "channel_id": bound_proof.channel_id,
        "nonce": bound_proof.nonce,
        "inventory_digest": bound_proof.inventory_digest,
        "lease_path": str(lease_path),
        "controller": expected_controller,
        "owner_receipt_digest": receipt_digest,
    }
    _replace_private_json(proof_path, proof_payload)
    bound_proof.require_valid(channel_id=channel)
    return bound_proof


def _load_legacy_owner_inventory(
    inventory_path: Path,
    *,
    registry: RegistrySnapshot,
    channel: str,
    quiescence_proof: DeploymentQuiescenceProof | None = None,
) -> list[LegacyOwner]:
    payload = _load_legacy_owner_inventory_payload(inventory_path)
    if quiescence_proof is not None:
        expected_controller = {
            "pid": quiescence_proof.controller_pid,
            "start_token": quiescence_proof.controller_start_token,
        }
        receipt_digest = str(payload.get("receipt_digest") or "")
        if (
            quiescence_proof.owner_receipt_digest is None
            or payload.get("deployment_nonce") != quiescence_proof.nonce
            or payload.get("controller") != expected_controller
            or payload.get("quiescence_inventory_digest")
            != quiescence_proof.inventory_digest
            or receipt_digest != quiescence_proof.owner_receipt_digest
            or receipt_digest != _legacy_owner_receipt_digest(payload)
        ):
            raise InstanceStatePreflightError(
                "drained legacy-owner receipt is not bound to this deployment proof"
            )

    owner_payload = payload.get("owners")
    if not isinstance(owner_payload, list):
        raise InstanceStatePreflightError("legacy-owner inventory entries are invalid")
    owners: list[LegacyOwner] = []
    for item in owner_payload:
        if not isinstance(item, dict):
            raise InstanceStatePreflightError("legacy-owner inventory entry is invalid")
        owner_channel = str(item.get("channel_id") or "").strip()
        root = Path(str(item.get("root") or "")).expanduser().resolve(strict=False)
        if not owner_channel or not root.is_dir():
            raise InstanceStatePreflightError("legacy-owner inventory entry is invalid")
        binding_id = str(item.get("vault_binding_id") or "").strip()
        if owner_channel == channel:
            for registration in registry.registrations.values():
                if same_filesystem_root(
                    resolve_filesystem_root_identity(root),
                    resolve_filesystem_root_identity(registration.path),
                ):
                    binding_id = registration.vault_binding_id
                    break
        if not binding_id:
            digest = hashlib.sha256(f"{owner_channel}\0{root}".encode()).hexdigest()[:20]
            binding_id = f"legacy-{owner_channel}-{digest}"
        owners.append(LegacyOwner(owner_channel, binding_id, root))
    if len({owner.vault_binding_id for owner in owners}) != len(owners):
        raise InstanceStatePreflightError("legacy-owner inventory repeats a binding identity")
    represented = {owner.vault_binding_id for owner in owners if owner.channel_id == channel}
    missing_bindings = set(registry.registrations) - represented
    if missing_bindings:
        raise InstanceStatePreflightError(
            "legacy-owner inventory omits a current-channel registration"
        )
    return owners


def _finish_instance_state_deployment(
    *,
    channel: str,
    instance_state_root: Path,
    host_global_root: Path,
    legacy_path: Path,
    inventory_path: Path,
    backup_root: Path,
    restore_root: Path | None,
    quiescence_proof: DeploymentQuiescenceProof | None,
) -> dict[str, object]:
    """Finalize legacy state while stopped, then clear the restart fence."""

    if quiescence_proof is None:
        raise InstanceStatePreflightError("durable quiescence proof is required")
    state_mount = _assert_mount_root(instance_state_root, "instance-state")
    ownership_root = _assert_mount_root(host_global_root, "host-global")
    quiescence_proof.require_valid(channel_id=channel)
    _read_deployment_fence(ownership_root, channel)
    quiescence_proof = _bind_legacy_owner_inventory_to_proof(
        inventory_path=inventory_path,
        quiescence_proof=quiescence_proof,
        channel=channel,
        host_global_root=ownership_root,
    )
    layout = InstanceStateLayout.for_channel(state_mount, channel)
    layout.ensure()
    ledger = OwnershipLedger(ownership_root)
    backup = InstanceStateBackup(layout, ledger)

    if restore_root is not None:
        backup.restore(
            restore_root,
            quiescence_proof=quiescence_proof,
            owner_receipt_path=inventory_path,
        )

    store = VaultRegistryStore(layout.registry_path)
    has_registry_state = layout.registry_path.is_file() or (
        store.snapshot_path.is_file() and store.snapshot_checksum_path.is_file()
    )
    had_populated_registry = has_registry_state and store.load().revision > 0
    if had_populated_registry and restore_root is None:
        ledger.require_existing()

    source = Path(legacy_path).expanduser().resolve(strict=False)
    final_fingerprint: str | None = None
    if source.is_file():
        exporter = LegacyRegistryFinalExport(layout)
        final = exporter.export_final_after_stop(
            source,
            quiescence_proof=quiescence_proof,
            host_global_root=ownership_root,
            owner_receipt_path=inventory_path,
        )
        final_fingerprint = final.fingerprint
        if not layout.registry_path.is_file() or store.load().revision == 0:
            exporter.import_final_export(
                final,
                quiescence_proof=quiescence_proof,
                host_global_root=ownership_root,
                owner_receipt_path=inventory_path,
            )
        else:
            exporter.preserve_final_export(
                final,
                quiescence_proof=quiescence_proof,
                host_global_root=ownership_root,
                owner_receipt_path=inventory_path,
            )
    elif not layout.registry_path.is_file():
        store.load()

    registry = store.load()
    try:
        ledger_snapshot = ledger.require_existing()
    except LedgerError:
        ledger_snapshot = None
    if ledger_snapshot is None or not ledger_snapshot.legacy_bootstrap_complete:
        owners = _load_legacy_owner_inventory(
            inventory_path,
            registry=registry,
            channel=channel,
            quiescence_proof=quiescence_proof,
        )
        ledger_snapshot = ledger.bootstrap_legacy_owners(
            owners,
            inventory_complete=True,
            writers_drained=True,
        )
    for registration in registry.registrations.values():
        ledger.recover_or_require_active(
            registration.vault_binding_id,
            channel_id=channel,
            root=Path(registration.path),
        )
    if not ledger_snapshot.legacy_bootstrap_complete:
        raise InstanceStatePreflightError("legacy owner bootstrap did not complete")

    backup_receipt = backup.create(backup_root)
    fence_path = _deployment_fence_path(ownership_root, channel)
    fence_path.unlink()
    _deployment_lease_path(ownership_root).unlink()
    (ownership_root / "deployment-quiescence-proof.json").unlink(missing_ok=True)
    directory = os.open(ownership_root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return {
        "channel": channel,
        "registry_revision": registry.revision,
        "final_fingerprint": final_fingerprint,
        "backup_manifest": str(backup_receipt.manifest_path),
        "restart_fence_cleared": True,
    }


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
    begin = subparsers.add_parser("deployment-begin")
    begin.add_argument("--channel", required=True)
    begin.add_argument("--instance-state-root", type=Path, required=True)
    begin.add_argument("--host-global-root", type=Path, required=True)
    begin.add_argument("--legacy-path", type=Path, required=True)
    begin.add_argument("--controller-pid", type=int, required=True)
    begin.add_argument("--controller-start-token", required=True)
    finish = subparsers.add_parser("deployment-finish")
    finish.add_argument("--channel", required=True)
    finish.add_argument("--instance-state-root", type=Path, required=True)
    finish.add_argument("--host-global-root", type=Path, required=True)
    finish.add_argument("--legacy-path", type=Path, required=True)
    finish.add_argument("--inventory-path", type=Path, required=True)
    finish.add_argument("--backup-root", type=Path, required=True)
    finish.add_argument("--restore-root", type=Path)
    finish.add_argument("--quiescence-proof-path", type=Path, required=True)
    prove = subparsers.add_parser("deployment-prove")
    prove.add_argument("--channel", required=True)
    prove.add_argument("--host-global-root", type=Path, required=True)
    prove.add_argument("--inventory-path", type=Path, required=True)
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
    if args.command == "deployment-begin":
        print(
            json.dumps(
                _begin_instance_state_deployment(
                    channel=args.channel,
                    instance_state_root=args.instance_state_root,
                    host_global_root=args.host_global_root,
                    legacy_path=args.legacy_path,
                    controller_pid=args.controller_pid,
                    controller_start_token=args.controller_start_token,
                ),
                sort_keys=True,
            )
        )
        return 0
    if args.command == "deployment-finish":
        proof_payload = json.loads(args.quiescence_proof_path.read_text(encoding="utf-8"))
        controller = proof_payload.get("controller")
        if not isinstance(controller, dict):
            raise InstanceStatePreflightError("durable quiescence proof is required")
        proof = DeploymentQuiescenceProof(
            channel_id=str(proof_payload["channel_id"]),
            nonce=str(proof_payload["nonce"]),
            inventory_digest=str(proof_payload["inventory_digest"]),
            lease_path=Path(str(proof_payload["lease_path"])),
            controller_pid=int(controller["pid"]),
            controller_start_token=str(controller["start_token"]),
            owner_receipt_digest=(
                str(proof_payload["owner_receipt_digest"])
                if proof_payload.get("owner_receipt_digest") is not None
                else None
            ),
        )
        print(
            json.dumps(
                _finish_instance_state_deployment(
                    channel=args.channel,
                    instance_state_root=args.instance_state_root,
                    host_global_root=args.host_global_root,
                    legacy_path=args.legacy_path,
                    inventory_path=args.inventory_path,
                    backup_root=args.backup_root,
                    restore_root=args.restore_root,
                    quiescence_proof=proof,
                ),
                sort_keys=True,
            )
        )
        return 0
    if args.command == "deployment-prove":
        proof = _prove_instance_state_quiescence(
            channel=args.channel, host_global_root=args.host_global_root, inventory_path=args.inventory_path
        )
        print(
            json.dumps(
                {
                    "channel_id": proof.channel_id,
                    "nonce": proof.nonce,
                    "inventory_digest": proof.inventory_digest,
                    "lease_path": str(proof.lease_path),
                    "controller": {
                        "pid": proof.controller_pid,
                        "start_token": proof.controller_start_token,
                    },
                },
                sort_keys=True,
            )
        )
        return 0
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "InstanceRegistryRuntime",
]
