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
from app.instance.scalar_rollback_guard import (
    ScalarRollbackGuardReceipt,
    preflight_scalar_rollback_guard,
)
from app.instance.vault_registry import (
    AppLocalSettings,
    AppLocalSettingsStore,
    CapabilityNotReadyError,
    RegistryError,
    RegistryActivationProof,
    RegistrySnapshot,
    REGISTRY_AUTHORITY_ACTIVE,
    RemovalTombstone,
    VaultRegistration,
    VaultRegistryStore,
)


@contextmanager
def _producer_transition_locked(layout: InstanceStateLayout) -> Iterator[None]:
    """Serialize registry producer transitions and deployment finalization."""

    lock_path = layout.root / "bootstrap.lock"
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


@contextmanager
def _deployment_admission_locked(host_global_root: Path) -> Iterator[None]:
    """Serialize deployment-begin with scalar rollback admission."""

    lock_path = Path(host_global_root) / "deployment-admission.lock"
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
        from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY

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
                    _capability=_STORAGE_MUTATION_CAPABILITY,
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
            if current.authority != REGISTRY_AUTHORITY_ACTIVE:
                raise CapabilityNotReadyError("MVR-01C authority cutover seals second registration")
            return self._register_active_locked(
                Path(root_identity.canonical_path),
                producer="bootstrap",
                current=current,
            )
        pending = (
            self.ledger.pending_registration(
                channel_id=self.layout.channel_id,
                root=Path(root_identity.canonical_path),
            )
            if self.ledger.path.is_file() and self.ledger.key_path.is_file()
            else None
        )
        registration = self._new_registration(
            Path(root_identity.canonical_path),
            vault_binding_id=(
                pending.vault_binding_id if pending is not None else None
            ),
        )
        self.ledger.reserve(
            channel_id=self.layout.channel_id,
            vault_binding_id=registration.vault_binding_id,
            root=Path(registration.path),
            allow_same_channel_nested=False,
            _capability=_STORAGE_MUTATION_CAPABILITY,
        )
        try:
            self.registry.register(
                registration,
                expected_revision=current.revision,
                _capability=_STORAGE_MUTATION_CAPABILITY,
            )
        except Exception:
            # A retry can recover a prepared lease only when the registry commit exists;
            # otherwise leaving it pending is safer than allowing a conflicting owner.
            raise
        self.ledger.activate(
            registration.vault_binding_id,
            _capability=_STORAGE_MUTATION_CAPABILITY,
        )
        return registration

    def _require_established_ownership(self, current: RegistrySnapshot) -> None:
        if current.revision > 0:
            self.ledger.require_existing()

    @contextmanager
    def _bootstrap_locked(self) -> Iterator[None]:
        with _producer_transition_locked(self.layout):
            yield

    def prepare_nested_registration(self, child_root: Path) -> VaultRegistration:
        del child_root
        raise CapabilityNotReadyError(
            "MVR-01C authority cutover exposes nested registration only through "
            "the active production picker"
        )

    def production_register(self, path: Path, *, producer: str) -> VaultRegistration:
        if producer not in {"picker", "api", "cli", "import", "bootstrap", "direct-service"}:
            raise RegistryError("unknown registry producer")
        with self._bootstrap_locked():
            current = self.registry.load()
            if current.authority != REGISTRY_AUTHORITY_ACTIVE:
                raise CapabilityNotReadyError(
                    "MVR-01C authority cutover seals production registration"
                )
            return self._register_active_locked(
                path,
                producer=producer,
                current=current,
                allow_same_channel_nested=producer == "picker",
            )

    def _register_active_locked(
        self,
        path: Path,
        *,
        producer: str,
        current: RegistrySnapshot,
        allow_same_channel_nested: bool = False,
    ) -> VaultRegistration:
        from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY

        if producer not in {"picker", "api", "cli", "import", "bootstrap", "direct-service"}:
            raise RegistryError("unknown registry producer")
        self.registry.require_no_scalar_rollback_session()
        root_identity = resolve_filesystem_root_identity(path)
        canonical_root = Path(root_identity.canonical_path)
        for existing in current.registrations.values():
            if same_filesystem_root(
                resolve_filesystem_root_identity(existing.path),
                root_identity,
            ):
                self.ledger.recover_or_require_active(
                    existing.vault_binding_id,
                    channel_id=self.layout.channel_id,
                    root=canonical_root,
                    _capability=_STORAGE_MUTATION_CAPABILITY,
                )
                return existing
        pending = self.ledger.pending_registration(
            channel_id=self.layout.channel_id,
            root=canonical_root,
        )
        registration = self._new_registration(
            canonical_root,
            vault_binding_id=(
                pending.vault_binding_id if pending is not None else None
            ),
        )
        validate_registry_disjoint_from_content(
            self.layout.registry_path,
            [Path(item.path) for item in current.registrations.values()]
            + [Path(registration.path)],
        )
        self.ledger.reserve(
            channel_id=self.layout.channel_id,
            vault_binding_id=registration.vault_binding_id,
            root=Path(registration.path),
            allow_same_channel_nested=allow_same_channel_nested,
            _capability=_STORAGE_MUTATION_CAPABILITY,
        )
        self.registry.register(
            registration,
            expected_revision=current.revision,
            _capability=_STORAGE_MUTATION_CAPABILITY,
        )
        self.ledger.activate(
            registration.vault_binding_id,
            _capability=_STORAGE_MUTATION_CAPABILITY,
        )
        return registration

    def activate_authority(
        self,
        *,
        guard_receipt: ScalarRollbackGuardReceipt,
        inventory_path: Path,
        quiescence_proof: DeploymentQuiescenceProof,
        inject_failure_before_commit: bool = False,
    ) -> RegistrySnapshot:
        """Install all rollback guards in one durable registry activation."""

        from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY

        with self._bootstrap_locked():
            bound_proof = _bind_legacy_owner_inventory_to_proof(
                inventory_path=inventory_path,
                quiescence_proof=quiescence_proof,
                channel=self.layout.channel_id,
                host_global_root=self.ledger.root,
            )
            bound_proof.require_valid(channel_id=self.layout.channel_id)
            guard_receipt.revalidate()
            current = self.registry.load()
            target_id = guard_receipt.rollback_vault_binding_id
            target = current.registrations.get(target_id or "")
            if (
                target is None
                or guard_receipt.rollback_vault_binding_id != target_id
                or not same_filesystem_root(
                    resolve_filesystem_root_identity(guard_receipt.selected_root),
                    resolve_filesystem_root_identity(target.path),
                )
                or not guard_receipt.gateway_authenticated
                or not guard_receipt.mutation_filtering
                or not guard_receipt.direct_api_port_absent
                or not guard_receipt.selected_mount_only
                or not guard_receipt.native_guard_fail_closed
            ):
                raise CapabilityNotReadyError(
                    "MVR-01C authority cutover guard receipt does not match the selected binding"
                )
            registrations: dict[str, Path | None] = {
                binding_id: Path(registration.path)
                for binding_id, registration in current.registrations.items()
            }
            self.ledger.require_scalar_rollback_ready(
                channel_id=self.layout.channel_id,
                registrations=registrations,
            )
            self.ledger.require_scalar_rollback_ready(
                channel_id=self.layout.channel_id,
                registrations={
                    binding_id: (
                        guard_receipt.selected_root
                        if binding_id == target_id
                        else None
                    )
                    for binding_id in current.registrations
                },
            )
            if inject_failure_before_commit:
                raise RegistryError("injected partial MVR-01C activation")
            _require_matching_compatibility_block(self.ledger.root)
            return self.registry.require_authoritative_activation(
                RegistryActivationProof(
                    rollback_exporter=True,
                    rollback_transformer=True,
                    previous_image_preflight=True,
                    rollback_vault_binding_id=target_id,
                    authenticated_gateway=guard_receipt.gateway_authenticated,
                    native_guard=guard_receipt.native_guard_fail_closed,
                    roll_forward_lineage=True,
                    compose_policy_sha256=guard_receipt.compose_policy_sha256,
                    gateway_policy_sha256=guard_receipt.gateway_policy_sha256,
                    native_launcher_sha256=guard_receipt.native_launcher_sha256,
                ),
                expected_revision=current.revision,
                _capability=_STORAGE_MUTATION_CAPABILITY,
            )

    def prepare_previous_scalar_image(self, legacy_path: Path) -> None:
        self._legacy_path = Path(legacy_path).expanduser().resolve(strict=False)
        # Loading proves that the rollback image remains readable without changing it.
        AppLocalSettingsStore(self._legacy_path).load()

    def production_read(self) -> AppLocalSettings:
        current = self.registry.load()
        if current.authority == REGISTRY_AUTHORITY_ACTIVE:
            return self.registry.app_local_view()
        return AppLocalSettingsStore(self._legacy_path).load()

    def merge_previous_scalar_image(self, legacy_path: Path) -> RegistrySnapshot:
        from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY

        payload, authentication = self.registry.load_scalar_rollback_session()
        self.ledger.verify_scalar_rollback_session(
            payload,
            authentication,
            _capability=_STORAGE_MUTATION_CAPABILITY,
        )
        return self.registry.merge_scalar_rollback(
            legacy_path,
            session_payload=payload,
            _capability=_STORAGE_MUTATION_CAPABILITY,
        )

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

        from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY

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
            _capability=_STORAGE_MUTATION_CAPABILITY,
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
        from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY

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
        self.registry.update_registration(
            updated,
            _capability=_STORAGE_MUTATION_CAPABILITY,
        )
        return updated

    def _new_registration(
        self,
        root: Path,
        *,
        vault_binding_id: str | None = None,
    ) -> VaultRegistration:
        vault_id, local_instance_id = _read_vault_identity(root)
        identity = resolve_filesystem_root_identity(root)
        binding_id = vault_binding_id or f"binding-{uuid4()}"
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
    if _any_deployment_lease_exists(host_global_root):
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
    runtime.registry.require_no_scalar_rollback_session()
    _require_runtime_floor(runtime.registry.load(), scalar_runtime=False)
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


