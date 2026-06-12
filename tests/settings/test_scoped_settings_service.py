from __future__ import annotations

from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager, no_vault_context
from app.vault.settings_service import SettingsService


def test_missing_settings_fall_back_to_defaults() -> None:
    effective = SettingsService().effective_settings(no_vault_context())

    assert effective["handoffFolder"].value == "Design Handoff"
    assert effective["handoffFolder"].source == "built-in"


def test_vault_local_settings_override_shared_settings(tmp_path) -> None:
    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))
    context = manager.initialize_vault(tmp_path / "vault").context
    local = tmp_path / "vault" / "settings" / "local.md"
    text = local.read_text(encoding="utf-8")
    local.write_text(text.replace("enableVaultWatcher: true", "enableVaultWatcher: false"), encoding="utf-8")

    effective = SettingsService().effective_settings(context)

    assert effective["enableVaultWatcher"].value is False
    assert effective["enableVaultWatcher"].source == str(local)
