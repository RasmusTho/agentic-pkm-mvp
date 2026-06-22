from __future__ import annotations

from pathlib import Path

import pytest

from app.mcp.vault_tools import VaultToolError, append_note, get_vault_root


def _clear_vault_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("VAULT_ROOT", "VAULT_ROOT_DEV", "VAULT_ROOT_TEST", "MCP_VAULT_ROOT", "VAULT_DIR"):
        monkeypatch.delenv(name, raising=False)


def test_get_vault_root_does_not_fallback_to_cwd_vault(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_vault_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vault").mkdir()

    with pytest.raises(VaultToolError, match="vault root is required"):
        get_vault_root()


def test_append_note_requires_explicit_or_configured_vault(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_vault_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vault").mkdir()

    with pytest.raises(VaultToolError, match="vault root is required"):
        append_note(title="No Vault", body="Should not write")
    assert not (tmp_path / "vault" / "_mcp").exists()


@pytest.mark.parametrize("env_var", ["MCP_VAULT_ROOT", "VAULT_DIR"])
def test_append_note_rejects_missing_mcp_specific_env(
    env_var: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_vault_env(monkeypatch)
    missing_vault = tmp_path / "missing-vault"
    fallback_vault = tmp_path / "fallback-vault"
    fallback_vault.mkdir()
    monkeypatch.setenv(env_var, str(missing_vault))
    monkeypatch.setenv("VAULT_ROOT", str(fallback_vault))

    with pytest.raises(VaultToolError, match=f"{env_var} is set to a missing vault root"):
        append_note(title="No Vault", body="Should not write")

    assert not missing_vault.exists()
    assert not (fallback_vault / "_mcp").exists()


def test_get_vault_root_uses_configured_vault_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_vault_env(monkeypatch)
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))

    assert get_vault_root() == tmp_path
