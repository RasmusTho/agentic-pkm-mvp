from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.chat.canvas_writer import CanvasWriter, GovernanceBearingMutationError
from app.chat.session_log import SessionLog, SessionLogWriter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_writer(vault_root: Path) -> SessionLogWriter:
    fixed_now = datetime(2026, 4, 24, 10, 0)
    return SessionLogWriter(vault_root=vault_root, now_fn=lambda: fixed_now, uuid_fn=lambda: "test-uuid")


def _note(vault_root: Path, name: str = "my-note.md", body: str = "Original body.") -> Path:
    note = vault_root / "notes" / name
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(f"---\ntype: note\nmaturity: draft\n---\n\n{body}\n", encoding="utf-8")
    return note


def _open_session(vault_root: Path, note: Path, label: str = "smoke") -> SessionLog:
    lw = _log_writer(vault_root)
    return lw.open_session(note, label)


# ---------------------------------------------------------------------------
# AC1: apply_edit writes body to vault via KnowledgePort
# ---------------------------------------------------------------------------

def test_apply_edit_writes_body_to_vault(tmp_path: Path) -> None:
    note = _note(tmp_path)
    session = _open_session(tmp_path, note)
    lw = _log_writer(tmp_path)
    writer = CanvasWriter(vault_root=tmp_path, log_writer=lw)

    writer.apply_edit(session, "New body content.", "replaced body")

    content = note.read_text(encoding="utf-8")
    assert "New body content." in content


# ---------------------------------------------------------------------------
# AC2: apply_edit preserves frontmatter unchanged
# ---------------------------------------------------------------------------

def test_apply_edit_preserves_frontmatter(tmp_path: Path) -> None:
    note = _note(tmp_path)
    session = _open_session(tmp_path, note)
    lw = _log_writer(tmp_path)
    writer = CanvasWriter(vault_root=tmp_path, log_writer=lw)

    writer.apply_edit(session, "Brand new body.", "body replaced")

    content = note.read_text(encoding="utf-8")
    assert "type: note" in content
    assert "maturity: draft" in content
    # Original body replaced
    assert "Original body." not in content
    assert "Brand new body." in content


# ---------------------------------------------------------------------------
# AC3: apply_edit raises GovernanceBearingMutationError on frontmatter in body
# ---------------------------------------------------------------------------

def test_apply_edit_rejects_frontmatter_in_body(tmp_path: Path) -> None:
    note = _note(tmp_path)
    session = _open_session(tmp_path, note)
    lw = _log_writer(tmp_path)
    writer = CanvasWriter(vault_root=tmp_path, log_writer=lw)

    with pytest.raises(GovernanceBearingMutationError):
        writer.apply_edit(session, "---\nmaturity: evergreen\n---\n\nBody", "frontmatter sneak")


# ---------------------------------------------------------------------------
# AC4: apply_edit raises on cross-note target (note_path outside vault_root)
# ---------------------------------------------------------------------------

def test_apply_edit_rejects_cross_note_target(tmp_path: Path) -> None:
    vault_a = tmp_path / "vault_a"
    vault_b = tmp_path / "vault_b"
    note_b = vault_b / "notes" / "other-note.md"
    note_b.parent.mkdir(parents=True, exist_ok=True)
    note_b.write_text("---\ntype: note\n---\n\nOther vault body.\n", encoding="utf-8")

    lw_a = _log_writer(vault_a)
    # Session was opened with a note path outside vault_a
    fake_session = SessionLog(
        log_path=vault_a / ".chats" / "other-note" / "2026-04-24T10-00-smoke.md",
        session_id="cross-note-test",
        note_path=note_b,
        label="cross",
    )
    writer = CanvasWriter(vault_root=vault_a, log_writer=lw_a)

    with pytest.raises(GovernanceBearingMutationError):
        writer.apply_edit(fake_session, "Sneaky body.", "cross-vault write attempt")


# ---------------------------------------------------------------------------
# AC5: apply_edit raises without open session
# ---------------------------------------------------------------------------

def test_apply_edit_requires_open_session(tmp_path: Path) -> None:
    lw = _log_writer(tmp_path)
    writer = CanvasWriter(vault_root=tmp_path, log_writer=lw)

    with pytest.raises(GovernanceBearingMutationError):
        writer.apply_edit(None, "body", "no session")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AC6: apply_edit records change summary in session log
# ---------------------------------------------------------------------------

def test_apply_edit_records_turn_in_session_log(tmp_path: Path) -> None:
    note = _note(tmp_path)
    lw = _log_writer(tmp_path)
    session = lw.open_session(note, "record-turn")
    writer = CanvasWriter(vault_root=tmp_path, log_writer=lw)

    writer.apply_edit(session, "Updated body.", "added three paragraphs")

    log_content = session.log_path.read_text(encoding="utf-8")
    assert "added three paragraphs" in log_content


# ---------------------------------------------------------------------------
# Extra: multiple edits each append to the log
# ---------------------------------------------------------------------------

def test_multiple_edits_each_append_to_log(tmp_path: Path) -> None:
    note = _note(tmp_path)
    lw = _log_writer(tmp_path)
    session = lw.open_session(note, "multi-edit")
    writer = CanvasWriter(vault_root=tmp_path, log_writer=lw)

    writer.apply_edit(session, "Body v1.", "first edit")
    writer.apply_edit(session, "Body v2.", "second edit")

    log_content = session.log_path.read_text(encoding="utf-8")
    assert "first edit" in log_content
    assert "second edit" in log_content
    # Latest body is what's in the note
    assert "Body v2." in note.read_text(encoding="utf-8")
