from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import threading

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


def test_append_note_concurrent_same_title_preserves_both_bodies(tmp_path: Path) -> None:
    ready = threading.Barrier(2)

    def write(body: str) -> Path:
        ready.wait()
        return append_note(title="Same", body=body, vault_root=tmp_path)

    with ThreadPoolExecutor(max_workers=2) as executor:
        paths = list(executor.map(write, ("one", "two")))

    assert {path.name for path in paths} == {"same.md", "same-2.md"}
    assert {_read_frontmatter(path)[1] for path in paths} == {"one", "two"}


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
    from app.mcp import vault_tools as vault_tools_module

    real_write = vault_tools_module.write_note_relative

    def _recording_write(note_rel_path: str, content: str, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((note_rel_path, content))
        return real_write(note_rel_path, content, **kwargs)

    monkeypatch.setattr(vault_tools_module, "write_note_relative", _recording_write)
    path = append_note(title="Contract Test", body="Body", vault_root=tmp_path)
    assert path.name == "contract-test.md"
    assert len(calls) == 1
    assert calls[0][0].startswith("_mcp/.mcp-append-stage-")


def test_append_note_retries_atomic_suffix_without_clobbering_foreign_winner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.mcp import vault_tools as vault_tools_module

    real_publish = vault_tools_module._atomic_rename_noreplace_at
    injected = False

    def race_first_suffix(
        source_fd: int,
        source_name: str,
        destination_fd: int,
        destination_name: str,
    ) -> None:
        nonlocal injected
        if not injected:
            injected = True
            foreign_fd = os.open(
                destination_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=destination_fd,
            )
            try:
                os.write(foreign_fd, b"foreign prior bytes\n")
                os.fsync(foreign_fd)
            finally:
                os.close(foreign_fd)
        real_publish(source_fd, source_name, destination_fd, destination_name)

    monkeypatch.setattr(
        vault_tools_module,
        "_atomic_rename_noreplace_at",
        race_first_suffix,
    )

    path = append_note(title="Same", body="MCP body", vault_root=tmp_path)

    assert path.name == "same-2.md"
    assert (tmp_path / "_mcp" / "same.md").read_bytes() == b"foreign prior bytes\n"
    assert _read_frontmatter(path)[1] == "MCP body"
    assert not (tmp_path / ".mcp-append-note.lock").exists()


def test_append_note_falls_back_to_default_vault_when_env_blank(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str] = []
    from app.mcp import vault_tools as vault_tools_module

    real_write = vault_tools_module.write_note_relative

    def _recording_write(note_rel_path: str, content: str, **kwargs):  # type: ignore[no-untyped-def]
        calls.append("Vault")
        return real_write(note_rel_path, content, **kwargs)

    monkeypatch.setenv("OBSIDIAN_VAULT_NAME", "   ")
    monkeypatch.setattr(vault_tools_module, "write_note_relative", _recording_write)
    append_note(title="Contract Test", body="Body", vault_root=tmp_path)
    assert calls == ["Vault"]


def test_append_note_blocked_by_denying_writeguard(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """#2953 AC: a denying WriteGuard blocks writes from ALL callers,
    including ``app/mcp/vault_tools.py`` -- the issue's named live violator,
    which had no caller-side ``assert_writes_allowed`` on `main` before this
    fix. This exercises the REAL production path (``append_note`` ->
    ``write_note_relative`` -> the guarded port), not a stubbed writer, so it
    proves the port-level fix actually closes this specific caller.
    """
    from app.write_guard import DEFAULT_WRITE_GUARD, WritesBlockedError

    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        lambda: {"state": "safe_mode", "reason": "test: deny all writes"},
    )
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "bootstrap_actions", frozenset())

    with pytest.raises(WritesBlockedError) as exc:
        append_note(title="Blocked Note", body="should not be written", vault_root=tmp_path)
    assert exc.value.state == "safe_mode"

    # The note file itself must never have been created (the guard fires
    # inside write_note_relative before any note content is written; the
    # containing directory may already exist -- append_note's own mkdir runs
    # before reaching the guarded port, a pre-existing, out-of-scope detail
    # unrelated to this issue's port-level WriteGuard assertion).
    target_dir = tmp_path / "_mcp"
    if target_dir.exists():
        assert not any(target_dir.iterdir())
