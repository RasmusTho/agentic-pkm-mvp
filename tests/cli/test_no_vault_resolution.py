from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.stores.plan_store import reset_plan_store


def _clear_vault_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "VAULT_ROOT",
        "VAULT_ROOT_DEV",
        "VAULT_ROOT_TEST",
        "MCP_VAULT_ROOT",
        "VAULT_DIR",
        "MCP_VAULT_ENABLE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_canvas_open_requires_explicit_or_configured_vault(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_vault_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    cwd_vault_note = tmp_path / "vault" / "note.md"
    cwd_vault_note.parent.mkdir()
    cwd_vault_note.write_text("# Should not be opened\n", encoding="utf-8")

    result = CliRunner().invoke(cli, ["canvas", "open", "note.md"])

    assert result.exit_code != 0
    assert "vault root is required" in result.output.lower()


def test_ask_enable_mcp_vault_requires_explicit_or_configured_vault(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_vault_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    reset_plan_store()

    result = CliRunner().invoke(cli, ["ask", "What should be saved?", "--enable-mcp-vault"])

    assert result.exit_code != 0
    assert "vault root is required" in result.output.lower()
    assert not (tmp_path / "vault" / "_mcp").exists()


def test_ask_enable_mcp_vault_accepts_mcp_specific_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_vault_env(monkeypatch)
    reset_plan_store()
    mcp_vault = tmp_path / "mcp-vault"
    mcp_vault.mkdir()
    monkeypatch.setenv("MCP_VAULT_ROOT", str(mcp_vault))

    result = CliRunner().invoke(cli, ["ask", "What should be saved?", "--enable-mcp-vault"])

    assert result.exit_code == 0, result.output
    files = list((mcp_vault / "_mcp").glob("*.md"))
    assert len(files) == 1


def test_ask_enable_mcp_vault_prefers_mcp_env_over_vault_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_vault_env(monkeypatch)
    reset_plan_store()
    normal_vault = tmp_path / "normal-vault"
    mcp_vault = tmp_path / "mcp-vault"
    normal_vault.mkdir()
    mcp_vault.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(normal_vault))
    monkeypatch.setenv("MCP_VAULT_ROOT", str(mcp_vault))

    result = CliRunner().invoke(cli, ["ask", "What should be saved?", "--enable-mcp-vault"])

    assert result.exit_code == 0, result.output
    assert list((mcp_vault / "_mcp").glob("*.md"))
    assert not (normal_vault / "_mcp").exists()
