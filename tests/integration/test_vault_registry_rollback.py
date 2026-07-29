from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from app.instance.instance_state import InstanceStateLayout
from app.instance.runtime import (
    InstanceRegistryRuntime,
    _begin_instance_state_deployment,
    _bind_legacy_owner_inventory_to_proof,
    _finish_instance_state_deployment,
    _preflight_scalar_rollback,
    _prove_instance_state_quiescence,
    _roll_forward_scalar_rollback,
)
from app.instance.scalar_rollback_guard import preflight_scalar_rollback_guard
from app.instance.vault_registry import (
    AppLocalSettingsStore,
    CapabilityNotReadyError,
    KnownVaultRef,
    RegistryError,
)
from app.vault.manager import VaultManager


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_second_registration_is_sealed_across_all_producers_until_01c(tmp_path) -> None:
    runtime = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / "instance-state", "dev"),
        tmp_path / "host-global",
    )
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()
    runtime.bootstrap_env_binding(vault_root=first, watcher_vault_path=first)

    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for root in (runtime.layout.root, runtime.ledger.root)
        for path in root.rglob("*")
        if path.is_file()
    }

    for producer in ("picker", "api", "cli", "import", "bootstrap", "direct-service"):
        with pytest.raises(CapabilityNotReadyError, match="MVR-01C authority cutover"):
            runtime.production_register(second, producer=producer)
        assert {
            path.relative_to(tmp_path): path.read_bytes()
            for root in (runtime.layout.root, runtime.ledger.root)
            for path in root.rglob("*")
            if path.is_file()
        } == before

    with pytest.raises(CapabilityNotReadyError, match="MVR-01C authority cutover"):
        runtime.bootstrap_env_binding(vault_root=second, watcher_vault_path=second)
    with pytest.raises(CapabilityNotReadyError, match="MVR-01C authority cutover"):
        runtime._bootstrap_env_binding_locked(
            vault_root=second,
            watcher_vault_path=second,
        )
    with pytest.raises(CapabilityNotReadyError, match="MVR-01C authority cutover"):
        runtime.prepare_nested_registration(second)

    assert len(runtime.registry.load().registrations) == 1
    assert len(runtime.ledger.load().leases) == 1
    assert {
        path.relative_to(tmp_path): path.read_bytes()
        for root in (runtime.layout.root, runtime.ledger.root)
        for path in root.rglob("*")
        if path.is_file()
    } == before


def test_01b_keeps_registry_cutover_dormant_until_01c(tmp_path) -> None:
    layout = InstanceStateLayout.for_channel(tmp_path / "instance-state", "prod")
    runtime = InstanceRegistryRuntime.for_paths(layout, tmp_path / "host-global")
    root = tmp_path / "vault"
    root.mkdir()
    prepared = runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)

    legacy_path = tmp_path / "legacy" / "app-local.md"
    legacy = AppLocalSettingsStore(legacy_path)
    legacy.upsert_known_vault(KnownVaultRef("legacy", str(root)))
    runtime.prepare_previous_scalar_image(legacy_path)
    transformed_path = tmp_path / "previous-image" / "app-local.md"
    transformed = runtime.registry.materialize_legacy_rollback(transformed_path)

    assert runtime.registry.load().authority == "dormant"
    assert runtime.production_read().last_active_vault_ref == legacy.load().last_active_vault_ref
    assert AppLocalSettingsStore(legacy_path).load().known_vaults
    assert prepared.vault_binding_id not in AppLocalSettingsStore(legacy_path).load().known_vaults
    assert transformed.known_vaults[prepared.ref].path == prepared.path
    with pytest.raises(CapabilityNotReadyError, match="MVR-01C authority cutover"):
        runtime.production_register(tmp_path / "other", producer="direct-service")


def _active_runtime(tmp_path):
    runtime = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / "instance-state", "prod"),
        tmp_path / "host-global",
    )
    root = tmp_path / "one"
    root.mkdir()
    first = runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    proof, inventory, _ = _deployment_authority(
        runtime,
        tmp_path / "missing-legacy.md",
    )
    runtime.activate_authority(
        guard_receipt=_guard_receipt(first.vault_binding_id, root),
        inventory_path=inventory,
        quiescence_proof=proof,
    )
    _finish_instance_state_deployment(
        channel=runtime.layout.channel_id,
        instance_state_root=runtime.layout.root.parent,
        host_global_root=runtime.ledger.root,
        legacy_path=tmp_path / "missing-legacy.md",
        inventory_path=inventory,
        backup_root=tmp_path / "authority-backup",
        restore_root=None,
        quiescence_proof=proof,
    )
    return runtime, first