def _require_runtime_floor(snapshot: RegistrySnapshot, *, scalar_runtime: bool) -> None:
    floors = snapshot.extensions.get("runtimeFloors") or {}
    if not isinstance(floors, dict):
        raise RegistryError("runtime floors are invalid")
    minimum = str(floors.get("minimumRuntimeSchema") or "").strip()
    if scalar_runtime and minimum and minimum != "scalar":
        raise CapabilityNotReadyError(
            "minimum runtime schema blocks scalar API/worker before database or queue startup"
        )


def _preflight_scalar_rollback(
    *,
    channel: str,
    registry_path: Path,
    host_global_root: Path,
    rollback_vault_binding_id: str,
    legacy_path: Path,
    selected_root: Path,
    compose_base: Path,
    compose_overlay: Path,
    gateway_config: Path,
    native_launcher: Path,
) -> int:
    if not host_global_root.is_dir():
        raise RegistryError("host-global ownership mount is missing")
    with _deployment_admission_locked(host_global_root):
        return _preflight_scalar_rollback_locked(
            channel=channel,
            registry_path=registry_path,
            host_global_root=host_global_root,
            rollback_vault_binding_id=rollback_vault_binding_id,
            legacy_path=legacy_path,
            selected_root=selected_root,
            compose_base=compose_base,
            compose_overlay=compose_overlay,
            gateway_config=gateway_config,
            native_launcher=native_launcher,
        )


