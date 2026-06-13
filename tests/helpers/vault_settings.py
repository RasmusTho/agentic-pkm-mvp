from __future__ import annotations

from pathlib import Path

from app.vault.manager import VaultManager


def initialize_test_vault(vault_root: Path) -> Path:
    """Create the minimal selected-vault settings contract for temp test vaults."""
    VaultManager().initialize_vault(vault_root, machine_role="testNode", remember=False)
    return vault_root
