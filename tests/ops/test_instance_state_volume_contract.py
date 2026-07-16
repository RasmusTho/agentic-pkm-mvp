from __future__ import annotations

import pytest

from app.instance.vault_registry import (
    AppLocalSettingsStore,
    CapabilityNotReadyError,
    RegistryActivationProof,
    VaultRegistration,
    VaultRegistryStore,
)
from app.vault.manager import VaultManager


def test_mvr01a_schema_activation_requires_rollback_capability(tmp_path) -> None:
    registry_path = tmp_path / "vault-registry.md"
    store = VaultRegistryStore(registry_path)
    store.register(VaultRegistration("binding-a", "path:/a", "/a"))

    with pytest.raises(CapabilityNotReadyError, match="MVR-01B rollback exporter/transformer"):
        store.require_authoritative_activation(RegistryActivationProof())

    with pytest.raises(CapabilityNotReadyError, match="MVR-01C authority cutover"):
        store.require_authoritative_activation(
            RegistryActivationProof(
                rollback_exporter=True,
                rollback_transformer=True,
                previous_image_preflight=True,
            )
        )

    assert store.load().authority == "dormant"

    legacy_path = tmp_path / "app-local.md"
    vault_path = tmp_path / "vault"
    manager = VaultManager(app_local_store=AppLocalSettingsStore(legacy_path))
    manager.initialize_vault(vault_path, remember=True)
    assert AppLocalSettingsStore(legacy_path).load().known_vaults
    assert VaultRegistryStore(registry_path).load().revision == 1
