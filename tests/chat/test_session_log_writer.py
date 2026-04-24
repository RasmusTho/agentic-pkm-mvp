from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.chat.session_log import SessionLogWriter

pytestmark = pytest.mark.not_pg


def _writer(vault_root: Path) -> SessionLogWriter:
    fixed_now = datetime(2026, 4, 24, 7, 30)
    return SessionLogWriter(vault_root=vault_root, now_fn=lambda: fixed_now, uuid_fn=lambda: "session-uuid")


def test_open_creates_file_in_chats_namespace(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    note = tmp_path / "notes" / "My Design Decision.md"
    session = writer.open_session(note, "restructure decision section")

    assert session.log_path.exists()
    assert "/.chats/" in str(session.log_path)


def test_log_path_uses_note_slug_and_timestamp(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    note = tmp_path / "notes" / "My Design Decision.md"
    session = writer.open_session(note, "restructure decision section")

    assert session.log_path.parent == tmp_path / ".chats" / "my-design-decision"
    assert session.log_path.name.startswith("2026-04-24T07-30-")
    assert session.log_path.name.endswith("restructure-decision-section.md")


def test_frontmatter_fields_present(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    note = tmp_path / "notes" / "My Design Decision.md"
    session = writer.open_session(note, "restructure decision section")

    text = session.log_path.read_text(encoding="utf-8")
    assert "type: chat-session" in text
    assert 'note: "[[My Design Decision]]"' in text
    assert "date: 2026-04-24T07:30" in text
    assert "session_id: session-uuid" in text


def test_type_field_is_chat_session_only(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    note = tmp_path / "notes" / "My Design Decision.md"
    session = writer.open_session(note, "session")

    text = session.log_path.read_text(encoding="utf-8")
    assert text.count("type: chat-session") == 1


def test_append_does_not_rewrite_prior_content(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    note = tmp_path / "notes" / "My Design Decision.md"
    session = writer.open_session(note, "session")
    baseline = session.log_path.read_text(encoding="utf-8")

    writer.append_turn(session, "Can you move the rationale?", "Moved rationale to dedicated section")

    updated = session.log_path.read_text(encoding="utf-8")
    assert baseline in updated
    assert "**User:** Can you move the rationale?" in updated
    assert "**Change:** Moved rationale to dedicated section" in updated


def test_close_session_appends_closure_line(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    note = tmp_path / "notes" / "My Design Decision.md"
    session = writer.open_session(note, "session")

    writer.close_session(session, "One structural edit")

    text = session.log_path.read_text(encoding="utf-8")
    assert "*Session closed. Total: One structural edit.*" in text
