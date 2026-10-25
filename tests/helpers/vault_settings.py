from __future__ import annotations

from pathlib import Path

from app.vault.manager import VaultManager


def initialize_test_vault(vault_root: Path) -> Path:
    """Create the minimal selected-vault settings contract for temp test vaults."""
    VaultManager().initialize_vault(vault_root, machine_role="testNode", remember=False)
    return vault_root


def set_test_screen_retention(vault_root: Path, minutes: int) -> None:
    """Set SCREEN-06 policy through its real governed producer in a test vault."""
    from unittest.mock import patch

    from app.vault.settings_service import SettingsService
    from app.write_guard import DEFAULT_WRITE_GUARD

    initialize_test_vault(vault_root)
    context = VaultManager().validate_vault(vault_root)
    with patch.object(DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": "healthy"}):
        SettingsService().update_setting(
            context, "screen_frame_retention_minutes", minutes, surface="cli", actor="test-operator",
        )
