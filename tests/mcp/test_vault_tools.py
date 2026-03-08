from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.mcp.vault_tools import append_note, get_vault_root, VaultToolError


def _read_frontmatter(path: Path) -> tuple[dict[str, object], str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    remainder = text[4:]
    divider = remainder.index("\n---\n\n")
    frontmatter_block = remainder[:divider]
    body = remainder[divider + len("\n---\n\n") :]
    frontmatter = yaml.safe_load(frontmatter_block) or {}
    return frontmatter, body.rstrip()


def test_append_note_writes_markdown(tmp_path: Path) -> None:
    path = append_note(
        title="Test Summary",
        body="Hello vault",
        tags=["ask", "summary"],
        metadata={"source": "planner"},
        vault_root=tmp_path,
    )
    assert path.exists()
    assert path.parent == tmp_path / "_mcp"
    frontmatter, body = _read_frontmatter(path)
    assert frontmatter["title"] == "Test Summary"
    assert frontmatter["tags"] == ["ask", "summary"]
    assert frontmatter["metadata"] == {"source": "planner"}
    assert body == "Hello vault"


def test_append_note_sequential_names(tmp_path: Path) -> None:
    first = append_note(title="Test", body="one", vault_root=tmp_path)
    second = append_note(title="Test", body="two", vault_root=tmp_path)
    assert first.name == "test.md"
    assert second.name == "test-2.md"


def test_get_vault_root_prefers_settings(tmp_path: Path) -> None:
    settings = {"vault_root": tmp_path}
    assert get_vault_root(settings) == tmp_path


def test_get_vault_root_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MCP_VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_DIR", raising=False)
    monkeypatch.setenv("MCP_VAULT_ROOT", str(tmp_path))
    assert get_vault_root() == tmp_path


def test_get_vault_root_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MCP_VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_DIR", raising=False)
    with pytest.raises(VaultToolError):
        get_vault_root({})


def test_append_note_requires_fields(tmp_path: Path) -> None:
    with pytest.raises(VaultToolError):
        append_note(title="", body="missing", vault_root=tmp_path)
    with pytest.raises(VaultToolError):
        append_note(title="Valid", body=" ", vault_root=tmp_path)


def test_append_note_uses_knowledge_port_writer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def _fake_write(note_rel_path: str, content: str, *, vault_root: Path | str):  # type: ignore[no-untyped-def]
        calls.append((note_rel_path, content))
        return None

    monkeypatch.setattr("app.mcp.vault_tools.write_note_relative", _fake_write)
    path = append_note(title="Contract Test", body="Body", vault_root=tmp_path)
    assert path.name == "contract-test.md"
    assert calls and calls[0][0] == "_mcp/contract-test.md"


def test_append_note_falls_back_to_default_vault_when_env_blank(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str] = []

    def _fake_write(note_rel_path: str, content: str, *, vault_root: Path | str):  # type: ignore[no-untyped-def]
        calls.append("Vault")
        return None

    monkeypatch.setenv("OBSIDIAN_VAULT_NAME", "   ")
    monkeypatch.setattr("app.mcp.vault_tools.write_note_relative", _fake_write)
    append_note(title="Contract Test", body="Body", vault_root=tmp_path)
    assert calls == ["Vault"]
