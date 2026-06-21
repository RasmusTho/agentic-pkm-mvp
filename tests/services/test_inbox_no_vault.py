from __future__ import annotations

from pathlib import Path

import pytest

from app.services.inbox import append_change, append_conflict

pytestmark = pytest.mark.not_pg


def test_inbox_appenders_skip_without_selected_vault(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Inbox/change/conflict appenders skip when no vault is selected.

    Slice 05B (#2384): the legacy CWD-relative ``Path("vault")`` fallback is
    removed from the inbox resolver, so calling the appenders with no selected
    vault must no-op rather than write into ``./vault`` under the working
    directory. The knowledge-port writer must never be invoked.
    """
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)
    monkeypatch.delenv("VAULT_CHANGE_LOG_NOTE_REL", raising=False)
    monkeypatch.delenv("VAULT_CONFLICT_LOG_NOTE_REL", raising=False)
    monkeypatch.chdir(tmp_path)

    writes: list[tuple[str, str]] = []

    def _fail_append(note_rel_path: str, content: str, *, vault_root):  # type: ignore[no-untyped-def]
        writes.append((note_rel_path, content))
        return None

    monkeypatch.setattr("app.services.inbox.append_note_relative", _fail_append)

    append_change("should not write")
    append_conflict("should not write either")

    assert writes == []
    assert not (tmp_path / "vault").exists()


def test_inbox_appenders_write_with_explicit_vault(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Selected-vault behavior is preserved: an explicit vault still writes."""
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    note_rel = "Inbox/_system_changes.md"
    append_change("hello", note_rel_path=note_rel, vault_root=tmp_path)
    target = tmp_path / note_rel
    assert target.exists()
    assert "hello" in target.read_text(encoding="utf-8")
