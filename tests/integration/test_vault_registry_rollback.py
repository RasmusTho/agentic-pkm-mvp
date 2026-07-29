from __future__ import annotations

from pathlib import Path

import pytest

from app.instance.instance_state import InstanceStateLayout
from app.instance.runtime import InstanceRegistryRuntime
from app.instance.scalar_rollback_guard import preflight_scalar_rollback_guard
from app.instance.vault_registry import (
    AppLocalSettingsStore,
    CapabilityNotReadyError,
    KnownVaultRef,
    RegistryError,
)


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
    runtime.activate_authority(
        guard_receipt=_guard_receipt(first.vault_binding_id, root),
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


def test_previous_image_reads_latest_post_migration_registry_state(tmp_path) -> None:
    runtime, first = _active_runtime(tmp_path)
    rollback_path = tmp_path / "previous-image" / "app-local.md"

    projected = runtime.registry.materialize_legacy_rollback(
        rollback_path,
        rollback_vault_binding_id=first.vault_binding_id,
    )

    assert set(projected.known_vaults) == {first.ref}
    assert projected.last_active_vault_ref == first.ref
    runtime.registry.rollback_export_path.write_text("stale", encoding="utf-8")
    with pytest.raises(RegistryError, match="missing or stale"):
        runtime.registry.materialize_legacy_rollback(
            rollback_path,
            rollback_vault_binding_id=first.vault_binding_id,
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


def test_01c_unseals_second_registration_only_with_complete_rollback_floor(tmp_path) -> None:
    runtime = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / "instance-state", "prod"),
        tmp_path / "host-global",
    )
    first_root = tmp_path / "one"
    first_root.mkdir()
    first = runtime.bootstrap_env_binding(vault_root=first_root, watcher_vault_path=first_root)
    before = runtime.layout.registry_path.read_bytes()

    with pytest.raises(RegistryError, match="injected partial"):
        runtime.activate_authority(
            guard_receipt=_guard_receipt(first.vault_binding_id, first_root),
            inject_failure_before_commit=True,
        )
    assert runtime.layout.registry_path.read_bytes() == before
    with pytest.raises(CapabilityNotReadyError, match="authority cutover"):
        runtime.production_register(tmp_path / "sealed", producer="picker")

    runtime.activate_authority(
        guard_receipt=_guard_receipt(first.vault_binding_id, first_root),
    )
    for producer in ("picker", "api", "cli", "import", "bootstrap", "direct-service"):
        root = tmp_path / producer
        root.mkdir()
        assert runtime.production_register(root, producer=producer).path == str(root)


def test_rollback_mutations_round_trip_on_roll_forward(tmp_path) -> None:
    runtime, first = _active_runtime(tmp_path)
    rollback_path = tmp_path / "rollback" / "app-local.md"
    runtime.registry.materialize_legacy_rollback(
        rollback_path,
        rollback_vault_binding_id=first.vault_binding_id,
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

    merged = runtime.merge_previous_scalar_image(rollback_path)

    assert merged.registrations[first.vault_binding_id].vault_name == "Renamed during rollback"
    assert merged.extensions["scalarRollForwardLineage"][-1]["mergedRegistryRevision"] == merged.revision

    divergent = tmp_path / "rollback" / "divergent.md"
    divergent.write_bytes(rollback_path.read_bytes())
    divergent_lineage = divergent.with_suffix(divergent.suffix + ".mvr-lineage.json")
    divergent_lineage.write_bytes(
        rollback_path.with_suffix(rollback_path.suffix + ".mvr-lineage.json")
        .read_bytes()
        .replace(b'"forkRegistryRevision": 2', b'"forkRegistryRevision": 1')
    )
    divergent_lineage.chmod(0o600)
    before = runtime.layout.registry_path.read_bytes()
    with pytest.raises(RegistryError, match="stale, ambiguous, or divergent"):
        runtime.merge_previous_scalar_image(divergent)
    assert runtime.layout.registry_path.read_bytes() == before
