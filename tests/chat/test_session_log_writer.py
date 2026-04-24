from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.chat.session_log import SessionLog, SessionLogWriter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _writer(tmp_path: Path) -> SessionLogWriter:
    return SessionLogWriter(vault_root=tmp_path)


def _note(tmp_path: Path, name: str = "my-design-decision.md") -> Path:
    note = tmp_path / "notes" / name
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("---\ntype: note\n---\n\nBody.\n", encoding="utf-8")
    return note


# ---------------------------------------------------------------------------
# AC1: open_session creates a file under .chats/<slug>/
# ---------------------------------------------------------------------------

def test_open_creates_file_in_chats_namespace(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    note = _note(tmp_path)
    session = writer.open_session(note, "restructure-decision-section")

    assert session.log_path.exists()
    assert ".chats" in session.log_path.parts
    # Parent dir is the note slug
    assert session.log_path.parent.name == "my-design-decision"


# ---------------------------------------------------------------------------
# AC2: path follows vault/.chats/<note-slug>/<timestamp>-<label>.md
# ---------------------------------------------------------------------------

def test_log_path_uses_note_slug_and_timestamp(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    note = _note(tmp_path, "My Design Decision.md")
    session = writer.open_session(note, "expand-context")

    # slug directory
    assert session.log_path.parent.parent == tmp_path / ".chats"
    # filename contains the label
    assert "expand-context" in session.log_path.name
    # filename contains a timestamp-like prefix (digits and hyphens before label)
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}", session.log_path.stem)
    assert session.log_path.suffix == ".md"


# ---------------------------------------------------------------------------
# AC3: frontmatter contains type, note, date, session_id
# ---------------------------------------------------------------------------

def test_frontmatter_fields_present(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    note = _note(tmp_path)
    session = writer.open_session(note, "smoke")

    content = session.log_path.read_text(encoding="utf-8")
    assert "type: chat-session" in content
    assert "note:" in content
    assert "date:" in content
    assert "session_id:" in content


# ---------------------------------------------------------------------------
# AC4: type: chat-session — no collision test
# ---------------------------------------------------------------------------

def test_type_field_is_chat_session_only(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    note = _note(tmp_path)
    session = writer.open_session(note, "smoke")

    content = session.log_path.read_text(encoding="utf-8")
    # The frontmatter block type value must be exactly chat-session
    fm_match = re.search(r"^type:\s*(.+)$", content, re.MULTILINE)
    assert fm_match is not None
    assert fm_match.group(1).strip() == "chat-session"


# ---------------------------------------------------------------------------
# AC5: appends are additive; prior content preserved
# ---------------------------------------------------------------------------

def test_append_does_not_rewrite_prior_content(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    note = _note(tmp_path)
    session = writer.open_session(note, "multi-turn")

    writer.append_turn(session, "first prompt", "first change")
    after_first = session.log_path.read_text(encoding="utf-8")

    writer.append_turn(session, "second prompt", "second change")
    after_second = session.log_path.read_text(encoding="utf-8")

    # All prior content still present
    assert "first prompt" in after_second
    assert "first change" in after_second
    # New content appended
    assert "second prompt" in after_second
    assert "second change" in after_second
    # File only grew
    assert len(after_second) > len(after_first)


# ---------------------------------------------------------------------------
# AC6: close_session appends a closure line with total summary
# ---------------------------------------------------------------------------

def test_close_session_appends_closure_line(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    note = _note(tmp_path)
    session = writer.open_session(note, "smoke")
    writer.append_turn(session, "a prompt", "a change")
    writer.close_session(session, "One structural edit: rationale section added")

    content = session.log_path.read_text(encoding="utf-8")
    assert "One structural edit: rationale section added" in content
    # Session should be marked closed
    assert session.closed


# ---------------------------------------------------------------------------
# Extra: SessionLog carries expected fields
# ---------------------------------------------------------------------------

def test_session_log_carries_session_id_and_note_path(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    note = _note(tmp_path)
    session = writer.open_session(note, "smoke")

    assert session.session_id  # non-empty UUID string
    assert session.note_path == note
    assert not session.closed


def test_append_records_user_prompt_and_change_summary(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    note = _note(tmp_path)
    session = writer.open_session(note, "smoke")
    writer.append_turn(session, "Can you move the rationale?", "Moved rationale under ## Rationale")

    content = session.log_path.read_text(encoding="utf-8")
    assert "Can you move the rationale?" in content
    assert "Moved rationale under ## Rationale" in content
