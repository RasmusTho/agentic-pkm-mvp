from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.instance.instance_state import InstanceStateLayout
from app.instance.ownership_ledger import (
    LedgerCollisionError,
    LedgerKeyError,
    LegacyOwner,
    OwnershipLedger,
)
from app.instance.runtime import (
    InstanceRegistryRuntime,
    LifecycleActivationProof,
    TransferActivationProof,
)
from app.instance.vault_registry import CapabilityNotReadyError, RegistryError
from app.vault.manager import iter_vault_markdown_files


def _runtime(tmp_path: Path, channel: str, host_global: Path) -> InstanceRegistryRuntime:
    return InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / channel, channel),
        host_global,
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
    runtime.prepare_nested_registration(child)

    assert [path.name for path in iter_vault_markdown_files(parent)] == ["parent.md"]
    assert [path.name for path in iter_vault_markdown_files(child)] == ["secret.md"]
    assert len(runtime.registry.load().registrations) == 2
    with pytest.raises(RegistryError):
        runtime.prepare_nested_registration(child.resolve())


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
    proof = TransferActivationProof.for_test_activation()

    with pytest.raises(RuntimeError, match="injected crash"):
        source.transfer_to(destination, registration.vault_binding_id, proof=proof, crash_after="destination_commit")
    third_channel = _runtime(tmp_path, "prod", host_global)
    with pytest.raises(LedgerCollisionError):
        third_channel.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    destination_binding = source.recover_transfer(destination)

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
    source.rotate_ledger_key()
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
    result = source.transfer_to(
        destination,
        original.vault_binding_id,
        proof=TransferActivationProof.for_test_activation(),
    )
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


def test_removed_binding_reregistration_preserves_tombstone_lineage(tmp_path) -> None:
    runtime = _runtime(tmp_path, "dev", tmp_path / "host-global")
    root = tmp_path / "vault"
    root.mkdir()
    registration = runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    proof = LifecycleActivationProof.for_test_activation()
    runtime.remove(registration.vault_binding_id, proof=proof)

    reactivated = runtime.reactivate_removed(root, proof=proof)
    assert reactivated.vault_binding_id == registration.vault_binding_id
    assert reactivated.local_instance_id == registration.local_instance_id
    assert reactivated.extensions["contentEpoch"] == 2
    assert runtime.registry.load().removal_tombstones[registration.vault_binding_id].content_epoch == 1


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
    )
    assert {lease.channel_id for lease in seeded.leases.values()} == {"dev", "prod"}

    missing = OwnershipLedger(tmp_path / "missing-host-global")
    with pytest.raises(LedgerCollisionError, match="complete"):
        missing.bootstrap_legacy_owners([], inventory_complete=False, writers_drained=True)


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

    with pytest.raises(RuntimeError, match="injected crash"):
        runtime.rotate_ledger_key(crash_after="key_commit")
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
    proof = LifecycleActivationProof.for_test_activation()
    runtime.remove(registration.vault_binding_id, proof=proof)
    runtime.rotate_ledger_key()

    reactivated = runtime.reactivate_removed(root, proof=proof)
    assert reactivated.vault_binding_id == registration.vault_binding_id


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
