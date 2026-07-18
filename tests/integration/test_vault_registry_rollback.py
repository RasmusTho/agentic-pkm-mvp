from __future__ import annotations

import pytest

from app.instance.instance_state import InstanceStateLayout
from app.instance.runtime import InstanceRegistryRuntime
from app.instance.vault_registry import (
    AppLocalSettingsStore,
    CapabilityNotReadyError,
    KnownVaultRef,
)


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

    for producer in ("picker", "api", "cli", "import", "bootstrap", "direct-service"):
        with pytest.raises(CapabilityNotReadyError, match="MVR-01C authority cutover"):
            runtime.production_register(second, producer=producer)

    assert len(runtime.registry.load().registrations) == 1
    assert len(runtime.ledger.load().leases) == 1


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
