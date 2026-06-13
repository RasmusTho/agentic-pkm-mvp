from __future__ import annotations

import pytest

from app.vault.app_local import AppLocalSettingsStore
from app.vault.markdown_settings import MarkdownSettingsStore
from app.vault.manager import VaultManager, VaultRequiredError


def _manager(tmp_path) -> VaultManager:
    return VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))


def test_vault_dependent_services_are_gated_without_selected_vault(tmp_path) -> None:
    manager = _manager(tmp_path)

    with pytest.raises(VaultRequiredError):
        manager.require_selected_vault(operation="handoff writer", require_writes=True)


def test_read_only_satellite_blocks_vault_writes(tmp_path) -> None:
    manager = _manager(tmp_path)
    vault = tmp_path / "vault"
    context = manager.initialize_vault(vault, machine_role="readOnlySatellite").context

    permissions = manager.permissions_for_context(context)

    assert permissions.allow_writes_to_vault is False
    assert permissions.enable_vault_watcher is False
    assert permissions.enable_auto_indexing is False
    with pytest.raises(VaultRequiredError):
        manager.require_selected_vault(operation="handoff writer", require_writes=True)

    local_path = vault / "settings" / "local.md"
    store = MarkdownSettingsStore()
    local_doc = store.read(local_path)
    frontmatter = dict(local_doc.frontmatter)
    frontmatter["allowWritesToVault"] = True
    frontmatter["enableVaultWatcher"] = True
    frontmatter["enableAutoIndexing"] = True
    store.write_frontmatter(local_path, frontmatter, body=local_doc.body)

    permissions = manager.permissions_for_context(context)
    assert permissions.allow_writes_to_vault is False
    assert permissions.enable_vault_watcher is False
    assert permissions.enable_auto_indexing is False
    with pytest.raises(VaultRequiredError):
        manager.require_selected_vault(operation="shared settings editor", require_shared_settings_edits=True)


def test_satellite_can_allow_local_only_settings_edits(tmp_path) -> None:
    manager = _manager(tmp_path)
    vault = tmp_path / "vault"
    context = manager.initialize_vault(vault, machine_role="satellite").context

    local_path = vault / "settings" / "local.md"
    store = MarkdownSettingsStore()
    local_doc = store.read(local_path)
    frontmatter = dict(local_doc.frontmatter)
    frontmatter["allowWritesToVault"] = False
    frontmatter["allowSharedSettingsEdits"] = False
    frontmatter["allowLocalSettingsEdits"] = True
    store.write_frontmatter(local_path, frontmatter, body=local_doc.body)

    permissions = manager.permissions_for_context(context)
    assert permissions.allow_writes_to_vault is False
    assert permissions.allow_shared_settings_edits is False
    assert permissions.allow_local_settings_edits is True

    manager.require_selected_vault(operation="local settings editor", require_local_settings_edits=True)
    with pytest.raises(VaultRequiredError):
        manager.require_selected_vault(operation="handoff writer", require_writes=True)
    with pytest.raises(VaultRequiredError):
        manager.require_selected_vault(operation="shared settings editor", require_shared_settings_edits=True)


def test_automation_node_can_run_background_services_when_enabled(tmp_path) -> None:
    manager = _manager(tmp_path)
    context = manager.initialize_vault(tmp_path / "vault", machine_role="automationNode").context

    permissions = manager.permissions_for_context(context)
    assert permissions.enable_vault_watcher is True
    assert permissions.enable_auto_indexing is True

    manager.require_selected_vault(operation="vault watcher", require_watcher=True)
    manager.require_selected_vault(operation="auto indexer", require_indexing=True)


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
