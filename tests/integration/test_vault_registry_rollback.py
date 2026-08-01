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

    # The scalar guard intentionally mounts only the selected root. Lease
    # coverage for every other registration must remain provable from the
    # authenticated ledger without opening its sealed host path.
    second_root.rename(tmp_path / "two-sealed")
    selected_alias = tmp_path / "selected-container-alias"
    selected_alias.symlink_to(Path(first.path), target_is_directory=True)
    _start_scalar_runtime(
        runtime,
        first,
        selected_alias,
        rollback_path,
    )
    assert set(AppLocalSettingsStore(rollback_path).load().known_vaults) == {
        first.ref
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
    settings.last_active_vault_ref = None
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
    assert merged.last_active_vault_ref is None
    assert merged.extensions["scalarRollForwardLineage"][-1]["mergedRegistryRevision"] == merged.revision
    deployment = (
        REPO_ROOT / "scripts/lib/instance_state_deployment.sh"
    ).read_text(encoding="utf-8")
    assert "scalar-rollback-roll-forward" in deployment
    assert "MVR01C_ROLL_FORWARD_LEGACY_PATH" in deployment
    assert "--scalar-roll-forward-merged" not in deployment
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


def test_mvr02_default_survives_scalar_projection_round_trip(tmp_path) -> None:
    """MVR-02 (#3856): the explicit default is new-schema-only lineage.

    Contract: docs/MULTI_VAULT_RUNTIME/RESOLVE_INSTANCE_DEFAULT_VAULT.md.
    The scalar previous image sees only the already validated explicit rollback
    target and never an inferred default; roll-forward restores the authoritative
    ``default_vault_binding_id`` from the new-schema lineage and still rejects a
    divergent or ambiguous scalar mutation.
    """

    from app.instance.default_vault import InstanceDefaultVaultService
    from app.instance.vault_registry import (
        DEFAULT_PROVENANCE_EXPLICIT,
        _split_rendered,
    )

    runtime, first = _active_runtime(tmp_path)
    second_root = tmp_path / "second"
    second_root.mkdir()
    second = runtime.production_register(second_root, producer="api")
    from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY

    service = InstanceDefaultVaultService(
        runtime.registry,
        capability=_STORAGE_MUTATION_CAPABILITY,
        emit_event=lambda receipt: "",
    )
    service.set(second.vault_binding_id)
    before = runtime.registry.load()
    assert before.default_vault_binding_id == second.vault_binding_id

    rollback_path = tmp_path / "rollback" / "app-local.md"
    _start_scalar_runtime(runtime, first, Path(first.path), rollback_path)

    # The scalar projection carries the validated rollback target only. It never
    # gains a default field, and the default is never converted into last-active.
    projected_frontmatter, _ = _split_rendered(
        rollback_path.read_text(encoding="utf-8"), rollback_path
    )
    assert "defaultVaultBindingId" not in projected_frontmatter
    assert "defaultVaultProvenance" not in projected_frontmatter
    assert projected_frontmatter["lastActiveVaultRef"] == first.ref
    assert set(projected_frontmatter["knownVaults"]) == {first.ref}
    assert projected_frontmatter["mvrRollbackBindingId"] == first.vault_binding_id
    # The authoritative registry is untouched by projection.
    assert runtime.registry.load().default_vault_binding_id == second.vault_binding_id

    # The previous image mutates only what it can see.
    rollback = AppLocalSettingsStore(rollback_path)
    settings = rollback.load()
    selected = settings.known_vaults[first.ref]
    settings.known_vaults[first.ref] = KnownVaultRef(
        ref=selected.ref,
        path=selected.path,
        vault_id=selected.vault_id,
        vault_name="Renamed on the previous image",
        local_instance_id=selected.local_instance_id,
        last_opened_at="2026-07-31T00:00:00Z",
    )
    rollback.save(settings)

    proof, owner_inventory, proof_path = _deployment_authority(runtime, rollback_path)
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

    # Roll-forward verified the default's binding still exists and restored it
    # unchanged, rather than inferring one from the returning last-active value.
    assert merged.default_vault_binding_id == second.vault_binding_id
    assert merged.default_vault_provenance == DEFAULT_PROVENANCE_EXPLICIT
    assert merged.registrations[first.vault_binding_id].vault_name == (
        "Renamed on the previous image"
    )
    assert merged.last_active_vault_ref == first.ref
    assert merged.last_active_vault_ref != second.ref
    _finish_instance_state_deployment(
        channel=runtime.layout.channel_id,
        instance_state_root=runtime.layout.root.parent,
        host_global_root=runtime.ledger.root,
        legacy_path=rollback_path,
        inventory_path=owner_inventory,
        backup_root=tmp_path / "mvr02-backup",
        restore_root=None,
        quiescence_proof=proof,
    )

    # A divergent scalar mutation is still rejected, and the default is unchanged.
    divergent = tmp_path / "rollback-divergent" / "app-local.md"
    _start_scalar_runtime(runtime, first, Path(first.path), divergent)
    divergent_store = AppLocalSettingsStore(divergent)
    divergent_settings = divergent_store.load()
    divergent_settings.known_vaults["path:/outside"] = KnownVaultRef(
        ref="path:/outside", path="/outside"
    )
    divergent_store.save(divergent_settings)
    payload_before = runtime.layout.registry_path.read_bytes()
    with pytest.raises(RegistryError, match="escaped the selected binding"):
        runtime.merge_previous_scalar_image(divergent)
    assert runtime.layout.registry_path.read_bytes() == payload_before
    assert runtime.registry.load().default_vault_binding_id == second.vault_binding_id


def _mvr04_dimension_service(runtime):
    """The MVR-04 production dimension producer over this runtime's registry."""

    from app.instance.runtime import open_vault_dimension_service

    return open_vault_dimension_service(runtime.layout.registry_path)


def test_mvr04_dimensions_survive_principal_capable_rollback_round_trip(tmp_path) -> None:
    """MVR-04 (#3858): dimensions are unknown state to a pre-MVR-04 image, and survive.

    Contract: docs/MULTI_VAULT_RUNTIME/GROUP_VAULT_BINDINGS_BY_DIMENSION.md.

    The old image here is MVR-03-capable but pre-MVR-04: it never learned the dimension
    schema. Two things therefore have to hold. Its scalar projection must *omit* dimensions
    entirely rather than flattening or guessing them, and any registry mutation it can
    still execute at that runtime floor -- an explicit instance-default change, which
    MVR-02 shipped -- must carry the complete dimension state through untouched, including
    member order.

    It deliberately does not pretend the still-dormant registration-removal command can
    run: that stays `capability_not_ready` until MVR-06B, and this test asserts that rather
    than routing around it.
    """

    from app.instance.default_vault import InstanceDefaultVaultService
    from app.instance.vault_dimensions import parse_dimensions
    from app.instance.vault_registry import _split_rendered
    from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY

    runtime, first = _active_runtime(tmp_path)
    second_root = tmp_path / "second"
    second_root.mkdir()
    second = runtime.production_register(second_root, producer="api")
    third_root = tmp_path / "third"
    third_root.mkdir()
    third = runtime.production_register(third_root, producer="api")

    # Ordered, deliberately non-alphabetical membership across two dimensions.
    dimensions = _mvr04_dimension_service(runtime)
    dimensions.create(
        "work",
        display_name="Work",
        members=[third.vault_binding_id, first.vault_binding_id],
    )
    dimensions.create("reading", display_name="Reading", members=[second.vault_binding_id])
    before = parse_dimensions(runtime.registry.load().extensions)
    assert before["work"].members == (third.vault_binding_id, first.vault_binding_id)

    # -- a mutation the pre-MVR-04 runtime floor *can* execute ------------------------
    # An MVR-03-capable image knows `set_instance_default` (MVR-02) and knows nothing about
    # dimensions. It rewrites the whole registry document, so this is the real test of
    # unknown-field preservation at that floor.
    service = InstanceDefaultVaultService(
        runtime.registry,
        capability=_STORAGE_MUTATION_CAPABILITY,
        emit_event=lambda receipt: "",
    )
    service.set(second.vault_binding_id)
    after_default = runtime.registry.load()
    assert after_default.default_vault_binding_id == second.vault_binding_id
    # Every dimension, every display name, every revision, and every member order intact.
    assert parse_dimensions(after_default.extensions) == before
    registrations_before = dict(after_default.registrations)

    # -- the scalar projection a pre-MVR-04 image reads carries no dimensions ----------
    rollback_path = tmp_path / "rollback" / "app-local.md"
    _start_scalar_runtime(runtime, first, Path(first.path), rollback_path)
    projected, _ = _split_rendered(
        rollback_path.read_text(encoding="utf-8"), rollback_path
    )
    assert "dimensions" not in projected
    assert "vaultDimensions" not in projected
    assert set(projected["knownVaults"]) == {first.ref}
    assert "work" not in rollback_path.read_text(encoding="utf-8")
    # The authoritative registry is untouched by projection: the complete dimension state
    # stays immutable while the old image is live.
    assert parse_dimensions(runtime.registry.load().extensions) == before

    # -- and comes back exactly on roll-forward ---------------------------------------
    # The old image changed nothing it could see, so every registration must restore
    # exactly and every dimension with it.
    proof, owner_inventory, proof_path = _deployment_authority(runtime, rollback_path)
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
    assert parse_dimensions(merged.extensions) == before
    assert merged.registrations == registrations_before
    assert merged.default_vault_binding_id == second.vault_binding_id
    _finish_instance_state_deployment(
        channel=runtime.layout.channel_id,
        instance_state_root=runtime.layout.root.parent,
        host_global_root=runtime.ledger.root,
        legacy_path=rollback_path,
        inventory_path=owner_inventory,
        backup_root=tmp_path / "mvr04-roundtrip-backup",
        restore_root=None,
        quiescence_proof=proof,
    )

    # -- registration removal is still dormant; this test does not pretend otherwise ---
    frozen = runtime.layout.registry_path.read_bytes()
    with pytest.raises(CapabilityNotReadyError):
        runtime.registry.remove_registration(third.vault_binding_id)
    assert runtime.layout.registry_path.read_bytes() == frozen


def test_mvr04_rollforward_preserves_dimensions_across_default_mutation(tmp_path) -> None:
    """MVR-04 (#3858): roll-forward keeps the complete unknown dimension set.

    Contract: docs/MULTI_VAULT_RUNTIME/GROUP_VAULT_BINDINGS_BY_DIMENSION.md.

    The previous image mutates only what it can see, then the new image rolls forward. The
    merge reconciles the default through the normal MVR-02 lineage and must carry the whole
    dimension set across unchanged -- inventing no removal and pruning no member, including
    members of dimensions the mutation never touched.
    """

    from app.instance.default_vault import InstanceDefaultVaultService
    from app.instance.vault_dimensions import parse_dimensions
    from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY

    runtime, first = _active_runtime(tmp_path)
    second_root = tmp_path / "second"
    second_root.mkdir()
    second = runtime.production_register(second_root, producer="api")
    third_root = tmp_path / "third"
    third_root.mkdir()
    third = runtime.production_register(third_root, producer="api")

    dimensions = _mvr04_dimension_service(runtime)
    dimensions.create(
        "work",
        display_name="Work",
        members=[third.vault_binding_id, first.vault_binding_id, second.vault_binding_id],
    )
    dimensions.create("untouched", display_name="Untouched", members=[second.vault_binding_id])

    # The new-schema explicit default the scalar image never sees.
    InstanceDefaultVaultService(
        runtime.registry,
        capability=_STORAGE_MUTATION_CAPABILITY,
        emit_event=lambda receipt: "",
    ).set(second.vault_binding_id)
    before = parse_dimensions(runtime.registry.load().extensions)

    rollback_path = tmp_path / "rollback" / "app-local.md"
    _start_scalar_runtime(runtime, first, Path(first.path), rollback_path)

    # The previous image mutates the one binding it can see.
    rollback = AppLocalSettingsStore(rollback_path)
    settings = rollback.load()
    selected = settings.known_vaults[first.ref]
    settings.known_vaults[first.ref] = KnownVaultRef(
        ref=selected.ref,
        path=selected.path,
        vault_id=selected.vault_id,
        vault_name="Renamed on the pre-MVR-04 image",
        local_instance_id=selected.local_instance_id,
        last_opened_at="2026-08-01T00:00:00Z",
    )
    rollback.save(settings)

    proof, owner_inventory, proof_path = _deployment_authority(runtime, rollback_path)
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

    # The default is reconciled through the normal MVR-02 lineage -- restored from the
    # new-schema value with its provenance intact, not inferred from the returning
    # last-active projection. These are the assertions the sibling MVR-02 test makes, kept
    # here so MVR-04 cannot quietly weaken the lineage it claims to reconcile through.
    from app.instance.vault_registry import DEFAULT_PROVENANCE_EXPLICIT

    assert merged.default_vault_binding_id == second.vault_binding_id
    assert merged.default_vault_provenance == DEFAULT_PROVENANCE_EXPLICIT
    assert merged.last_active_vault_ref == first.ref
    assert merged.last_active_vault_ref != second.ref
    assert merged.registrations[first.vault_binding_id].vault_name == (
        "Renamed on the pre-MVR-04 image"
    )

    # The complete dimension set survives, with ordered membership intact. No removal was
    # invented for a binding the old image never mentioned, and the dimension the mutation
    # never touched is byte-identical.
    after = parse_dimensions(merged.extensions)
    assert after == before
    assert after["work"].members == (
        third.vault_binding_id,
        first.vault_binding_id,
        second.vault_binding_id,
    )
    assert after["untouched"].members == (second.vault_binding_id,)
    assert all(dimension.last_repair is None for dimension in after.values())
    assert set(merged.registrations) == {
        first.vault_binding_id,
        second.vault_binding_id,
        third.vault_binding_id,
    }

    _finish_instance_state_deployment(
        channel=runtime.layout.channel_id,
        instance_state_root=runtime.layout.root.parent,
        host_global_root=runtime.ledger.root,
        legacy_path=rollback_path,
        inventory_path=owner_inventory,
        backup_root=tmp_path / "mvr04-backup",
        restore_root=None,
        quiescence_proof=proof,
    )

    # Dimension administration still works after roll-forward, on the merged revision.
    dimensions.set_members("work", [first.vault_binding_id, second.vault_binding_id])
    assert parse_dimensions(runtime.registry.load().extensions)["work"].members == (
        first.vault_binding_id,
        second.vault_binding_id,
    )
