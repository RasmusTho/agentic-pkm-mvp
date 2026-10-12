from __future__ import annotations

import hashlib
import inspect
import json
import os
import fcntl
import traceback
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

import app.instance.runtime as runtime_module
import app.instance.ownership_ledger as ownership_module

from app.instance.filesystem_identity import (
    FilesystemRootIdentity,
    resolve_filesystem_root_identity,
    same_filesystem_root,
)
from app.instance.instance_state import (
    DeploymentQuiescenceProof,
    InstanceStateLayout,
    InstanceStatePreflightError,
    validate_registry_disjoint_from_content,
)
from app.instance._storage_boundary import _StorageMutationCapability
from app.instance.ownership_ledger import (
    LedgerCollisionError,
    LedgerError,
    LedgerKeyError,
    LegacyOwner,
    OwnershipLedger,
)
from app.instance.runtime import (
    InstanceRegistryRuntime,
    _begin_instance_state_deployment,
    _bind_legacy_owner_inventory_to_proof,
    _deployment_fence_path,
    _deployment_lease_path,
    _prove_instance_state_quiescence,
)
from app.instance.vault_registry import (
    AppLocalSettingsStore,
    CapabilityNotReadyError,
    RegistryError,
    RemovalTombstone,
    TransferLineage,
    VaultRegistration,
)
from app.vault.manager import VaultManager, _initial_settings_files, iter_vault_markdown_files
from app.vault.markdown_settings import MarkdownSettingsStore
from tests._mvr_default_vault_harness import activate
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


def _runtime(tmp_path: Path, channel: str, host_global: Path) -> InstanceRegistryRuntime:
    return InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / channel, channel),
        host_global,
    )


def _runtime_state_bytes(
    tmp_path: Path, *runtimes: InstanceRegistryRuntime
) -> dict[Path, bytes]:
    roots = {
        root.resolve(strict=False)
        for runtime in runtimes
        for root in (runtime.layout.root, runtime.ledger.root)
    }
    return {
        path.relative_to(tmp_path): path.read_bytes()
        for root in roots
        for path in root.rglob("*")
        if path.is_file()
    }


