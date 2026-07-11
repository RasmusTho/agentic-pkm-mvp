from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json

import pytest

from app.chat.session_log import SessionLogWriter, load_chat_sessions_for_note
from app.chat.session_store import SessionStore
from app.vault.manager import VaultContext
from app.write_guard import DEFAULT_WRITE_GUARD, WritesBlockedError

pytestmark = pytest.mark.not_pg


def _writer(vault_root: Path) -> SessionLogWriter:
    fixed_now = datetime(2026, 4, 24, 7, 30)
    return SessionLogWriter(vault_root=vault_root, now_fn=lambda: fixed_now, uuid_fn=lambda: "session-uuid")


def _note(vault_root: Path) -> Path:
    note = vault_root / "notes" / "My Design Decision.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("---\ntype: note\n---\n\nNote body.\n", encoding="utf-8")
    return note


def test_open_creates_file_in_chats_namespace(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    note = _note(tmp_path)
    session = writer.open_session(note, "restructure decision section")

    assert session.log_path.exists()
    assert "/.chats/" in str(session.log_path)


def test_log_path_uses_note_slug_and_timestamp(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    note = _note(tmp_path)
    session = writer.open_session(note, "restructure decision section")

    assert session.log_path.parent == tmp_path / ".chats" / "my-design-decision"
    assert session.log_path.name.startswith("2026-04-24T07-30-")
    assert session.log_path.name.endswith("restructure-decision-section.md")


def test_frontmatter_fields_present(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    note = _note(tmp_path)
    session = writer.open_session(note, "restructure decision section")

    text = session.log_path.read_text(encoding="utf-8")
    assert "type: chat-session" in text
    assert 'note: "[[My Design Decision]]"' in text
    assert "note_uuid: " in text
    assert "date: 2026-04-24T07:30" in text
    assert "session_id: session-uuid" in text


def test_type_field_is_chat_session_only(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    note = _note(tmp_path)
    session = writer.open_session(note, "session")

    text = session.log_path.read_text(encoding="utf-8")
    assert text.count("type: chat-session") == 1


def test_append_does_not_rewrite_prior_content(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    note = _note(tmp_path)
    session = writer.open_session(note, "session")
    baseline = session.log_path.read_text(encoding="utf-8")

    writer.append_turn(session, "Can you move the rationale?", "Moved rationale to dedicated section")

    updated = session.log_path.read_text(encoding="utf-8")
    assert baseline in updated
    assert "**User:** Can you move the rationale?" in updated
    assert "**Change:** Moved rationale to dedicated section" in updated


def test_close_session_appends_closure_line(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    note = _note(tmp_path)
    session = writer.open_session(note, "session")

    writer.close_session(session, "One structural edit")

    text = session.log_path.read_text(encoding="utf-8")
    assert "*Session closed. Total: One structural edit.*" in text


def test_open_session_resolves_and_writes_note_uuid(tmp_path: Path) -> None:
    session = _writer(tmp_path).open_session(_note(tmp_path), "session")

    assert session.note_uuid
    assert f"note_uuid: {session.note_uuid}" in session.log_path.read_text(encoding="utf-8")


def test_writes_blocked_by_writeguard_at_call_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    writer = _writer(tmp_path)
    note = _note(tmp_path)
    original_assert = DEFAULT_WRITE_GUARD.assert_writes_allowed

    def _blocked(action: str) -> None:
        if action == "chat_session.persist":
            raise WritesBlockedError("unhealthy", "test", action)
        original_assert(action)

    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "assert_writes_allowed", _blocked)
    with pytest.raises(WritesBlockedError):
        writer.open_session(note, "blocked")
    assert not (tmp_path / ".chats").exists()

    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "assert_writes_allowed", original_assert)
    session = writer.open_session(note, "active")
    baseline = session.log_path.read_text(encoding="utf-8")
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "assert_writes_allowed", _blocked)
    with pytest.raises(WritesBlockedError):
        writer.append_turn(session, "prompt", "summary")
    assert session.log_path.read_text(encoding="utf-8") == baseline
    with pytest.raises(WritesBlockedError):
        writer.close_session(session, "summary")
    assert session.log_path.read_text(encoding="utf-8") == baseline


def test_writes_route_through_knowledge_port(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    writer = _writer(tmp_path)
    note = _note(tmp_path)
    calls: list[str] = []
    from app.chat import session_log

    original_write = session_log.write_note_relative
    original_append = session_log.append_note_relative

    def _write(*args: object, **kwargs: object) -> object:
        calls.append("write")
        return original_write(*args, **kwargs)  # type: ignore[arg-type]

    def _append(*args: object, **kwargs: object) -> object:
        calls.append("append")
        return original_append(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(session_log, "write_note_relative", _write)
    monkeypatch.setattr(session_log, "append_note_relative", _append)
    session = writer.open_session(note, "session")
    writer.append_turn(session, "prompt", "summary")
    writer.close_session(session, "summary")

    assert calls == ["write", "append", "append"]


def test_load_by_note_uuid_survives_stale_slug(tmp_path: Path) -> None:
    session = _writer(tmp_path).open_session(_note(tmp_path), "session")
    stale_dir = tmp_path / ".chats" / "old-note-title"
    stale_dir.mkdir(parents=True)
    stale_path = stale_dir / session.log_path.name
    session.log_path.rename(stale_path)
    context = VaultContext(status="selected", active_vault_path=str(tmp_path))

    found = load_chat_sessions_for_note(session.note_uuid or "", vault_context=context)

    assert [item.session_id for item in found] == [session.session_id]


def test_session_store_load_heals_legacy_json_missing_note_uuid(tmp_path: Path) -> None:
    note = _note(tmp_path)
    store = SessionStore(vault_root=tmp_path)
    store._session_dir.mkdir(parents=True)
    (store._session_dir / "legacy.json").write_text(
        json.dumps(
            {
                "log_path": str(tmp_path / ".chats" / "old" / "legacy.md"),
                "session_id": "legacy",
                "note_path": str(note),
                "label": "legacy",
                "vault_root": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )

    session = store.load("legacy")

    assert session is not None
    assert session.note_uuid