def _guard_receipt(binding_id, root):
    return preflight_scalar_rollback_guard(
        compose_overlay=REPO_ROOT / "docker-compose.scalar-rollback.yml",
        gateway_config=REPO_ROOT / "ops/scalar-rollback/nginx.conf",
        native_launcher=REPO_ROOT / "scripts/scalar_rollback_native.sh",
        rollback_vault_binding_id=binding_id,
        selected_root=root,
    )


def _start_scalar_runtime(runtime, registration, root, rollback_path) -> None:
    _preflight_scalar_rollback(
        channel=runtime.layout.channel_id,
        registry_path=runtime.layout.registry_path,
        host_global_root=runtime.ledger.root,
        rollback_vault_binding_id=registration.vault_binding_id,
        legacy_path=rollback_path,
        selected_root=root,
        compose_base=REPO_ROOT / "docker-compose.yaml",
        compose_overlay=REPO_ROOT / "docker-compose.scalar-rollback.yml",
        gateway_config=REPO_ROOT / "ops/scalar-rollback/nginx.conf",
        native_launcher=REPO_ROOT / "scripts/scalar_rollback_native.sh",
    )


def _deployment_authority(runtime, legacy_path):
    controller = {
        "pid": os.getpid(),
        "start_token": "linux:" + "0" * 64,
    }
    _begin_instance_state_deployment(
        channel=runtime.layout.channel_id,
        instance_state_root=runtime.layout.root.parent,
        host_global_root=runtime.ledger.root,
        legacy_path=legacy_path,
        controller_pid=controller["pid"],
        controller_start_token=controller["start_token"],
    )
    empty_domains = {
        domain: [] for domain in ("dev", "native", "prod", "test")
    }
    empty_digest = hashlib.sha256(
        json.dumps(
            empty_domains,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    quiescence_inventory = (
        runtime.ledger.root / "deployment-quiescence-inventory.json"
    )
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
    quiescence_inventory.chmod(0o600)
    proof = _prove_instance_state_quiescence(
        channel=runtime.layout.channel_id,
        host_global_root=runtime.ledger.root,
        inventory_path=quiescence_inventory,
    )
    owners = [
        {
            "channel_id": lease.channel_id,
            "vault_binding_id": binding_id,
            "root": runtime.registry.load().registrations[binding_id].path,
        }
        for binding_id, lease in runtime.ledger.load().leases.items()
    ]
    owner_identities = []
    for owner in owners:
        metadata = os.stat(owner["root"])
        owner_identities.append(
            {
                "channel_id": owner["channel_id"],
                "root": owner["root"],
                "identity": f"inode:{metadata.st_dev}:{metadata.st_ino}",
            }
        )
    source_evidence = {
        "docker": [],
        "config": [],
        "owners": owners,
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
                        source_evidence,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
                "source_evidence": source_evidence,
                "owners": owners,
            }
        ),
        encoding="utf-8",
    )
    owner_inventory.chmod(0o600)
    bound = _bind_legacy_owner_inventory_to_proof(
        inventory_path=owner_inventory,
        quiescence_proof=proof,
        channel=runtime.layout.channel_id,
        host_global_root=runtime.ledger.root,
    )
    return (
        bound,
        owner_inventory,
        runtime.ledger.root / "deployment-quiescence-proof.json",
    )


def test_previous_image_reads_latest_post_migration_registry_state(tmp_path) -> None:
    runtime, first = _active_runtime(tmp_path)
    rollback_path = tmp_path / "previous-image" / "app-local.md"

    _start_scalar_runtime(
        runtime,
        first,
        Path(first.path),
        rollback_path,
    )
    projected = AppLocalSettingsStore(rollback_path).load()

    assert set(projected.known_vaults) == {first.ref}
    assert projected.last_active_vault_ref == first.ref
    runtime.merge_previous_scalar_image(rollback_path)
    runtime.registry.rollback_export_path.write_text("stale", encoding="utf-8")
    with pytest.raises(RegistryError, match="missing or stale"):
        _start_scalar_runtime(
            runtime,
            first,
            Path(first.path),
            rollback_path,
        )


def test_multi_binding_rollback_requires_one_safe_explicit_target(tmp_path) -> None:
    runtime, first = _active_runtime(tmp_path)
    second_root = tmp_path / "two"
    second_root.mkdir()
    second = runtime.production_register(second_root, producer="api")
    before = runtime.layout.registry_path.read_bytes()
    rollback_path = tmp_path / "rollback" / "app-local.md"

    with pytest.raises(RegistryError, match="does not match"):
        runtime.registry.materialize_legacy_rollback(
            rollback_path,
            rollback_vault_binding_id=second.vault_binding_id,
        )
    projected = runtime.registry.materialize_legacy_rollback(
        rollback_path,
        rollback_vault_binding_id=first.vault_binding_id,
    )

    assert set(projected.known_vaults) == {first.ref}
    assert runtime.layout.registry_path.read_bytes() == before
    assert set(runtime.registry.load().registrations) == {
        first.vault_binding_id,
        second.vault_binding_id,
    }


