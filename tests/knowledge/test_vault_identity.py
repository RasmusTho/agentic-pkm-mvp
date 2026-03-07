from __future__ import annotations

from app.knowledge.vault_identity import resolve_obsidian_vault_name


def test_resolve_obsidian_vault_name_defaults_to_vault() -> None:
    assert resolve_obsidian_vault_name({}) == "Vault"


def test_resolve_obsidian_vault_name_uses_nonblank_value() -> None:
    assert resolve_obsidian_vault_name({"OBSIDIAN_VAULT_NAME": "Mimer"}) == "Mimer"


def test_resolve_obsidian_vault_name_trims_and_falls_back_on_blank() -> None:
    assert resolve_obsidian_vault_name({"OBSIDIAN_VAULT_NAME": "   "}) == "Vault"
