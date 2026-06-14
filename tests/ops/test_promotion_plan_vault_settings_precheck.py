"""prepare-promotion vault-settings preflight flags an uninitialized prod vault — #1991."""

from __future__ import annotations

from pathlib import Path

from app.vault.manager import VaultManager
from app.vault.promotion_preflight import vault_settings_preflight


def test_flags_uninitialized_vault(tmp_path: Path) -> None:
    vault = tmp_path / "Midgård"
    vault.mkdir()

    pf = vault_settings_preflight(vault)

    assert pf.status == "uninitialized"
    assert pf.initialized is False
    assert pf.blocking is True
    assert pf.remedy and "vault init" in pf.remedy


def test_preflight_passes_after_init(tmp_path: Path) -> None:
    vault = tmp_path / "Midgård"
    VaultManager().initialize_vault(
        vault, vault_name="Midgård", machine_role="primary", remember=False
    )

    pf = vault_settings_preflight(vault)

    assert pf.initialized is True
    assert pf.blocking is False
    assert pf.remedy is None