def _mechanically_register_nested_binding(
    runtime: InstanceRegistryRuntime, child_root: Path
) -> VaultRegistration:
    """Exercise the dormant schema through its existing store/ledger primitives."""

    identity = resolve_filesystem_root_identity(child_root)
    current = runtime.registry.load()
    validate_registry_disjoint_from_content(
        runtime.layout.registry_path,
        [Path(identity.canonical_path)]
        + [Path(item.path) for item in current.registrations.values()],
    )
    for item in current.registrations.values():
        if same_filesystem_root(resolve_filesystem_root_identity(item.path), identity):
            raise RegistryError("registry path identity collision")
    registration = VaultRegistration(
        vault_binding_id=f"binding-test-{uuid4()}",
        ref=f"path:{identity.canonical_path}",
        path=identity.canonical_path,
        vault_id="child",
        local_instance_id=f"local-test-{uuid4()}",
        extensions={"status": "initialized", "contentEpoch": 1},
    )
    runtime.ledger.reserve(
        channel_id=runtime.layout.channel_id,
        vault_binding_id=registration.vault_binding_id,
        root=Path(registration.path),
        allow_same_channel_nested=True,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    runtime.registry.register(
        registration,
        expected_revision=current.revision,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    runtime.ledger.activate(
        registration.vault_binding_id,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    return registration


def _mechanically_prepare_transfer(
    source_runtime: InstanceRegistryRuntime,
    destination_runtime: InstanceRegistryRuntime,
    vault_binding_id: str,
) -> str:
    """Prepare dormant transfer state without calling a runtime authority façade."""

    source_snapshot = source_runtime.registry.load()
    source = source_snapshot.registrations[vault_binding_id]
    destination_binding_id = f"binding-test-{uuid4()}"
    reservation = source_runtime.ledger.begin_transfer(
        source_binding_id=vault_binding_id,
        destination_channel_id=destination_runtime.layout.channel_id,
        destination_binding_id=destination_binding_id,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    destination_snapshot = destination_runtime.registry.load()
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
            source_channel_id=source_runtime.layout.channel_id,
            destination_channel_id=destination_runtime.layout.channel_id,
            source_registry_revision=source_snapshot.revision + 1,
            destination_registry_revision=destination_snapshot.revision + 1,
            ownership_transfer_id=reservation.transfer_id,
        ),
    )
    registrations = dict(destination_snapshot.registrations)
    registrations[destination_registration.vault_binding_id] = destination_registration
    destination_runtime.registry.commit_state(
        registrations=registrations,
        transfer_lineage=lineage,
        expected_revision=destination_snapshot.revision,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    return destination_registration.vault_binding_id


def _mechanically_recover_transfer(
    source_runtime: InstanceRegistryRuntime,
    destination_runtime: InstanceRegistryRuntime,
) -> str:
    """Finish dormant transfer state through existing store/ledger primitives."""

    transfer = source_runtime.ledger.load().transfer
    if transfer is None:
        lineage = destination_runtime.registry.load().transfer_lineage
        if not lineage:
            raise LedgerError("no transfer reservation is recoverable")
        return lineage[-1].destination_binding_id
    source_snapshot = source_runtime.registry.load()
    destination_snapshot = destination_runtime.registry.load()
    source_registration = source_snapshot.registrations.get(transfer.source_binding_id)
    if source_registration is not None:
        registrations = dict(source_snapshot.registrations)
        del registrations[transfer.source_binding_id]
        tombstones = dict(source_snapshot.removal_tombstones)
        tombstones[transfer.source_binding_id] = _removal_tombstone(source_registration)
        source_runtime.registry.commit_state(
            registrations=registrations,
            removal_tombstones=tombstones,
            expected_revision=source_snapshot.revision,
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
    if transfer.destination_binding_id not in destination_snapshot.registrations:
        raise LedgerError("prepared transfer is missing its destination registration")
    source_runtime.ledger.activate_transfer(
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    return transfer.destination_binding_id


def _removal_tombstone(registration: VaultRegistration) -> RemovalTombstone:
    epoch = registration.extensions.get("contentEpoch", 1)
    return RemovalTombstone(
        vault_binding_id=registration.vault_binding_id,
        ref=registration.ref,
        path=registration.path,
        vault_id=registration.vault_id,
        local_instance_id=registration.local_instance_id,
        content_epoch=epoch if isinstance(epoch, int) and epoch >= 1 else 1,
    )


def _mechanically_remove_binding(
    runtime: InstanceRegistryRuntime, vault_binding_id: str
) -> RemovalTombstone:
    current = runtime.registry.load()
    registration = current.registrations[vault_binding_id]
    registrations = dict(current.registrations)
    del registrations[vault_binding_id]
    tombstones = dict(current.removal_tombstones)
    retired = _removal_tombstone(registration)
    tombstones[vault_binding_id] = retired
    runtime.registry.commit_state(
        registrations=registrations,
        removal_tombstones=tombstones,
        expected_revision=current.revision,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    runtime.ledger.release_to_tombstone(
        vault_binding_id,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    return retired


def _mechanically_reactivate_binding(
    runtime: InstanceRegistryRuntime, root: Path
) -> VaultRegistration:
    current = runtime.registry.load()
    identity = resolve_filesystem_root_identity(root)
    matched = next(
        tombstone
        for tombstone in current.removal_tombstones.values()
        if same_filesystem_root(
            resolve_filesystem_root_identity(tombstone.path),
            identity,
        )
    )
    runtime.ledger.reactivate(
        matched.vault_binding_id,
        channel_id=runtime.layout.channel_id,
        root=root,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    registration = VaultRegistration(
        vault_binding_id=matched.vault_binding_id,
        ref=matched.ref,
        path=identity.canonical_path,
        vault_id=matched.vault_id,
        local_instance_id=matched.local_instance_id,
        extensions={"contentEpoch": matched.content_epoch + 1},
    )
    registrations = dict(current.registrations)
    registrations[registration.vault_binding_id] = registration
    runtime.registry.commit_state(
        registrations=registrations,
        expected_revision=current.revision,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    return registration


def test_dormant_runtime_api_exports_no_caller_constructible_activation_seam() -> None:
    assert runtime_module.__all__ == ["InstanceRegistryRuntime"]
    assert not hasattr(runtime_module, "LifecycleActivationProof")
    assert not hasattr(runtime_module, "TransferActivationProof")
    runtime_source = inspect.getsource(InstanceRegistryRuntime)
    for forbidden_primitive in (
        ".begin_transfer(",
        ".activate_transfer(",
        ".release_to_tombstone(",
        ".reactivate(",
    ):
        assert forbidden_primitive not in runtime_source
    for method_name in (
        "prepare_nested_registration",
        "transfer_to",
        "recover_transfer",
        "relocate",
        "remove",
        "reactivate_removed",
    ):
        parameters = inspect.signature(
            getattr(InstanceRegistryRuntime, method_name)
        ).parameters
        assert "proof" not in parameters
        assert "crash_after" not in parameters
        method_source = inspect.getsource(getattr(InstanceRegistryRuntime, method_name))
        assert "CapabilityNotReadyError" in method_source
        assert "self.registry" not in method_source
        assert "self.ledger" not in method_source


def test_store_and_ledger_mutators_reject_uncapable_callers(tmp_path) -> None:
    """Public storage objects reject before any registry or ledger write."""

    with pytest.raises(
        TypeError,
        match="storage mutation capability is not caller-constructible",
    ):
        _StorageMutationCapability()
    forged_capability = object.__new__(_StorageMutationCapability)

    host_global = tmp_path / "host-global"
    runtime = _runtime(tmp_path, "dev", host_global)
    root = tmp_path / "vault"
    root.mkdir()
    registration = runtime.bootstrap_env_binding(
        vault_root=root,
        watcher_vault_path=root,
    )
    snapshot = runtime.registry.load()
    replacement = replace(
        registration,
        vault_name="must-not-persist",
    )
    extra = VaultRegistration(
        vault_binding_id="binding-uncapable",
        ref="path:/uncapable",
        path="/uncapable",
        vault_id="vault-uncapable",
        local_instance_id="local-uncapable",
    )
    before = _runtime_state_bytes(tmp_path, runtime)
    mutations = (
        lambda: runtime.registry.register(extra),
        lambda: runtime.registry.update_registration(replacement),
        lambda: runtime.registry.remove_registration(registration.vault_binding_id),
        lambda: runtime.registry.commit_state(
            registrations=dict(snapshot.registrations),
            expected_revision=snapshot.revision,
        ),
        lambda: runtime.registry.set_extension_state(
            principal_state={},
            background_state={},
            runtime_floors={},
        ),
        lambda: runtime.ledger.reserve(
            channel_id="test",
            vault_binding_id="binding-uncapable",
            root=root,
        ),
        lambda: runtime.ledger.activate(registration.vault_binding_id),
        lambda: runtime.ledger.begin_transfer(
            source_binding_id=registration.vault_binding_id,
            destination_channel_id="test",
            destination_binding_id="binding-destination",
        ),
        lambda: runtime.ledger.activate_transfer(),
        lambda: runtime.ledger.release_to_tombstone(registration.vault_binding_id),
        lambda: runtime.ledger.reactivate(
            registration.vault_binding_id,
            channel_id="dev",
            root=root,
        ),
        lambda: runtime.ledger.rotate_key(precondition=lambda snapshot, roots: None),
    )

    for mutate in mutations:
        with pytest.raises(
            CapabilityNotReadyError,
            match="private MVR storage mutation capability is required",
        ):
            mutate()
        assert _runtime_state_bytes(tmp_path, runtime) == before

    with pytest.raises(
        CapabilityNotReadyError,
        match="private MVR storage mutation capability is required",
    ):
        runtime.registry.register(extra, _capability=forged_capability)
    assert _runtime_state_bytes(tmp_path, runtime) == before

    with pytest.raises(
        CapabilityNotReadyError,
        match="private MVR storage mutation capability is required",
    ):
        runtime.ledger.recover_or_require_active(
            registration.vault_binding_id,
            channel_id="dev",
            root=root,
        )
    assert _runtime_state_bytes(tmp_path, runtime) == before

    with pytest.raises(
        CapabilityNotReadyError,
        match="private MVR storage mutation capability is required",
    ):
        runtime.ledger.bootstrap_legacy_owners(
            [], inventory_complete=True, writers_drained=True
        )
    assert _runtime_state_bytes(tmp_path, runtime) == before


def _rotation_authority(
    runtime: InstanceRegistryRuntime,
    owners: list[tuple[str, str, Path]],
) -> tuple[DeploymentQuiescenceProof, Path]:
    controller = {
        "pid": os.getpid(),
        "start_token": "linux:" + "0" * 64,
    }
    _begin_instance_state_deployment(
        channel=runtime.layout.channel_id,
        instance_state_root=runtime.layout.root.parent,
        host_global_root=runtime.ledger.root,
        legacy_path=runtime.layout.root / "missing-legacy.md",
        controller_pid=controller["pid"],
        controller_start_token=controller["start_token"],
    )
    empty_domains = {domain: [] for domain in ("dev", "native", "prod", "test")}
    empty_digest = hashlib.sha256(
        json.dumps(empty_domains, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    quiescence_inventory = runtime.ledger.root / "deployment-quiescence-inventory.json"
    quiescence_inventory.write_text(
        json.dumps(
            {
                "schema": "agentic-pkm.host-deployment-quiescence.v2",
                "inventory_complete": True,
                "all_consumers_stopped": True,
                "probe_count": 2,
                "controller": controller,
                "domains": empty_domains,
                "snapshot_digests": [empty_digest, empty_digest],
            }
        ),
        encoding="utf-8",
    )
    os.chmod(quiescence_inventory, 0o600)
    proof = _prove_instance_state_quiescence(
        channel=runtime.layout.channel_id,
        host_global_root=runtime.ledger.root,
        inventory_path=quiescence_inventory,
    )
    owner_rows = [
        {
            "channel_id": channel_id,
            "vault_binding_id": binding_id,
            "root": str(root),
        }
        for channel_id, binding_id, root in owners
    ]
    owner_identities = []
    for channel_id, _, root in owners:
        metadata = os.stat(root)
        owner_identities.append(
            {
                "channel_id": channel_id,
                "root": str(root),
                "identity": f"inode:{metadata.st_dev}:{metadata.st_ino}",
                "ancestor_identities": sorted(
                    f"path:{ancestor}" for ancestor in root.resolve().parents
                ),
            }
        )
    source_evidence = {
        "docker": [],
        "config": [],
        "owners": owner_rows,
        "owner_identities": owner_identities,
    }
    owner_inventory = runtime.ledger.root / "legacy-owner-inventory.json"
    owner_inventory.write_text(
        json.dumps(
            {
                "schema": "agentic-pkm.legacy-owner-inventory.v1",
                "inventory_complete": True,
                "writers_drained": True,
                "source_probe_count": 2,
                "validated_after_quiescence": True,
                "source_digest": hashlib.sha256(
                    json.dumps(
                        source_evidence, sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest(),
                "source_evidence": source_evidence,
                "owners": owner_rows,
            }
        ),
        encoding="utf-8",
    )
    os.chmod(owner_inventory, 0o600)
    return (
        _bind_legacy_owner_inventory_to_proof(
            inventory_path=owner_inventory,
            quiescence_proof=proof,
            channel=runtime.layout.channel_id,
            host_global_root=runtime.ledger.root,
        ),
        owner_inventory,
    )


def test_overlapping_content_roots_cannot_be_active_in_two_channels(tmp_path) -> None:
    shared = tmp_path / "content"
    child = shared / "child"
    child.mkdir(parents=True)
    alias = tmp_path / "content-alias"
    alias.symlink_to(shared, target_is_directory=True)
    host_global = tmp_path / "host-global"
    dev = _runtime(tmp_path, "dev", host_global)
    prod = _runtime(tmp_path, "prod", host_global)
    dev.bootstrap_env_binding(vault_root=shared, watcher_vault_path=shared)

    for conflicting in (shared, child, alias):
        with pytest.raises(LedgerCollisionError):
            prod.bootstrap_env_binding(vault_root=conflicting, watcher_vault_path=conflicting)

    payload = host_global.joinpath("ownership-ledger.json").read_text(encoding="utf-8")
    assert str(shared.resolve()) not in payload


def test_same_channel_nested_vaults_preserve_child_boundary(tmp_path) -> None:
    parent = tmp_path / "parent"
    child = parent / "private-child"
    (parent / "settings").mkdir(parents=True)
    (parent / "settings" / "vault.md").write_text("---\nvaultId: parent\n---\n", encoding="utf-8")
    (parent / "parent.md").write_text("parent", encoding="utf-8")
    (child / "settings").mkdir(parents=True)
    (child / "settings" / "vault.md").write_text("---\nvaultId: child\n---\n", encoding="utf-8")
    (child / "secret.md").write_text("secret", encoding="utf-8")
    runtime = _runtime(tmp_path, "dev", tmp_path / "host-global")
    runtime.bootstrap_env_binding(vault_root=parent, watcher_vault_path=parent)
    _mechanically_register_nested_binding(runtime, child)

    assert [path.name for path in iter_vault_markdown_files(parent)] == ["parent.md"]
    assert [path.name for path in iter_vault_markdown_files(child)] == ["secret.md"]
    assert len(runtime.registry.load().registrations) == 2
    with pytest.raises(RegistryError):
        _mechanically_register_nested_binding(runtime, child.resolve())


def test_transfer_is_dormant_until_foreground_ownership_floor(tmp_path) -> None:
    host_global = tmp_path / "host-global"
    source = _runtime(tmp_path, "dev", host_global)
    destination = _runtime(tmp_path, "test", host_global)
    root = tmp_path / "vault"
    (root / "settings").mkdir(parents=True)
    (root / "settings" / "vault.md").write_text(
        "---\nvaultId: vault-transfer\n---\n", encoding="utf-8"
    )
    registration = source.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)

    with pytest.raises(CapabilityNotReadyError, match="MVR-05C foreground ownership floor"):
        source.transfer_to(destination, registration.vault_binding_id)
    assert source.ledger.active_owner(registration.vault_binding_id).channel_id == "dev"


def test_direct_or_forged_transfer_call_cannot_mutate_dormant_protocol(tmp_path) -> None:
    host_global = tmp_path / "host-global"
    source = _runtime(tmp_path, "dev", host_global)
    destination = _runtime(tmp_path, "test", host_global)
    root = tmp_path / "vault"
    root.mkdir()
    registration = source.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    destination.registry.load()
    before = _runtime_state_bytes(tmp_path, source, destination)
    ledger_before = source.ledger.load()

    with pytest.raises(CapabilityNotReadyError, match="MVR-05C foreground ownership floor"):
        source.transfer_to(destination, registration.vault_binding_id)

    with pytest.raises(TypeError, match="unexpected keyword argument 'proof'"):
        source.transfer_to(destination, registration.vault_binding_id, proof=True)  # type: ignore[call-arg]

    assert _runtime_state_bytes(tmp_path, source, destination) == before
    assert source.ledger.load() == ledger_before


def test_direct_transfer_recovery_cannot_retire_source_or_activate_destination(tmp_path) -> None:
    host_global = tmp_path / "host-global"
    source = _runtime(tmp_path, "dev", host_global)
    destination = _runtime(tmp_path, "test", host_global)
    root = tmp_path / "vault"
    root.mkdir()
    registration = source.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    _mechanically_prepare_transfer(
        source,
        destination,
        registration.vault_binding_id,
    )
    before = _runtime_state_bytes(tmp_path, source, destination)
    ledger_before = source.ledger.load()

    with pytest.raises(CapabilityNotReadyError, match="MVR-05C foreground ownership floor"):
        source.recover_transfer(destination)

    assert _runtime_state_bytes(tmp_path, source, destination) == before
    assert source.ledger.load() == ledger_before


def test_transfer_mints_destination_binding_and_preserves_lineage_atomically(tmp_path) -> None:
    host_global = tmp_path / "host-global"
    source = _runtime(tmp_path, "dev", host_global)
    destination = _runtime(tmp_path, "test", host_global)
    root = tmp_path / "vault"
    (root / "settings").mkdir(parents=True)
    (root / "settings" / "vault.md").write_text(
        "---\nvaultId: vault-transfer\n---\n", encoding="utf-8"
    )
    registration = source.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    _mechanically_prepare_transfer(
        source,
        destination,
        registration.vault_binding_id,
    )
    third_channel = _runtime(tmp_path, "prod", host_global)
    with pytest.raises(LedgerCollisionError):
        third_channel.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    destination_binding = _mechanically_recover_transfer(source, destination)

    assert destination_binding != registration.vault_binding_id
    assert registration.vault_binding_id not in source.registry.load().registrations
    assert destination_binding in destination.registry.load().registrations
    lineage = destination.registry.load().transfer_lineage
    assert lineage[-1].source_binding_id == registration.vault_binding_id
    assert lineage[-1].destination_binding_id == destination_binding
    assert lineage[-1].vault_id == "vault-transfer"
    assert lineage[-1].source_channel_id == "dev"
    assert lineage[-1].destination_channel_id == "test"
    assert lineage[-1].source_registry_revision == 2
    assert lineage[-1].destination_registry_revision == 1
    ownership_lineage = source.ledger.load().transfer_lineage[-1]
    assert ownership_lineage.transfer_id == lineage[-1].ownership_transfer_id
    assert ownership_lineage.source_binding_id == registration.vault_binding_id
    assert ownership_lineage.destination_binding_id == destination_binding
    before_rotation = ownership_lineage.root_fingerprint
    rotation_proof, owner_inventory = _rotation_authority(
        source,
        [("test", destination_binding, root)],
    )
    source.rotate_ledger_key(
        quiescence_proof=rotation_proof,
        legacy_owner_inventory_path=owner_inventory,
    )
    assert source.ledger.load().transfer_lineage[-1].root_fingerprint != before_rotation
    assert source.ledger.active_owner(destination_binding).channel_id == "test"
    assert source.ledger.active_owner(registration.vault_binding_id) is None


def test_transfer_preserves_local_clone_identity_across_channel_binding_change(tmp_path) -> None:
    host_global = tmp_path / "host-global"
    source = _runtime(tmp_path, "dev", host_global)
    destination = _runtime(tmp_path, "test", host_global)
    root = tmp_path / "vault"
    root.mkdir()
    original = source.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    _mechanically_prepare_transfer(
        source,
        destination,
        original.vault_binding_id,
    )
    result = _mechanically_recover_transfer(source, destination)
    tombstone = source.registry.load().removal_tombstones[original.vault_binding_id]
    destination_registration = destination.registry.load().registrations[result]
    lineage = destination.registry.load().transfer_lineage[-1]

    assert tombstone.local_instance_id == original.local_instance_id
    assert destination_registration.local_instance_id == original.local_instance_id
    assert lineage.local_instance_id == original.local_instance_id


def test_relocation_is_dormant_until_all_consumer_effect_leases(tmp_path) -> None:
    runtime = _runtime(tmp_path, "dev", tmp_path / "host-global")
    root = tmp_path / "vault"
    moved = tmp_path / "moved"
    root.mkdir()
    moved.mkdir()
    registration = runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    before = runtime.registry.load()

    with pytest.raises(CapabilityNotReadyError, match="MVR-06C consumer effect-lease floor"):
        runtime.relocate(registration.vault_binding_id, moved)

    after = runtime.registry.load()
    assert after.revision == before.revision
    assert after.registrations[registration.vault_binding_id].path == str(root.resolve())


def test_registration_removal_is_dormant_until_all_consumer_floors(tmp_path) -> None:
    runtime = _runtime(tmp_path, "dev", tmp_path / "host-global")
    root = tmp_path / "vault"
    root.mkdir()
    registration = runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    before = runtime.registry.load()

    with pytest.raises(CapabilityNotReadyError, match="MVR-06B consumer drain floor"):
        runtime.remove(registration.vault_binding_id)

    assert runtime.registry.load() == before
    assert runtime.ledger.active_owner(registration.vault_binding_id) is not None


def test_direct_or_forged_removal_call_cannot_mutate_dormant_protocol(tmp_path) -> None:
    runtime = _runtime(tmp_path, "dev", tmp_path / "host-global")
    root = tmp_path / "vault"
    root.mkdir()
    registration = runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    before = _runtime_state_bytes(tmp_path, runtime)
    ledger_before = runtime.ledger.load()

    with pytest.raises(CapabilityNotReadyError, match="MVR-06B consumer drain floor"):
        runtime.remove(registration.vault_binding_id)

    with pytest.raises(TypeError, match="unexpected keyword argument 'proof'"):
        runtime.remove(registration.vault_binding_id, proof=True)  # type: ignore[call-arg]

    assert _runtime_state_bytes(tmp_path, runtime) == before
    assert runtime.ledger.load() == ledger_before


def test_forged_reactivation_and_bootstrap_cannot_mutate_removed_lineage(tmp_path) -> None:
    runtime = _runtime(tmp_path, "dev", tmp_path / "host-global")
    root = tmp_path / "vault"
    root.mkdir()
    registration = runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    _mechanically_remove_binding(runtime, registration.vault_binding_id)
    before = _runtime_state_bytes(tmp_path, runtime)
    ledger_before = runtime.ledger.load()

    with pytest.raises(CapabilityNotReadyError, match="MVR-06B consumer drain floor"):
        runtime.reactivate_removed(root)
    with pytest.raises(TypeError, match="unexpected keyword argument 'proof'"):
        runtime.reactivate_removed(root, proof=True)  # type: ignore[call-arg]
    assert _runtime_state_bytes(tmp_path, runtime) == before
    assert runtime.ledger.load() == ledger_before

    with pytest.raises(CapabilityNotReadyError, match="MVR-06B consumer drain floor"):
        runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    assert _runtime_state_bytes(tmp_path, runtime) == before
    assert runtime.ledger.load() == ledger_before


def test_removed_binding_reregistration_preserves_tombstone_lineage(tmp_path) -> None:
    runtime = _runtime(tmp_path, "dev", tmp_path / "host-global")
    root = tmp_path / "vault"
    root.mkdir()
    registration = runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    _mechanically_remove_binding(runtime, registration.vault_binding_id)

    with pytest.raises(CapabilityNotReadyError, match="MVR-06B consumer drain floor"):
        runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    reactivated = _mechanically_reactivate_binding(runtime, root)
    assert reactivated.vault_binding_id == registration.vault_binding_id
    assert reactivated.local_instance_id == registration.local_instance_id
    assert reactivated.extensions["contentEpoch"] == 2
    assert runtime.registry.load().removal_tombstones[registration.vault_binding_id].content_epoch == 1


def test_populated_registry_with_lost_ledger_and_key_fails_without_mutation(tmp_path) -> None:
    host_global = tmp_path / "host-global"
    runtime = _runtime(tmp_path, "prod", host_global)
    root = tmp_path / "vault"
    root.mkdir()
    runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)

    runtime.ledger.path.unlink()
    runtime.ledger.key_path.unlink()
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for state_root in (runtime.layout.root, host_global)
        for path in state_root.iterdir()
        if path.is_file()
    }

    with pytest.raises(LedgerKeyError, match="requires protected ownership"):
        runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)

    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for state_root in (runtime.layout.root, host_global)
        for path in state_root.iterdir()
        if path.is_file()
    }
    assert after == before
    assert not runtime.ledger.path.exists()
    assert not runtime.ledger.key_path.exists()


def test_retry_recovers_pending_owner_after_registry_commit(tmp_path, monkeypatch) -> None:
    runtime = _runtime(tmp_path, "dev", tmp_path / "host-global")
    root = tmp_path / "vault"
    root.mkdir()
    original_activate = runtime.ledger.activate
    failures = 0

    def fail_once(
        vault_binding_id: str,
        *,
        _capability: _StorageMutationCapability | None = None,
    ):
        nonlocal failures
        failures += 1
        if failures == 1:
            raise RuntimeError("injected activate failure")
        return original_activate(vault_binding_id, _capability=_capability)

    monkeypatch.setattr(runtime.ledger, "activate", fail_once)
    with pytest.raises(RuntimeError, match="injected activate failure"):
        runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)

    committed = next(iter(runtime.registry.load().registrations.values()))
    assert runtime.ledger.active_owner(committed.vault_binding_id) is None
    recovered = runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    assert recovered.vault_binding_id == committed.vault_binding_id
    assert runtime.ledger.active_owner(committed.vault_binding_id) is not None


def test_first_upgrade_seeds_all_legacy_channel_owners_before_claim(tmp_path) -> None:
    host_global = tmp_path / "host-global"
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    ledger = OwnershipLedger(host_global)
    seeded = ledger.bootstrap_legacy_owners(
        [
            LegacyOwner("dev", "legacy-dev", first),
            LegacyOwner("prod", "legacy-prod", second),
        ],
        inventory_complete=True,
        writers_drained=True,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    assert {lease.channel_id for lease in seeded.leases.values()} == {"dev", "prod"}

    missing = OwnershipLedger(tmp_path / "missing-host-global")
    with pytest.raises(LedgerCollisionError, match="complete"):
        missing.bootstrap_legacy_owners(
            [],
            inventory_complete=False,
            writers_drained=True,
            _capability=STORAGE_MUTATION_CAPABILITY,
        )


def test_env_only_bootstrap_atomically_enrolls_one_stable_binding_or_fails_closed(tmp_path) -> None:
    runtime = _runtime(tmp_path, "dev", tmp_path / "host-global")
    root = tmp_path / "vault"
    root.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    registration = runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=alias)
    again = runtime.bootstrap_env_binding(vault_root=alias, watcher_vault_path=root)

    assert again.vault_binding_id == registration.vault_binding_id
    assert len(runtime.registry.load().registrations) == 1
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(RegistryError, match="conflicting bootstrap roots"):
        runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=other)


def test_host_global_ledger_key_is_durable_shared_and_rotates_atomically(tmp_path) -> None:
    host_global = tmp_path / "host-global"
    runtime = _runtime(tmp_path, "dev", host_global)
    root = tmp_path / "vault"
    root.mkdir()
    registration = runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    before = runtime.ledger.load()
    restarted = _runtime(tmp_path, "dev-restart", host_global)
    assert restarted.ledger.load().key_id == before.key_id

    key_before_unfenced = runtime.ledger.key_path.read_bytes()
    ledger_before_unfenced = runtime.ledger.path.read_bytes()
    with pytest.raises(InstanceStatePreflightError, match="quiescence proof"):
        runtime.rotate_ledger_key()
    assert runtime.ledger.key_path.read_bytes() == key_before_unfenced
    assert runtime.ledger.path.read_bytes() == ledger_before_unfenced

    rotation_proof, owner_inventory = _rotation_authority(
        runtime,
        [("dev", registration.vault_binding_id, root)],
    )
    with pytest.raises(RuntimeError, match="injected crash"):
        runtime.rotate_ledger_key(
            quiescence_proof=rotation_proof,
            legacy_owner_inventory_path=owner_inventory,
            crash_after="key_commit",
        )
    rotated = runtime.ledger.load()
    assert rotated.key_id != before.key_id
    assert rotated.generation == before.generation + 1
    assert runtime.ledger.active_owner(registration.vault_binding_id) is not None
    os.chmod(host_global / "ownership-key.json", 0o644)
    with pytest.raises(LedgerKeyError):
        runtime.ledger.load()


def test_key_rotation_preserves_removed_root_tombstone_match_on_reregistration(tmp_path) -> None:
    runtime = _runtime(tmp_path, "dev", tmp_path / "host-global")
    root = tmp_path / "uninitialized"
    root.mkdir()
    registration = runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    _mechanically_remove_binding(runtime, registration.vault_binding_id)
    rotation_proof, owner_inventory = _rotation_authority(runtime, [])
    runtime.rotate_ledger_key(
        quiescence_proof=rotation_proof,
        legacy_owner_inventory_path=owner_inventory,
    )

    reactivated = _mechanically_reactivate_binding(runtime, root)
    assert reactivated.vault_binding_id == registration.vault_binding_id


def _protected_rotation_state(runtime: InstanceRegistryRuntime) -> dict[str, bytes | None]:
    return {
        path.name: path.read_bytes() if path.exists() else None
        for path in (
            runtime.ledger.key_path,
            runtime.ledger.path,
            runtime.ledger.rotation_path,
        )
    }


def test_key_rotation_rejects_public_test_only_proof_bypass_without_mutation(
    tmp_path,
) -> None:
    runtime = _runtime(tmp_path, "dev", tmp_path / "host-global")
    root = tmp_path / "vault"
    root.mkdir()
    registration = runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    proof, owner_inventory = _rotation_authority(
        runtime,
        [("dev", registration.vault_binding_id, root)],
    )
    assert "_test_only" not in DeploymentQuiescenceProof.__dataclass_fields__
    assert not hasattr(DeploymentQuiescenceProof, "for_test")
    _rewrite_owner_receipt(
        owner_inventory,
        lambda payload: payload.update(
            {
                "controller": {
                    "pid": os.getpid() + 1,
                    "start_token": "linux:" + "f" * 64,
                }
            }
        ),
    )
    before = _protected_rotation_state(runtime)
    generation_before = runtime.ledger.load().generation

    with pytest.raises(InstanceStatePreflightError):
        runtime.rotate_ledger_key(
            quiescence_proof=proof,
            legacy_owner_inventory_path=owner_inventory,
        )

    assert _protected_rotation_state(runtime) == before
    assert runtime.ledger.load().generation == generation_before


@pytest.mark.parametrize("missing_artifact", ["key", "ledger"])
def test_key_rotation_requires_established_artifacts_without_creating_them(
    tmp_path, missing_artifact
) -> None:
    runtime = _runtime(tmp_path, "dev", tmp_path / "host-global")
    runtime.ledger.root.mkdir(mode=0o700)
    if missing_artifact == "ledger":
        runtime.ledger.load()
        runtime.ledger.path.unlink()
    proof, owner_inventory = _rotation_authority(runtime, [])
    before = _protected_rotation_state(runtime)

    with pytest.raises(LedgerKeyError):
        runtime.rotate_ledger_key(
            quiescence_proof=proof,
            legacy_owner_inventory_path=owner_inventory,
        )

    assert _protected_rotation_state(runtime) == before


def _rewrite_owner_receipt(path: Path, mutate) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    if payload.get("receipt_digest") != "invalid":
        payload["receipt_digest"] = hashlib.sha256(
            json.dumps(
                {key: value for key, value in payload.items() if key != "receipt_digest"},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    else:
        payload["receipt_digest"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(path, 0o600)


def _unbind_owner_receipt(payload: dict[str, object]) -> None:
    for key in (
        "deployment_nonce",
        "controller",
        "quiescence_inventory_digest",
        "receipt_digest",
    ):
        payload.pop(key, None)


@pytest.mark.parametrize(
    "invalid_receipt",
    [
        "stale-receipt",
        "unbound-receipt",
        "swapped-receipt",
        "forged-source-digest",
        "forged-receipt-digest",
        "wrong-nonce",
        "wrong-controller",
        "wrong-inventory-digest",
    ],
)
def test_key_rotation_rejects_unbound_or_forged_owner_receipt_without_mutation(
    tmp_path, invalid_receipt
) -> None:
    runtime = _runtime(tmp_path, "dev", tmp_path / "host-global")
    root = tmp_path / "vault"
    root.mkdir()
    registration = runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    proof, owner_inventory = _rotation_authority(
        runtime,
        [("dev", registration.vault_binding_id, root)],
    )
    if invalid_receipt == "stale-receipt":
        stale_receipt = owner_inventory.read_bytes()
        _deployment_fence_path(runtime.ledger.root, "dev").unlink()
        _deployment_lease_path(runtime.ledger.root).unlink()
        (runtime.ledger.root / "deployment-host-global-lease.json").unlink()
        (runtime.ledger.root / "deployment-quiescence-proof.json").unlink()
        proof, owner_inventory = _rotation_authority(
            runtime,
            [("dev", registration.vault_binding_id, root)],
        )
        owner_inventory.write_bytes(stale_receipt)
        os.chmod(owner_inventory, 0o600)
    elif invalid_receipt == "unbound-receipt":
        _rewrite_owner_receipt(owner_inventory, _unbind_owner_receipt)
    elif invalid_receipt == "swapped-receipt":
        _rewrite_owner_receipt(
            owner_inventory,
            lambda payload: payload.update(
                {
                    "deployment_nonce": "foreign-deployment-nonce",
                    "controller": {
                        "pid": os.getpid() + 1,
                        "start_token": "linux:" + "f" * 64,
                    },
                    "quiescence_inventory_digest": "f" * 64,
                }
            ),
        )
    elif invalid_receipt == "forged-source-digest":
        _rewrite_owner_receipt(
            owner_inventory,
            lambda payload: payload.update({"source_digest": "0" * 64}),
        )
    elif invalid_receipt == "forged-receipt-digest":
        _rewrite_owner_receipt(
            owner_inventory,
            lambda payload: payload.update({"receipt_digest": "invalid"}),
        )
    elif invalid_receipt == "wrong-nonce":
        _rewrite_owner_receipt(
            owner_inventory,
            lambda payload: payload.update({"deployment_nonce": "stale-deployment-nonce"}),
        )
    elif invalid_receipt == "wrong-controller":
        _rewrite_owner_receipt(
            owner_inventory,
            lambda payload: payload.update(
                {
                    "controller": {
                        "pid": os.getpid() + 1,
                        "start_token": "linux:" + "e" * 64,
                    }
                }
            ),
        )
    else:
        _rewrite_owner_receipt(
            owner_inventory,
            lambda payload: payload.update({"quiescence_inventory_digest": "e" * 64}),
        )
    before = _protected_rotation_state(runtime)

    with pytest.raises(InstanceStatePreflightError):
        runtime.rotate_ledger_key(
            quiescence_proof=proof,
            legacy_owner_inventory_path=owner_inventory,
        )

    assert _protected_rotation_state(runtime) == before


@pytest.mark.parametrize(
    "invalid_authority",
    ["stale-proof", "wrong-channel", "missing-fence", "missing-owner", "wrong-root"],
)
def test_key_rotation_rejects_stale_or_mismatched_authority_without_mutation(
    tmp_path, invalid_authority
) -> None:
    runtime = _runtime(tmp_path, "dev", tmp_path / "host-global")
    root = tmp_path / "vault"
    root.mkdir()
    registration = runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    proof, owner_inventory = _rotation_authority(
        runtime,
        [("dev", registration.vault_binding_id, root)],
    )
    if invalid_authority == "stale-proof":
        proof = replace(proof, nonce="stale-deployment-nonce")
    elif invalid_authority == "wrong-channel":
        proof = replace(proof, channel_id="prod")
    elif invalid_authority == "missing-fence":
        _deployment_fence_path(runtime.ledger.root, "dev").unlink()
    elif invalid_authority == "missing-owner":
        payload = json.loads(owner_inventory.read_text(encoding="utf-8"))
        payload["owners"] = []
        payload["source_digest"] = hashlib.sha256(b"[]").hexdigest()
        owner_inventory.write_text(json.dumps(payload), encoding="utf-8")
        os.chmod(owner_inventory, 0o600)
    else:
        other_root = tmp_path / "other-vault"
        other_root.mkdir()
        payload = json.loads(owner_inventory.read_text(encoding="utf-8"))
        payload["owners"][0]["root"] = str(other_root)
        payload["source_digest"] = hashlib.sha256(
            json.dumps(payload["owners"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        owner_inventory.write_text(json.dumps(payload), encoding="utf-8")
        os.chmod(owner_inventory, 0o600)
    key_before = runtime.ledger.key_path.read_bytes()
    ledger_before = runtime.ledger.path.read_bytes()

    with pytest.raises(InstanceStatePreflightError):
        runtime.rotate_ledger_key(
            quiescence_proof=proof,
            legacy_owner_inventory_path=owner_inventory,
        )

    assert runtime.ledger.key_path.read_bytes() == key_before
    assert runtime.ledger.path.read_bytes() == ledger_before


def test_uninitialized_env_upgrade_preserves_read_only_binding_without_writes(tmp_path) -> None:
    runtime = _runtime(tmp_path, "dev", tmp_path / "host-global")
    root = tmp_path / "personal"
    root.mkdir()
    note = root / "note.md"
    note.write_text("unchanged", encoding="utf-8")
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    registration = runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)

    assert registration.vault_id is None
    assert registration.extensions["status"] == "uninitialized"
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before
    with pytest.raises(CapabilityNotReadyError, match="uninitialized"):
        runtime.require_initialized(registration.vault_binding_id)

    initialized = runtime.complete_initialization(
        registration.vault_binding_id,
        vault_id="vault-personal",
        local_instance_id=registration.local_instance_id or "",
    )
    assert initialized.vault_binding_id == registration.vault_binding_id
    assert initialized.vault_id == "vault-personal"


def _authenticated_legacy_identity_fixture(tmp_path, monkeypatch):
    """Reproduce the real materializer's initialized, identity-less registration."""

    root = tmp_path / "owned-source"
    root.mkdir()
    store = MarkdownSettingsStore()
    for filename, frontmatter, body in _initial_settings_files(
        vault_id="vault-retained-source",
        vault_name="Retained source",
        local_instance_id="local-retained-source",
        machine_role="testNode",
    ):
        store.write_frontmatter(root / "settings" / filename, frontmatter, body=body)
    (root / "retained-note.md").write_text("Existing human content\n", encoding="utf-8")
    runtime = _runtime(tmp_path, "test", tmp_path / "host-global")
    identity = resolve_filesystem_root_identity(root)
    ancestors = tuple(f"path:{parent}" for parent in root.resolve().parents)
    owner_row = {
        "channel_id": "test", "vault_binding_id": "binding-retained", "root": str(root),
    }
    source_evidence = {
        "docker": [], "config": [], "owners": [owner_row],
        "owner_identities": [{
            "channel_id": "test", "root": str(root),
            "identity": f"inode:{identity.device}:{identity.inode}",
            "ancestor_identities": sorted(ancestors),
        }],
    }
    receipt = {
        "schema": "agentic-pkm.legacy-owner-inventory.v1",
        "inventory_complete": True, "writers_drained": True,
        "source_probe_count": 2, "validated_after_quiescence": True,
        "source_digest": runtime_module._canonical_json_digest(source_evidence),
        "source_evidence": source_evidence, "owners": [owner_row],
    }
    receipt["receipt_digest"] = runtime_module._legacy_owner_receipt_digest(receipt)
    owner = LegacyOwner(
        "test", "binding-retained", root,
        f"inode:{identity.device}:{identity.inode}", ancestors,
        receipt_digest=receipt["receipt_digest"],
    )
    runtime.ledger.bootstrap_legacy_owners(
        [owner], inventory_complete=True, writers_drained=True,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    receipt_path = runtime.ledger.root / "legacy-owner-inventory.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    receipt_path.chmod(0o600)
    snapshot = runtime_module._materialize_authenticated_channel_registrations(
        channel="test", registry=runtime.registry, ledger=runtime.ledger, owners=(owner,),
    )
    registration = snapshot.registrations["binding-retained"]
    assert registration.vault_id is None and registration.local_instance_id is None
    runtime.registry.set_instance_default(
        registration.vault_binding_id, _capability=STORAGE_MUTATION_CAPABILITY,
    )
    with runtime.registry._locked():
        snapshot = runtime.registry._read_current_locked(recover=True)
        runtime.registry._write_locked(replace(
            snapshot, last_active_vault_ref=registration.ref,
            extensions={**snapshot.extensions, "runtimeFloors": {
                "minimumRuntimeSchema": "mvr05-binding-keyed-v1",
            }},
        ))
    monkeypatch.setenv("VAULT_ROOT", str(root))
    monkeypatch.setenv("VAULT_ROOT_TEST", str(root))
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(root))
    with runtime.first_vault_bootstrap_lock():
        pass
    return runtime, root, registration


def _legacy_identity_preflight(runtime):
    return runtime_module.main([
        "preflight", "--channel", "test",
        "--instance-state-root", str(runtime.layout.root.parent),
        "--host-global-root", str(runtime.ledger.root), "--consumer", "api",
    ])


def _source_and_owner_bytes(runtime, root):
    return {
        **{path: path.read_bytes() for path in root.rglob("*") if path.is_file()},
        **{path: path.read_bytes() for path in runtime.ledger.root.rglob("*") if path.is_file()},
    }


@pytest.mark.parametrize("established", ["neither", "vault", "local", "both"])
def test_authenticated_legacy_identity_completion_preserves_binding_and_authority(
    tmp_path, monkeypatch, established,
) -> None:
    runtime, root, registration = _authenticated_legacy_identity_fixture(tmp_path, monkeypatch)
    registration = replace(
        registration,
        vault_id="vault-retained-source" if established in {"vault", "both"} else None,
        local_instance_id="local-retained-source" if established in {"local", "both"} else None,
    )
    runtime.registry.update_registration(registration, _capability=STORAGE_MUTATION_CAPABILITY)
    before = runtime.registry.load()
    source_before = _source_and_owner_bytes(runtime, root)
    context = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "validator.md")).validate_vault(root)
    assert context.status == "selected"
    assert context.active_vault_id == "vault-retained-source"
    assert context.local_instance_id == "local-retained-source"
    assert _legacy_identity_preflight(runtime) == 0
    expected = replace(registration, vault_id=context.active_vault_id, local_instance_id=context.local_instance_id)
    after = runtime.registry.load()
    assert after == replace(
        before, revision=before.revision + (established != "both"),
        registrations={registration.vault_binding_id: expected},
    )
    assert runtime.require_initialized(registration.vault_binding_id) == expected
    assert _source_and_owner_bytes(runtime, root) == source_before
    state_after = _runtime_state_bytes(tmp_path, runtime)
    assert _legacy_identity_preflight(runtime) == 0
    assert _runtime_state_bytes(tmp_path, runtime) == state_after


@pytest.mark.parametrize("producer", ["remount", "active-existing-root"])
def test_authenticated_legacy_identity_completion_covers_admitted_matching_producers(
    tmp_path, monkeypatch, producer,
) -> None:
    runtime, root, registration = _authenticated_legacy_identity_fixture(tmp_path, monkeypatch)
    if producer == "active-existing-root":
        activate(runtime, registration, tmp_path)
    else:
        original = ownership_module.resolve_filesystem_root_identity

        def remounted(value):
            identity = original(value)
            if Path(value).resolve() == root.resolve():
                return FilesystemRootIdentity(identity.canonical_path, identity.device, identity.inode + 1)
            return identity

        monkeypatch.setattr(ownership_module, "resolve_filesystem_root_identity", remounted)
    before = runtime.registry.load()
    source_before = _source_and_owner_bytes(runtime, root)
    if producer == "remount":
        assert _legacy_identity_preflight(runtime) == 0
    else:
        runtime.production_register(root, producer="api")
    expected = replace(registration, vault_id="vault-retained-source", local_instance_id="local-retained-source")
    after = runtime.registry.load()
    extensions = before.extensions
    if producer == "active-existing-root":
        extensions = {**extensions, "scalarRollback": {
            **extensions["scalarRollback"], "forkRegistryRevision": before.revision + 1,
        }}
    assert after == replace(before, revision=before.revision + 1,
                            registrations={registration.vault_binding_id: expected}, extensions=extensions)
    assert _source_and_owner_bytes(runtime, root) == source_before


@pytest.mark.parametrize("failure", [
    "foreign-owner", "missing-owner", "unproven-root", "vault-conflict", "local-conflict",
    "settings-alias", "identity-alias", "stale-registry", "stale-owner",
])
def test_authenticated_legacy_identity_completion_refuses_conflicts_and_stale_state(
    tmp_path, monkeypatch, failure,
) -> None:
    runtime, root, registration = _authenticated_legacy_identity_fixture(tmp_path, monkeypatch)
    if failure in {"foreign-owner", "missing-owner"}:
        with runtime.ledger._locked():
            key = runtime.ledger._load_or_create_key_locked(allow_create=False)
            ledger = runtime.ledger._load_or_create_ledger_locked(key, allow_create=False)
            leases = {} if failure == "missing-owner" else {
                registration.vault_binding_id: replace(ledger.leases[registration.vault_binding_id], channel_id="dev"),
            }
            runtime.ledger._write_ledger_locked(replace(ledger, leases=leases), key)
    elif failure == "unproven-root":
        root.rename(tmp_path / "retained-source")
        root.mkdir()
    elif failure.endswith("-conflict"):
        registration = replace(registration, **{
            "vault_id" if failure == "vault-conflict" else "local_instance_id": "conflicting-retained-identity",
        })
        runtime.registry.update_registration(registration, _capability=STORAGE_MUTATION_CAPABILITY)
    elif failure == "settings-alias":
        (root / "settings").rename(tmp_path / "foreign-settings")
        (root / "settings").symlink_to(tmp_path / "foreign-settings", target_is_directory=True)
    elif failure == "identity-alias":
        (root / "settings/local.md").rename(tmp_path / "foreign-local.md")
        (root / "settings/local.md").symlink_to(tmp_path / "foreign-local.md")
    elif failure == "stale-owner":
        original = runtime.ledger.recover_or_require_active

        def retire_after_admission(*args, **kwargs):
            lease = original(*args, **kwargs)
            runtime.ledger.release_to_tombstone(registration.vault_binding_id, _capability=STORAGE_MUTATION_CAPABILITY)
            return lease

        monkeypatch.setattr(runtime.ledger, "recover_or_require_active", retire_after_admission)
    before = runtime.registry.load()
    source_before = _source_and_owner_bytes(runtime, root)
    newer = None
    if failure == "stale-registry":
        original_update = runtime.registry.update_registration

        def race_before_update(candidate, **kwargs):
            nonlocal newer
            newer = runtime.registry.set_instance_default(None, _capability=STORAGE_MUTATION_CAPABILITY)
            return original_update(candidate, **kwargs)

        monkeypatch.setattr(runtime.registry, "update_registration", race_before_update)
    with pytest.raises((RegistryError, LedgerError)):
        runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    assert runtime.registry.load() == (newer or before)
    if failure == "stale-registry":
        assert newer is not None
        assert newer.registrations[registration.vault_binding_id] == registration
    if failure != "stale-owner":
        assert _source_and_owner_bytes(runtime, root) == source_before
    else:
        assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == {
            path: content for path, content in source_before.items() if path.is_relative_to(root)
        }
        assert registration.vault_binding_id in runtime.ledger.require_existing().tombstones


@pytest.mark.parametrize("shape", [
    "missing-settings", "missing-vault-id", "missing-local-id",
    "missing-identities-and-schema", "provisional", "ordinary",
])
def test_authenticated_legacy_identity_completion_preserves_uninitialized_compatibility(
    tmp_path, monkeypatch, shape,
) -> None:
    runtime, root, registration = _authenticated_legacy_identity_fixture(tmp_path, monkeypatch)
    if shape == "missing-settings":
        (root / "settings/paths.md").unlink()
    elif shape == "missing-identities-and-schema":
        for filename in ("vault.md", "local.md"):
            MarkdownSettingsStore().write_frontmatter(root / "settings" / filename, {})
    elif shape.startswith("missing-"):
        filename, schema = ("vault.md", "vault") if shape == "missing-vault-id" else ("local.md", "local")
        MarkdownSettingsStore().write_frontmatter(root / "settings" / filename, {"schema": f"design-handoff.{schema}.v1"})
    else:
        registration = replace(registration, local_instance_id="local-provisional", extensions={
            **registration.extensions,
            "status": "uninitialized" if shape == "provisional" else "initialized",
            "provenance": "first_open_existing" if shape == "provisional" else "legacy_env_bootstrap",
        })
        runtime.registry.update_registration(registration, _capability=STORAGE_MUTATION_CAPABILITY)
    before = _runtime_state_bytes(tmp_path, runtime)
    source_before = _source_and_owner_bytes(runtime, root)
    assert _legacy_identity_preflight(runtime) == 0
    assert _runtime_state_bytes(tmp_path, runtime) == before
    assert _source_and_owner_bytes(runtime, root) == source_before
    with pytest.raises(CapabilityNotReadyError, match="uninitialized"):
        runtime.require_initialized(registration.vault_binding_id)


@pytest.mark.parametrize("source_failure", ["parse", "schema", "identity-type"])
def test_authenticated_legacy_identity_completion_is_value_free_and_metadata_only(
    tmp_path, monkeypatch, source_failure,
) -> None:
    runtime, root, registration = _authenticated_legacy_identity_fixture(tmp_path, monkeypatch)
    identity_read = runtime_module._read_vault_identity

    def assert_ownership_lock():
        with runtime.ledger.lock_path.open("a+b") as handle:
            with pytest.raises(BlockingIOError):
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def locked_read(path):
        assert_ownership_lock()
        return identity_read(path)

    monkeypatch.setattr(runtime_module, "_read_vault_identity", locked_read)
    original_update = runtime.registry.update_registration

    def locked_commit(candidate, **kwargs):
        assert_ownership_lock()
        return original_update(candidate, **kwargs)

    monkeypatch.setattr(runtime.registry, "update_registration", locked_commit)
    source_before = _source_and_owner_bytes(runtime, root)
    runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    assert runtime.registry.lookup(registration.vault_binding_id).vault_id == "vault-retained-source"
    assert _source_and_owner_bytes(runtime, root) == source_before
    # Another eligible placeholder is prepared entirely in fixtures to exercise refusal.
    with runtime.registry._locked():
        snapshot = runtime.registry._read_current_locked(recover=True)
        runtime.registry._write_locked(replace(snapshot, registrations={registration.vault_binding_id: registration}))
    marker = "PROTECTED_FIXTURE_PARSE_VALUE"
    if source_failure == "parse":
        (root / "settings/vault.md").write_text(f"---\nvaultId: [{marker}\n---\n", encoding="utf-8")
    else:
        MarkdownSettingsStore().write_frontmatter(root / "settings/vault.md", {
            "schema": marker if source_failure == "schema" else "design-handoff.vault.v1",
            "vaultId": {marker: True} if source_failure == "identity-type" else "vault-retained-source",
        })
    before = _runtime_state_bytes(tmp_path, runtime)
    source_before = _source_and_owner_bytes(runtime, root)
    with pytest.raises(RegistryError) as exc:
        runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    output = "".join(traceback.format_exception(exc.type, exc.value, exc.tb))
    assert marker not in output and str(root) not in output
    assert "vault-retained-source" not in str(exc.value)
    assert _runtime_state_bytes(tmp_path, runtime) == before
    assert _source_and_owner_bytes(runtime, root) == source_before