def test_01c_unseals_second_registration_only_with_complete_rollback_floor(
    tmp_path,
    monkeypatch,
) -> None:
    runtime = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / "instance-state", "prod"),
        tmp_path / "host-global",
    )
    first_root = tmp_path / "one"
    first_root.mkdir()
    first = runtime.bootstrap_env_binding(vault_root=first_root, watcher_vault_path=first_root)
    before = runtime.layout.registry_path.read_bytes()
    proof, inventory, _ = _deployment_authority(
        runtime,
        tmp_path / "missing-legacy.md",
    )

    with pytest.raises(RegistryError, match="injected partial"):
        runtime.activate_authority(
            guard_receipt=_guard_receipt(first.vault_binding_id, first_root),
            inventory_path=inventory,
            quiescence_proof=proof,
            inject_failure_before_commit=True,
        )
    assert runtime.layout.registry_path.read_bytes() == before
    with pytest.raises(CapabilityNotReadyError, match="authority cutover"):
        runtime.production_register(tmp_path / "sealed", producer="picker")

    runtime.activate_authority(
        guard_receipt=_guard_receipt(first.vault_binding_id, first_root),
        inventory_path=inventory,
        quiescence_proof=proof,
    )
    for producer in ("picker", "api", "cli", "import", "bootstrap", "direct-service"):
        root = tmp_path / producer
        root.mkdir()
        assert runtime.production_register(root, producer=producer).path == str(root)

    picker_root = tmp_path / "actual-picker"
    picker_root.mkdir()
    monkeypatch.setenv(
        "INSTANCE_VAULT_REGISTRY_PATH",
        str(runtime.layout.registry_path),
    )
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", "prod")
    context = VaultManager().select_vault(picker_root)
    assert context.status == "uninitialized"
    active = runtime.registry.load()
    assert active.last_active_vault_ref == f"path:{picker_root}"
    assert any(item.path == str(picker_root) for item in active.registrations.values())
    assert (
        AppLocalSettingsStore().load().last_active_vault_ref
        == f"path:{picker_root}"
    )

    nested = first_root / "nested"
    nested.mkdir()
    nested_context = VaultManager().select_vault(nested)
    assert nested_context.status == "uninitialized"
    assert any(
        item.path == str(nested)
        for item in runtime.registry.load().registrations.values()
    )