def _preflight_scalar_rollback_locked(
    *,
    channel: str,
    registry_path: Path,
    host_global_root: Path,
    rollback_vault_binding_id: str,
    legacy_path: Path,
    selected_root: Path,
    compose_base: Path,
    compose_overlay: Path,
    gateway_config: Path,
    native_launcher: Path,
) -> int:
    from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY

    if _any_deployment_lease_exists(host_global_root) or any(
        host_global_root.glob("deployment-*-restart-fence.json")
    ):
        raise RegistryError("scalar rollback is blocked by a deployment lease or restart fence")
    store = VaultRegistryStore(registry_path)
    producer_lock = registry_path.parent / "bootstrap.lock"
    descriptor = os.open(
        producer_lock,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "a+b", closefd=True) as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            snapshot = store.load()
            _require_runtime_floor(snapshot, scalar_runtime=True)
            ledger = OwnershipLedger(host_global_root)
            target = snapshot.registrations.get(rollback_vault_binding_id)
            if target is None:
                raise RegistryError("scalar rollback target is not registered")
            ledger.require_scalar_rollback_ready(
                channel_id=channel,
                registrations={
                    binding_id: (
                        selected_root
                        if binding_id == rollback_vault_binding_id
                        else None
                    )
                    for binding_id in snapshot.registrations
                },
            )
            floor = snapshot.extensions.get("scalarRollback")
            if not isinstance(floor, dict):
                raise RegistryError("active registry scalar rollback floor is invalid")
            guard_receipt = preflight_scalar_rollback_guard(
                compose_base=compose_base,
                compose_overlay=compose_overlay,
                gateway_config=gateway_config,
                native_launcher=native_launcher,
                rollback_vault_binding_id=rollback_vault_binding_id,
                selected_root=selected_root,
            )
            if (
                guard_receipt.compose_policy_sha256
                != floor.get("composePolicySha256")
                or guard_receipt.gateway_policy_sha256
                != floor.get("gatewayPolicySha256")
                or guard_receipt.native_launcher_sha256
                != floor.get("nativeLauncherSha256")
            ):
                raise RegistryError(
                    "scalar rollback policy does not match the activated floor"
                )
            registry_export_sha256 = hashlib.sha256(
                store.rollback_export_path.read_bytes()
            ).hexdigest()
            floors = snapshot.extensions.get("runtimeFloors") or {}
            if not isinstance(floors, dict):
                raise RegistryError("runtime floors are invalid")
            session_invariants: dict[str, object] = {
                "schema": "agentic-pkm.scalar-roll-forward-lineage.v1",
                "registrySchema": snapshot.schema,
                "forkRegistryRevision": snapshot.revision,
                "rollbackVaultBindingId": rollback_vault_binding_id,
                "minimumRuntimeSchema": floors.get("minimumRuntimeSchema"),
                "registryExportSha256": registry_export_sha256,
                "legacySelectedPath": str(selected_root),
                "composePolicySha256": guard_receipt.compose_policy_sha256,
                "gatewayPolicySha256": guard_receipt.gateway_policy_sha256,
                "nativeLauncherSha256": guard_receipt.native_launcher_sha256,
            }
            if store.scalar_rollback_session_path.exists():
                payload, authentication = store.load_scalar_rollback_session()
                ledger.verify_scalar_rollback_session(
                    payload,
                    authentication,
                    _capability=_STORAGE_MUTATION_CAPABILITY,
                )
                if (
                    any(
                        payload.get(key) != value
                        for key, value in session_invariants.items()
                    )
                    or re.fullmatch(
                        r"[0-9a-f]{64}",
                        str(payload.get("initialExportSha256") or ""),
                    )
                    is None
                ):
                    raise RegistryError(
                        "existing scalar rollback session does not match this retry"
                    )
                # The old API may already have changed its valid scalar file;
                # the signed initial digest remains lineage, not a retry-time
                # immutability assertion.
                if not legacy_path.is_file():
                    raise RegistryError(
                        "existing scalar rollback projection is missing"
                    )
                legacy = AppLocalSettingsStore(legacy_path).load()
                if set(legacy.known_vaults) != {target.ref}:
                    raise RegistryError(
                        "existing scalar rollback projection escaped the selected binding"
                    )
                selected = legacy.known_vaults[target.ref]
                if (
                    selected.path != str(selected_root)
                    or selected.vault_id != target.vault_id
                    or selected.local_instance_id != target.local_instance_id
                    or legacy.last_active_vault_ref not in (None, target.ref)
                ):
                    raise RegistryError(
                        "existing scalar rollback projection identity diverged"
                    )
            else:
                store.materialize_legacy_rollback(
                    legacy_path,
                    rollback_vault_binding_id=rollback_vault_binding_id,
                    selected_runtime_path=selected_root,
                )
                projection_sha256 = hashlib.sha256(
                    legacy_path.read_bytes()
                ).hexdigest()
                payload = session_invariants | {
                    "initialExportSha256": projection_sha256,
                }
                authentication = ledger.authenticate_scalar_rollback_session(
                    payload,
                    _capability=_STORAGE_MUTATION_CAPABILITY,
                )
                guard_receipt.revalidate()
                if _any_deployment_lease_exists(host_global_root) or any(
                    host_global_root.glob("deployment-*-restart-fence.json")
                ):
                    raise RegistryError(
                        "scalar rollback is blocked by a deployment lease or restart fence"
                    )
                store.install_scalar_rollback_session(
                    payload=payload,
                    authentication=authentication,
                    expected_revision=snapshot.revision,
                    _capability=_STORAGE_MUTATION_CAPABILITY,
                )
            guard_receipt.revalidate()
            if _any_deployment_lease_exists(host_global_root) or any(
                host_global_root.glob("deployment-*-restart-fence.json")
            ):
                raise RegistryError(
                    "scalar rollback is blocked by a deployment lease or restart fence"
                )
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    print(
        json.dumps(
            {
                "registry_revision": snapshot.revision,
                "rollback_vault_binding_id": rollback_vault_binding_id,
                "legacy_projection": str(legacy_path),
            },
            sort_keys=True,
        )
    )
    return 0


def _activate_mvr01c_authority(
    *,
    channel: str,
    instance_state_root: Path,
    host_global_root: Path,
    rollback_vault_binding_id: str,
    selected_root: Path,
    compose_base: Path,
    compose_overlay: Path,
    gateway_config: Path,
    native_launcher: Path,
    inventory_path: Path,
    quiescence_proof_path: Path,
) -> int:
    proof = _load_deployment_quiescence_proof(quiescence_proof_path)
    runtime = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(instance_state_root, channel),
        host_global_root,
        initialize_layout=False,
    )
    receipt = preflight_scalar_rollback_guard(
        compose_base=compose_base,
        compose_overlay=compose_overlay,
        gateway_config=gateway_config,
        native_launcher=native_launcher,
        rollback_vault_binding_id=rollback_vault_binding_id,
        selected_root=selected_root,
    )
    activated = runtime.activate_authority(
        guard_receipt=receipt,
        inventory_path=inventory_path,
        quiescence_proof=proof,
    )
    print(
        json.dumps(
            {
                "authority": activated.authority,
                "registry_revision": activated.revision,
                "rollback_vault_binding_id": rollback_vault_binding_id,
            },
            sort_keys=True,
        )
    )
    return 0


