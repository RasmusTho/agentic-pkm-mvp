from __future__ import annotations

import pytest

from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager, VaultRequiredError


def _manager(tmp_path) -> VaultManager:
    return VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))


def test_vault_dependent_services_are_gated_without_selected_vault(tmp_path) -> None:
    manager = _manager(tmp_path)

    with pytest.raises(VaultRequiredError):
        manager.require_selected_vault(operation="handoff writer", require_writes=True)


def test_read_only_satellite_blocks_vault_writes(tmp_path) -> None:
    manager = _manager(tmp_path)
    context = manager.initialize_vault(tmp_path / "vault", machine_role="readOnlySatellite").context

    permissions = manager.permissions_for_context(context)

    assert permissions.allow_writes_to_vault is False
    with pytest.raises(VaultRequiredError):
        manager.require_selected_vault(operation="handoff writer", require_writes=True)


def test_watcher_config_rejects_uninitialized_vault(tmp_path, monkeypatch) -> None:
    from app.watcher.config import WatcherConfig

    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault))

    with pytest.raises(ValueError, match="status=uninitialized"):
        WatcherConfig.from_env()


def test_watcher_config_accepts_initialized_vault(tmp_path, monkeypatch) -> None:
    from app.watcher.config import WatcherConfig

    vault = tmp_path / "vault"
    _manager(tmp_path).initialize_vault(vault)
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault))

    cfg = WatcherConfig.from_env()

    assert cfg.vault_path == vault