def test_production_registration_retries_reserve_only_crash(
    tmp_path,
    monkeypatch,
) -> None:
    runtime, _ = _active_runtime(tmp_path)
    root = tmp_path / "reserve-crash"
    root.mkdir()
    original_register = runtime.registry.register

    def fail_after_reserve(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("injected crash after ownership reserve")

    monkeypatch.setattr(runtime.registry, "register", fail_after_reserve)
    with pytest.raises(RuntimeError, match="after ownership reserve"):
        runtime.production_register(root, producer="picker")
    pending = [
        lease
        for lease in runtime.ledger.load().leases.values()
        if lease.state == "pending"
    ]
    assert len(pending) == 1

    monkeypatch.setattr(runtime.registry, "register", original_register)
    registered = runtime.production_register(root, producer="picker")
    assert registered.vault_binding_id == pending[0].vault_binding_id
    assert runtime.ledger.active_owner(registered.vault_binding_id) is not None


def test_production_registration_retries_registry_commit_crash(
    tmp_path,
    monkeypatch,
) -> None:
    runtime, _ = _active_runtime(tmp_path)
    root = tmp_path / "registry-commit-crash"
    root.mkdir()
    original_activate = runtime.ledger.activate

    def fail_after_registry_commit(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("injected crash after registry commit")

    monkeypatch.setattr(runtime.ledger, "activate", fail_after_registry_commit)
    with pytest.raises(RuntimeError, match="after registry commit"):
        runtime.production_register(root, producer="picker")
    committed = next(
        registration
        for registration in runtime.registry.load().registrations.values()
        if registration.path == str(root)
    )
    assert runtime.ledger.load().leases[committed.vault_binding_id].state == "pending"

    monkeypatch.setattr(runtime.ledger, "activate", original_activate)
    retried = runtime.production_register(root, producer="picker")
    assert retried == committed
    assert runtime.ledger.active_owner(committed.vault_binding_id) is not None


def test_rollback_mutations_round_trip_on_roll_forward(tmp_path) -> None:
    runtime, first = _active_runtime(tmp_path)
    rollback_path = tmp_path / "rollback" / "app-local.md"
    _start_scalar_runtime(
        runtime,
        first,
        Path(first.path),
        rollback_path,
    )
    rollback = AppLocalSettingsStore(rollback_path)
    settings = rollback.load()
    selected = settings.known_vaults[first.ref]
    settings.known_vaults[first.ref] = KnownVaultRef(
        ref=selected.ref,
        path=selected.path,
        vault_id=selected.vault_id,
        vault_name="Renamed during rollback",
        local_instance_id=selected.local_instance_id,
        last_opened_at="2026-07-29T00:00:00Z",
    )
    rollback.save(settings)

    proof, owner_inventory, proof_path = _deployment_authority(
        runtime,
        rollback_path,
    )
    assert (
        _roll_forward_scalar_rollback(
            channel=runtime.layout.channel_id,
            instance_state_root=runtime.layout.root.parent,
            host_global_root=runtime.ledger.root,
            legacy_path=rollback_path,
            inventory_path=owner_inventory,
            quiescence_proof_path=proof_path,
        )
        == 0
    )
    merged = runtime.registry.load()

    assert merged.registrations[first.vault_binding_id].vault_name == "Renamed during rollback"
    assert merged.extensions["scalarRollForwardLineage"][-1]["mergedRegistryRevision"] == merged.revision
    deployment = (
        REPO_ROOT / "scripts/lib/instance_state_deployment.sh"
    ).read_text(encoding="utf-8")
    assert "scalar-rollback-roll-forward" in deployment
    assert "MVR01C_ROLL_FORWARD_LEGACY_PATH" in deployment
    _finish_instance_state_deployment(
        channel=runtime.layout.channel_id,
        instance_state_root=runtime.layout.root.parent,
        host_global_root=runtime.ledger.root,
        legacy_path=rollback_path,
        inventory_path=owner_inventory,
        backup_root=tmp_path / "backup",
        restore_root=None,
        quiescence_proof=proof,
    )

    divergent = tmp_path / "rollback-divergent" / "app-local.md"
    _start_scalar_runtime(
        runtime,
        first,
        Path(first.path),
        divergent,
    )
    divergent_store = AppLocalSettingsStore(divergent)
    divergent_settings = divergent_store.load()
    divergent_settings.known_vaults["path:/outside"] = KnownVaultRef(
        ref="path:/outside",
        path="/outside",
    )
    divergent_store.save(divergent_settings)
    before = runtime.layout.registry_path.read_bytes()
    with pytest.raises(RegistryError, match="escaped the selected binding"):
        runtime.merge_previous_scalar_image(divergent)
    assert runtime.layout.registry_path.read_bytes() == before


def test_roll_forward_recovers_crash_after_registry_generation_write(
    tmp_path,
    monkeypatch,
) -> None:
    runtime, registration = _active_runtime(tmp_path)
    rollback_path = tmp_path / "rollback-crash" / "app-local.md"
    _start_scalar_runtime(
        runtime,
        registration,
        Path(registration.path),
        rollback_path,
    )
    before = runtime.registry.load()
    original_apply = runtime.registry._apply_generation
    crashed = False

    def crash_after_generation(generation, *, use_raw_writer=False):
        nonlocal crashed
        original_apply(generation, use_raw_writer=use_raw_writer)
        if (
            not crashed
            and generation[runtime.registry.scalar_rollback_session_path] is None
        ):
            crashed = True
            raise SystemExit("injected crash after scalar merge generation")

    monkeypatch.setattr(runtime.registry, "_apply_generation", crash_after_generation)
    with pytest.raises(SystemExit, match="injected crash"):
        runtime.merge_previous_scalar_image(rollback_path)
    monkeypatch.setattr(runtime.registry, "_apply_generation", original_apply)

    recovered = runtime.registry.load()
    assert recovered.revision == before.revision
    assert runtime.registry.scalar_rollback_session_path.is_file()

    merged = runtime.merge_previous_scalar_image(rollback_path)
    assert merged.revision == before.revision + 1
    assert not runtime.registry.scalar_rollback_session_path.exists()


def test_roll_forward_recovers_committed_journal_before_cleanup(
    tmp_path,
    monkeypatch,
) -> None:
    runtime, registration = _active_runtime(tmp_path)
    rollback_path = tmp_path / "rollback-committed" / "app-local.md"
    _start_scalar_runtime(
        runtime,
        registration,
        Path(registration.path),
        rollback_path,
    )
    before = runtime.registry.load()
    original_clear = runtime.registry._clear_transaction_journal
    calls = 0

    def fail_first_cleanup():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected crash before committed journal cleanup")
        original_clear()

    monkeypatch.setattr(
        runtime.registry,
        "_clear_transaction_journal",
        fail_first_cleanup,
    )
    merged = runtime.merge_previous_scalar_image(rollback_path)
    assert merged.revision == before.revision + 1
    assert runtime.registry.transaction_path.is_file()
    assert not runtime.registry.scalar_rollback_session_path.exists()

    recovered = runtime.registry.load()
    assert recovered.revision == merged.revision
    assert not runtime.registry.transaction_path.exists()
    assert not runtime.registry.scalar_rollback_session_path.exists()