def _load_deployment_quiescence_proof(path: Path) -> DeploymentQuiescenceProof:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        controller = payload.get("controller")
        if not isinstance(controller, dict):
            raise ValueError
        return DeploymentQuiescenceProof(
            channel_id=str(payload["channel_id"]),
            nonce=str(payload["nonce"]),
            inventory_digest=str(payload["inventory_digest"]),
            lease_path=Path(str(payload["lease_path"])),
            controller_pid=int(controller["pid"]),
            controller_start_token=str(controller["start_token"]),
            owner_receipt_digest=(
                str(payload["owner_receipt_digest"])
                if payload.get("owner_receipt_digest") is not None
                else None
            ),
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InstanceStatePreflightError(
            "durable quiescence proof is required"
        ) from exc


def _roll_forward_scalar_rollback(
    *,
    channel: str,
    instance_state_root: Path,
    host_global_root: Path,
    legacy_path: Path,
    inventory_path: Path,
    quiescence_proof_path: Path,
) -> int:
    """Merge a scalar fork only inside the existing host-wide stopped window."""

    state_mount = _assert_mount_root(instance_state_root, "instance-state")
    ownership_root = _assert_mount_root(host_global_root, "host-global")
    layout = InstanceStateLayout.for_channel(state_mount, channel)
    layout.require_existing()
    with _deployment_admission_locked(ownership_root):
        with _producer_transition_locked(layout):
            proof = _load_deployment_quiescence_proof(quiescence_proof_path)
            _bind_legacy_owner_inventory_to_proof(
                inventory_path=inventory_path,
                quiescence_proof=proof,
                channel=channel,
                host_global_root=ownership_root,
            )
            runtime = InstanceRegistryRuntime.for_paths(
                layout,
                ownership_root,
                initialize_layout=False,
            )
            current = runtime.registry.load()
            runtime.ledger.require_scalar_rollback_ready(
                channel_id=channel,
                registrations={
                    binding_id: Path(registration.path)
                    for binding_id, registration in current.registrations.items()
                },
            )
            merged = runtime.merge_previous_scalar_image(legacy_path)
    print(
        json.dumps(
            {
                "registry_revision": merged.revision,
                "scalar_roll_forward": "merged",
            },
            sort_keys=True,
        )
    )
    return 0


_DEPLOYMENT_FENCE_SCHEMA = "agentic-pkm.instance-state-deployment-fence.v1"
_LEGACY_INVENTORY_SCHEMA = "agentic-pkm.legacy-owner-inventory.v1"
_LEGACY_INVENTORY_SOURCE_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_DEPLOYMENT_LEASE_SCHEMA = "agentic-pkm.host-deployment-lease.v3"
_DEPLOYMENT_COMPATIBILITY_BLOCK_SCHEMA = (
    "agentic-pkm.host-deployment-compatibility-block.v1"
)
_QUIESCENCE_INVENTORY_SCHEMA = "agentic-pkm.host-deployment-quiescence.v2"
_CONTROLLER_START_TOKEN_RE = re.compile(r"^(?:linux|darwin):[0-9a-f]{64}$")


def _deployment_fence_path(host_global_root: Path, channel: str) -> Path:
    return Path(host_global_root) / f"deployment-{channel}-restart-fence.json"


def _deployment_lease_path(host_global_root: Path) -> Path:
    return _deployment_public_root(host_global_root) / "deployment-host-global-lease.json"


def _legacy_deployment_lease_path(host_global_root: Path) -> Path:
    return Path(host_global_root) / "deployment-host-global-lease.json"


def _any_deployment_lease_exists(host_global_root: Path) -> bool:
    return _deployment_lease_path(
        host_global_root
    ).exists() or _legacy_deployment_lease_path(host_global_root).exists()


def _deployment_public_root(host_global_root: Path) -> Path:
    return Path(host_global_root) / "deployment-public"


def _ensure_deployment_public_root(host_global_root: Path) -> Path:
    root = _deployment_public_root(host_global_root)
    root.mkdir(mode=0o700, exist_ok=True)
    metadata = root.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
        raise InstanceStatePreflightError("public deployment control directory is unsafe")
    os.chmod(root, 0o700)
    runtime_lock = _scalar_rollback_runtime_lock_path(host_global_root)
    descriptor = os.open(
        runtime_lock,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise InstanceStatePreflightError(
                "scalar rollback runtime admission lock is unsafe"
            )
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return root


def _scalar_rollback_runtime_lock_path(host_global_root: Path) -> Path:
    return _deployment_public_root(host_global_root) / "scalar-rollback-runtime.lock"


@contextmanager
def _scalar_rollback_runtime_quiescent(host_global_root: Path) -> Iterator[None]:
    """Exclude every old API admitted before the public deployment lease."""

    runtime_lock = _scalar_rollback_runtime_lock_path(host_global_root)
    descriptor = os.open(
        runtime_lock,
        os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
    )
    with os.fdopen(descriptor, "a+b", closefd=True) as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise InstanceStatePreflightError(
                "scalar rollback runtime is still admitted"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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


def _read_deployment_lease(host_global_root: Path) -> dict[str, object]:
    path = _deployment_lease_path(host_global_root)
    try:
        metadata = path.lstat()
        payload = json.loads(path.read_text(encoding="utf-8"))
        controller = payload.get("controller")
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o777 != 0o600
            or not isinstance(payload, dict)
            or payload.get("schema") != _DEPLOYMENT_LEASE_SCHEMA
            or payload.get("phase") not in {"claimed", "proved", "cleanup"}
            or not isinstance(payload.get("channel_id"), str)
            or not isinstance(payload.get("nonce"), str)
            or not isinstance(payload.get("legacy_path"), str)
            or not isinstance(controller, dict)
            or not isinstance(controller.get("pid"), int)
            or _CONTROLLER_START_TOKEN_RE.fullmatch(
                str(controller.get("start_token") or "")
            )
            is None
        ):
            raise ValueError
        return payload
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise InstanceStatePreflightError(
            "valid host-global deployment lease is required"
        ) from exc


def _read_legacy_deployment_lease(
    host_global_root: Path,
) -> dict[str, object]:
    path = _legacy_deployment_lease_path(host_global_root)
    try:
        metadata = path.lstat()
        payload = json.loads(path.read_text(encoding="utf-8"))
        controller = payload.get("controller")
        schema = payload.get("schema")
        is_legacy = schema == "agentic-pkm.host-deployment-lease.v2"
        is_compatibility_block = (
            schema == _DEPLOYMENT_COMPATIBILITY_BLOCK_SCHEMA
        )
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o777 != 0o600
            or not isinstance(payload, dict)
            or not (is_legacy or is_compatibility_block)
            or payload.get("phase")
            not in (
                {"claimed", "proved"}
                if is_legacy
                else {"claimed", "proved", "cleanup"}
            )
            or not isinstance(payload.get("channel_id"), str)
            or not isinstance(payload.get("nonce"), str)
            or not isinstance(controller, dict)
            or not isinstance(controller.get("pid"), int)
            or _CONTROLLER_START_TOKEN_RE.fullmatch(
                str(controller.get("start_token") or "")
            )
            is None
            or (
                is_compatibility_block
                and (
                    not isinstance(
                        payload.get("compatibility_v3_nonce"), str
                    )
                    or payload.get("compatibility_v3_nonce")
                    != payload.get("nonce")
                    or not isinstance(payload.get("legacy_path"), str)
                )
            )
        ):
            raise ValueError
        return payload
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise InstanceStatePreflightError(
            "valid legacy host-global deployment lease is required"
        ) from exc


def _compatibility_block_payload(
    lease: Mapping[str, object],
) -> dict[str, object]:
    payload = {
        "schema": _DEPLOYMENT_COMPATIBILITY_BLOCK_SCHEMA,
        "channel_id": lease["channel_id"],
        "nonce": lease["nonce"],
        "compatibility_v3_nonce": lease["nonce"],
        "phase": lease["phase"],
        "controller": lease["controller"],
        "legacy_path": lease["legacy_path"],
    }
    for key in (
        "diagnostic_fingerprint",
        "inventory_digest",
        "all_consumers_stopped",
        "owner_receipt_digest",
        "result",
    ):
        if key in lease:
            payload[key] = lease[key]
    return payload


def _require_matching_compatibility_block(
    host_global_root: Path,
    lease: Mapping[str, object] | None = None,
    *,
    reconcile_from_previous_phase: bool = False,
    reconcile_dead_claim_controller: bool = False,
) -> dict[str, object]:
    current = (
        _read_deployment_lease(host_global_root)
        if lease is None
        else dict(lease)
    )
    root_authority = _read_legacy_deployment_lease(host_global_root)
    expected = _compatibility_block_payload(current)
    if (
        root_authority != expected
        and reconcile_dead_claim_controller
        and root_authority.get("schema")
        == _DEPLOYMENT_COMPATIBILITY_BLOCK_SCHEMA
        and root_authority.get("phase") == expected.get("phase") == "claimed"
        and all(
            root_authority.get(key) == expected.get(key)
            for key in (
                "channel_id",
                "nonce",
                "compatibility_v3_nonce",
                "legacy_path",
            )
        )
        and root_authority.get("controller") != expected.get("controller")
        and not _controller_identity_is_live(root_authority.get("controller"))
    ):
        # A successor may have adopted the public claim and then died while
        # replacing the channel fence, before the final root-block refresh.
        # The shared nonce binds both private artifacts to that same claim.
        _replace_private_json(
            _legacy_deployment_lease_path(host_global_root),
            expected,
        )
        root_authority = expected
    if (
        root_authority != expected
        and reconcile_from_previous_phase
        and root_authority.get("schema")
        == _DEPLOYMENT_COMPATIBILITY_BLOCK_SCHEMA
        and all(
            root_authority.get(key) == expected.get(key)
            for key in (
                "channel_id",
                "nonce",
                "compatibility_v3_nonce",
                "controller",
                "legacy_path",
            )
        )
        and (
            (root_authority.get("phase"), expected.get("phase"))
            in {("claimed", "proved"), ("proved", "cleanup")}
            or (
                root_authority.get("phase") == expected.get("phase")
                and root_authority.get("owner_receipt_digest") is None
                and expected.get("owner_receipt_digest") is not None
            )
        )
    ):
        _replace_private_json(
            _legacy_deployment_lease_path(host_global_root),
            expected,
        )
        root_authority = expected
    if root_authority != expected:
        raise InstanceStatePreflightError(
            "root deployment compatibility block does not match the public lease"
        )
    return root_authority


def _controller_identity_is_live(controller: object) -> bool:
    if not isinstance(controller, dict):
        return False
    try:
        pid = int(controller["pid"])
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (KeyError, PermissionError, TypeError, ValueError) as exc:
        raise InstanceStatePreflightError(
            "existing deployment controller identity cannot be verified"
        ) from exc
    try:
        from scripts.instance_state_writer_inventory import (
            InventoryError,
            controller_token,
        )

        return controller_token(pid) == str(controller["start_token"])
    except (InventoryError, OSError) as exc:
        raise InstanceStatePreflightError(
            "existing deployment controller identity cannot be verified"
        ) from exc


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
    _ensure_deployment_public_root(ownership_root)
    layout = InstanceStateLayout.for_channel(state_mount, channel)
    layout.ensure()
    source = Path(legacy_path).expanduser().resolve(strict=False)
    diagnostic_fingerprint: str | None = None
    if source.is_file():
        diagnostic_fingerprint = LegacyRegistryFinalExport(
            layout
        ).capture_diagnostic_snapshot(source).fingerprint
    lease_path = _deployment_lease_path(ownership_root)
    controller: dict[str, object] = {
        "pid": controller_pid,
        "start_token": controller_start_token,
    }
    with _deployment_admission_locked(ownership_root):
        root_lease_path = _legacy_deployment_lease_path(ownership_root)
        root_authority = (
            _read_legacy_deployment_lease(ownership_root)
            if root_lease_path.exists()
            else None
        )
        existing_lease: dict[str, object] | None = None
        if lease_path.exists():
            existing_lease = _read_deployment_lease(ownership_root)
            if existing_lease.get("phase") == "cleanup":
                _complete_instance_state_deployment_cleanup(ownership_root)
                existing_lease = None
                root_authority = None
            elif (
                root_authority is not None
                and root_authority.get("schema")
                == _DEPLOYMENT_COMPATIBILITY_BLOCK_SCHEMA
            ):
                _require_matching_compatibility_block(
                    ownership_root,
                    existing_lease,
                    reconcile_dead_claim_controller=True,
                )
        compatibility_resume = (
            root_authority is not None
            and root_authority.get("schema")
            == _DEPLOYMENT_COMPATIBILITY_BLOCK_SCHEMA
            and existing_lease is None
        )
        legacy_lease = (
            root_authority
            if root_authority is not None
            and root_authority.get("schema")
            == "agentic-pkm.host-deployment-lease.v2"
            else None
        )
        if compatibility_resume:
            if root_authority is None:
                raise AssertionError
            if root_authority.get("phase") == "cleanup":
                _complete_instance_state_deployment_cleanup(ownership_root)
                root_authority = None
                compatibility_resume = False
            elif (
                root_authority.get("phase") != "claimed"
                or root_authority.get("channel_id") != channel
                or root_authority.get("legacy_path") != str(source)
            ):
                raise InstanceStatePreflightError(
                    "incomplete deployment compatibility block targets another claim"
                )
            elif root_authority.get("controller") != controller:
                if _controller_identity_is_live(root_authority.get("controller")):
                    raise InstanceStatePreflightError(
                        "deployment compatibility block controller is active"
                    )
                # The root blocker is the first durable write in a new v3
                # claim. If the controller dies before publishing the public
                # lease, adopt that authenticated claim in place: preserve its
                # nonce and continuously occupy the shipped v2 O_EXCL path.
                root_authority = dict(root_authority) | {
                    "controller": controller,
                }
                _replace_private_json(root_lease_path, root_authority)
        if legacy_lease is not None:
            if (
                legacy_lease.get("phase") != "claimed"
                or legacy_lease.get("channel_id") != channel
            ):
                raise InstanceStatePreflightError(
                    "legacy host-global deployment lease requires its original recovery path"
                )
            if _controller_identity_is_live(legacy_lease.get("controller")):
                raise InstanceStatePreflightError(
                    "legacy host-global deployment controller is active"
                )
        if existing_lease is not None:
            if (
                existing_lease.get("phase") != "claimed"
                or existing_lease.get("channel_id") != channel
                or existing_lease.get("legacy_path") != str(source)
            ):
                raise InstanceStatePreflightError(
                    "another host-global deployment lease is active"
                )
            if existing_lease.get("controller") == controller:
                existing_fence_path = _deployment_fence_path(
                    ownership_root, channel
                )
                if existing_fence_path.exists():
                    existing_fence = _read_deployment_fence(
                        ownership_root, channel
                    )
                    if existing_fence.get("legacy_path") != str(source):
                        raise InstanceStatePreflightError(
                            "existing restart fence does not match the deployment lease"
                        )
                    if (
                        existing_fence.get("deployment_nonce")
                        == existing_lease.get("nonce")
                        and existing_fence.get("controller") == controller
                    ):
                        compatibility = _compatibility_block_payload(
                            existing_lease
                        )
                        if root_lease_path.exists():
                            _replace_private_json(
                                root_lease_path, compatibility
                            )
                        else:
                            _write_private_json(
                                root_lease_path, compatibility
                            )
                        return existing_fence
            elif _controller_identity_is_live(existing_lease.get("controller")):
                raise InstanceStatePreflightError(
                    "another host-global deployment controller is active"
                )
            elif (
                existing_lease.get("controller") != controller
            ):
                fence_path = _deployment_fence_path(ownership_root, channel)
                if fence_path.exists():
                    existing_fence = _read_deployment_fence(ownership_root, channel)
                    fence_matches_existing = (
                        existing_fence.get("deployment_nonce")
                        == existing_lease.get("nonce")
                        and existing_fence.get("controller")
                        == existing_lease.get("controller")
                    )
                    fence_matches_legacy = (
                        legacy_lease is not None
                        and existing_fence.get("deployment_nonce")
                        == legacy_lease.get("nonce")
                        and existing_fence.get("controller")
                        == legacy_lease.get("controller")
                    )
                    if (
                        not (fence_matches_existing or fence_matches_legacy)
                        or existing_fence.get("legacy_path") != str(source)
                    ):
                        raise InstanceStatePreflightError(
                            "existing restart fence does not match the deployment lease"
                        )
        fence_path = _deployment_fence_path(ownership_root, channel)
        if (
            legacy_lease is not None
            and existing_lease is None
            and fence_path.exists()
        ):
            legacy_fence = _read_deployment_fence(
                ownership_root, channel
            )
            if (
                legacy_fence.get("deployment_nonce")
                != legacy_lease.get("nonce")
                or legacy_fence.get("controller")
                != legacy_lease.get("controller")
                or legacy_fence.get("legacy_path") != str(source)
            ):
                raise InstanceStatePreflightError(
                    "legacy restart fence does not match its deployment lease"
                )
        if (
            not lease_path.exists()
            and root_authority is None
            and fence_path.exists()
        ):
            raise InstanceStatePreflightError(
                "channel restart fence exists without its host-global lease"
            )
        nonce = (
            str(existing_lease["nonce"])
            if existing_lease is not None
            else (
                str(root_authority["nonce"])
                if compatibility_resume and root_authority is not None
                else uuid4().hex
            )
        )
        lease: dict[str, object] = {
            "schema": _DEPLOYMENT_LEASE_SCHEMA,
            "channel_id": channel,
            "nonce": nonce,
            "phase": "claimed",
            "controller": controller,
            "legacy_path": str(source),
            "diagnostic_fingerprint": diagnostic_fingerprint,
        }
        payload: dict[str, object] = {
            "schema": _DEPLOYMENT_FENCE_SCHEMA,
            "channel_id": channel,
            "deployment_nonce": nonce,
            "controller": controller,
            "legacy_path": str(source),
            "diagnostic_fingerprint": diagnostic_fingerprint,
        }
        compatibility = _compatibility_block_payload(lease)
        if not root_lease_path.exists():
            _write_private_json(root_lease_path, compatibility)
        if lease_path.exists():
            _replace_private_json(lease_path, lease)
        else:
            _write_private_json(lease_path, lease)
        if fence_path.exists():
            _replace_private_json(fence_path, payload)
        else:
            _write_private_json(fence_path, payload)
        _replace_private_json(root_lease_path, compatibility)
        return payload


def _prove_instance_state_quiescence(
    *, channel: str, host_global_root: Path, inventory_path: Path
) -> DeploymentQuiescenceProof:
    """Bind two-pass all-domain stopped inventory evidence to the host lease."""
    root = _assert_mount_root(host_global_root, "host-global")
    lease_path = _deployment_lease_path(root)
    try:
        lease = _read_deployment_lease(root)
        _require_matching_compatibility_block(
            root,
            lease,
            reconcile_from_previous_phase=True,
        )
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
        digest = hashlib.sha256(inventory_bytes).hexdigest()
        if (
            lease.get("channel_id") != channel
            or lease.get("phase") not in {"claimed", "proved"}
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
            or (
                lease.get("phase") == "proved"
                and (
                    lease.get("inventory_digest") != digest
                    or lease.get("all_consumers_stopped") is not True
                )
            )
        ):
            raise ValueError
        claim_identity = {
            key: lease.get(key)
            for key in ("channel_id", "nonce", "controller", "legacy_path")
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise InstanceStatePreflightError("complete two-pass host-wide quiescence inventory is required") from exc
    with _scalar_rollback_runtime_quiescent(root):
        lease = _read_deployment_lease(root)
        _require_matching_compatibility_block(
            root,
            lease,
            reconcile_from_previous_phase=True,
        )
        if (
            any(
                lease.get(key) != value
                for key, value in claim_identity.items()
            )
            or lease.get("phase") not in {"claimed", "proved"}
            or (
                lease.get("phase") == "proved"
                and lease.get("inventory_digest") != digest
            )
        ):
            raise InstanceStatePreflightError(
                "deployment lease changed before quiescence proof"
            )
        lease |= {
            "phase": "proved",
            "inventory_digest": digest,
            "all_consumers_stopped": True,
        }
        _replace_private_json(lease_path, lease)
        _replace_private_json(
            _legacy_deployment_lease_path(root),
            _compatibility_block_payload(lease),
        )
        proof_path = root / "deployment-quiescence-proof.json"
        controller = lease["controller"]
        if not isinstance(controller, dict):
            raise InstanceStatePreflightError(
                "valid deployment controller identity is required"
            )
        proof_payload: dict[str, object] = {
            "channel_id": channel,
            "nonce": str(lease["nonce"]),
            "inventory_digest": digest,
            "lease_path": str(lease_path),
            "controller": controller,
        }
        if proof_path.exists():
            _replace_private_json(proof_path, proof_payload)
        else:
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
    _require_matching_compatibility_block(
        ownership_root,
        lease,
        reconcile_from_previous_phase=True,
    )
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
        _replace_private_json(
            _legacy_deployment_lease_path(ownership_root),
            _compatibility_block_payload(lease),
        )

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
    """Serialize finalization against authority and other producer transitions."""

    state_mount = _assert_mount_root(instance_state_root, "instance-state")
    ownership_root = _assert_mount_root(host_global_root, "host-global")
    layout = InstanceStateLayout.for_channel(state_mount, channel)
    layout.require_existing()
    with _deployment_admission_locked(ownership_root):
        with _producer_transition_locked(layout):
            return _finish_instance_state_deployment_locked(
                channel=channel,
                instance_state_root=state_mount,
                host_global_root=ownership_root,
                legacy_path=legacy_path,
                inventory_path=inventory_path,
                backup_root=backup_root,
                restore_root=restore_root,
                quiescence_proof=quiescence_proof,
            )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _complete_instance_state_deployment_cleanup(
    host_global_root: Path,
) -> dict[str, object]:
    """Complete the durable cleanup phase and return its stored receipt."""

    ownership_root = Path(host_global_root).expanduser().resolve(strict=False)
    public_path = _deployment_lease_path(ownership_root)
    root_path = _legacy_deployment_lease_path(ownership_root)
    root_authority = _read_legacy_deployment_lease(ownership_root)
    if root_authority.get("schema") != _DEPLOYMENT_COMPATIBILITY_BLOCK_SCHEMA:
        raise InstanceStatePreflightError(
            "valid deployment cleanup compatibility block is required"
        )
    if public_path.exists():
        lease = _read_deployment_lease(ownership_root)
        _require_matching_compatibility_block(
            ownership_root,
            lease,
            reconcile_from_previous_phase=True,
        )
        result = lease.get("result")
        channel = lease.get("channel_id")
    else:
        lease = root_authority
        result = root_authority.get("result")
        channel = root_authority.get("channel_id")
    if (
        lease.get("phase") != "cleanup"
        or not isinstance(channel, str)
        or not isinstance(result, dict)
        or result.get("channel") != channel
        or result.get("restart_fence_cleared") is not True
    ):
        raise InstanceStatePreflightError(
            "valid deployment cleanup receipt is required"
    )
    _deployment_fence_path(ownership_root, channel).unlink(missing_ok=True)
    (ownership_root / "deployment-quiescence-proof.json").unlink(missing_ok=True)
    _fsync_directory(ownership_root)
    public_path.unlink(missing_ok=True)
    _fsync_directory(_deployment_public_root(ownership_root))
    current_root = _read_legacy_deployment_lease(ownership_root)
    if (
        current_root.get("schema")
        != _DEPLOYMENT_COMPATIBILITY_BLOCK_SCHEMA
        or current_root.get("phase") != "cleanup"
        or current_root.get("result") != result
        or current_root.get("channel_id") != channel
    ):
        raise InstanceStatePreflightError(
            "deployment cleanup compatibility block changed"
        )
    root_path.unlink()
    _fsync_directory(ownership_root)
    return dict(result)


def _finish_instance_state_deployment_locked(
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

    from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY

    state_mount = _assert_mount_root(instance_state_root, "instance-state")
    ownership_root = _assert_mount_root(host_global_root, "host-global")
    if _deployment_lease_path(ownership_root).exists():
        active_lease = _read_deployment_lease(ownership_root)
        _require_matching_compatibility_block(
            ownership_root,
            active_lease,
            reconcile_from_previous_phase=True,
        )
        if active_lease.get("phase") == "cleanup":
            if active_lease.get("channel_id") != channel:
                raise InstanceStatePreflightError(
                    "deployment cleanup targets another channel"
                )
            return _complete_instance_state_deployment_cleanup(ownership_root)
    else:
        root_authority = _read_legacy_deployment_lease(ownership_root)
        if (
            root_authority.get("schema")
            == _DEPLOYMENT_COMPATIBILITY_BLOCK_SCHEMA
            and root_authority.get("phase") == "cleanup"
            and root_authority.get("channel_id") == channel
        ):
            return _complete_instance_state_deployment_cleanup(ownership_root)
        raise InstanceStatePreflightError(
            "public deployment lease is required"
        )
    if quiescence_proof is None:
        raise InstanceStatePreflightError("durable quiescence proof is required")
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
            _capability=_STORAGE_MUTATION_CAPABILITY,
        )
    for registration in registry.registrations.values():
        ledger.recover_or_require_active(
            registration.vault_binding_id,
            channel_id=channel,
            root=Path(registration.path),
            _capability=_STORAGE_MUTATION_CAPABILITY,
        )
    if not ledger_snapshot.legacy_bootstrap_complete:
        raise InstanceStatePreflightError("legacy owner bootstrap did not complete")

    backup_receipt = backup.create(
        backup_root,
        quiescence_proof=quiescence_proof,
        owner_receipt_path=inventory_path,
    )
    result: dict[str, object] = {
        "channel": channel,
        "registry_revision": registry.revision,
        "final_fingerprint": final_fingerprint,
        "backup_manifest": str(backup_receipt.manifest_path),
        "restart_fence_cleared": True,
    }
    lease_path = _deployment_lease_path(ownership_root)
    lease = _read_deployment_lease(ownership_root)
    _require_matching_compatibility_block(ownership_root, lease)
    if (
        lease.get("channel_id") != channel
        or lease.get("phase") != "proved"
        or lease.get("nonce") != quiescence_proof.nonce
    ):
        raise InstanceStatePreflightError(
            "proved deployment lease changed before cleanup"
        )
    cleanup_lease = lease | {"phase": "cleanup", "result": result}
    _replace_private_json(lease_path, cleanup_lease)
    _replace_private_json(
        _legacy_deployment_lease_path(ownership_root),
        _compatibility_block_payload(cleanup_lease),
    )
    return _complete_instance_state_deployment_cleanup(ownership_root)


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
    scalar = subparsers.add_parser("scalar-rollback-preflight")
    scalar.add_argument("--channel", required=True)
    scalar.add_argument("--registry-path", type=Path, required=True)
    scalar.add_argument("--host-global-root", type=Path, required=True)
    scalar.add_argument("--rollback-vault-binding-id", required=True)
    scalar.add_argument("--legacy-path", type=Path, required=True)
    scalar.add_argument("--selected-root", type=Path, required=True)
    scalar.add_argument("--compose-base", type=Path, required=True)
    scalar.add_argument("--compose-overlay", type=Path, required=True)
    scalar.add_argument("--gateway-config", type=Path, required=True)
    scalar.add_argument("--native-launcher", type=Path, required=True)
    roll_forward = subparsers.add_parser("scalar-rollback-roll-forward")
    roll_forward.add_argument("--channel", required=True)
    roll_forward.add_argument("--instance-state-root", type=Path, required=True)
    roll_forward.add_argument("--host-global-root", type=Path, required=True)
    roll_forward.add_argument("--legacy-path", type=Path, required=True)
    roll_forward.add_argument("--inventory-path", type=Path, required=True)
    roll_forward.add_argument(
        "--quiescence-proof-path",
        type=Path,
        required=True,
    )
    activate = subparsers.add_parser("authority-cutover")
    activate.add_argument("--channel", required=True)
    activate.add_argument("--instance-state-root", type=Path, required=True)
    activate.add_argument("--host-global-root", type=Path, required=True)
    activate.add_argument("--rollback-vault-binding-id", required=True)
    activate.add_argument("--selected-root", type=Path, required=True)
    activate.add_argument("--compose-base", type=Path, required=True)
    activate.add_argument("--compose-overlay", type=Path, required=True)
    activate.add_argument("--gateway-config", type=Path, required=True)
    activate.add_argument("--native-launcher", type=Path, required=True)
    activate.add_argument("--inventory-path", type=Path, required=True)
    activate.add_argument("--quiescence-proof-path", type=Path, required=True)
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
    if args.command == "scalar-rollback-preflight":
        return _preflight_scalar_rollback(
            channel=args.channel,
            registry_path=args.registry_path,
            host_global_root=args.host_global_root,
            rollback_vault_binding_id=args.rollback_vault_binding_id,
            legacy_path=args.legacy_path,
            selected_root=args.selected_root,
            compose_base=args.compose_base,
            compose_overlay=args.compose_overlay,
            gateway_config=args.gateway_config,
            native_launcher=args.native_launcher,
        )
    if args.command == "authority-cutover":
        return _activate_mvr01c_authority(
            channel=args.channel,
            instance_state_root=args.instance_state_root,
            host_global_root=args.host_global_root,
            rollback_vault_binding_id=args.rollback_vault_binding_id,
            selected_root=args.selected_root,
            compose_base=args.compose_base,
            compose_overlay=args.compose_overlay,
            gateway_config=args.gateway_config,
            native_launcher=args.native_launcher,
            inventory_path=args.inventory_path,
            quiescence_proof_path=args.quiescence_proof_path,
        )
    if args.command == "scalar-rollback-roll-forward":
        return _roll_forward_scalar_rollback(
            channel=args.channel,
            instance_state_root=args.instance_state_root,
            host_global_root=args.host_global_root,
            legacy_path=args.legacy_path,
            inventory_path=args.inventory_path,
            quiescence_proof_path=args.quiescence_proof_path,
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
        try:
            proof = _load_deployment_quiescence_proof(
                args.quiescence_proof_path
            )
        except InstanceStatePreflightError:
            if _deployment_lease_path(args.host_global_root).exists():
                lease = _read_deployment_lease(args.host_global_root)
            else:
                lease = _read_legacy_deployment_lease(
                    args.host_global_root
                )
            if (
                lease.get("phase") != "cleanup"
                or lease.get("channel_id") != args.channel
                or (
                    lease.get("schema")
                    not in {
                        _DEPLOYMENT_LEASE_SCHEMA,
                        _DEPLOYMENT_COMPATIBILITY_BLOCK_SCHEMA,
                    }
                )
            ):
                raise
            proof = None
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
