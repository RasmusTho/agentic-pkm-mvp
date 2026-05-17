"""Tests for Canvas Core session provenance write/read integration (#1028).

Session provenance is the append-only intent trail subordinate to the note.
These tests verify open-at-start, append-during-session, undo marking, path
exposure, interruption retention, and note-as-artifact primacy.

ACs from #1028:
- test_session_log_opened_at_session_start
- test_session_log_appends_during_session
- test_assistant_edit_summary_recorded
- test_undone_edit_marker_recorded
- test_session_log_path_exposed_for_inspection
- test_interrupted_session_retains_provenance
- test_provenance_is_subordinate_to_note
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from companion_ui.canvas_core.body_edit import AppliedEdit
from companion_ui.canvas_core.session_provenance import CanvasSessionProvenance
from companion_ui.canvas_core.undo_stack import UndoneEdit

# ---------------------------------------------------------------------------
# In-memory fake ProvenanceWriter (no file I/O, no app/ imports in tests)
# Structurally matches SessionLogWriter API.
# ---------------------------------------------------------------------------


@dataclass
class _FakeSession:
    log_path: Path
    session_id: str


@dataclass
class _FakeWriter:
    """In-memory test double for ProvenanceWriter / SessionLogWriter."""

    _sessions: list[_FakeSession] = field(default_factory=list)
    _turns: dict[str, list[dict]] = field(default_factory=dict)
    _closures: dict[str, str] = field(default_factory=dict)

    def open_session(self, note_path: Path, session_label: str) -> _FakeSession:
        sid = f"fake-session-{len(self._sessions) + 1:03d}"
        log_path = Path(f"/fake/.chats/{note_path.stem}/{session_label}.md")
        sess = _FakeSession(log_path=log_path, session_id=sid)
        self._sessions.append(sess)
        self._turns[sid] = []
        return sess

    def append_turn(self, session: _FakeSession, user_prompt: str, change_summary: str) -> None:
        self._turns[session.session_id].append(
            {"user_prompt": user_prompt, "change_summary": change_summary}
        )

    def close_session(self, session: _FakeSession, total_summary: str) -> None:
        self._closures[session.session_id] = total_summary

    # --- test helpers ---

    def turns_for(self, session_id: str) -> list[dict]:
        return self._turns.get(session_id, [])

    def is_closed(self, session_id: str) -> bool:
        return session_id in self._closures


NOTE_PATH = Path("/vault/notes/my-note.md")
SESSION_LABEL = "editing-intro"


def _make_provenance(writer: _FakeWriter | None = None) -> CanvasSessionProvenance:
    return CanvasSessionProvenance(
        writer=writer or _FakeWriter(),
        note_path=NOTE_PATH,
        session_label=SESSION_LABEL,
    )


def _applied_edit(edit_id: str = "e-001", session_id: str = "s-001") -> AppliedEdit:
    return AppliedEdit(
        edit_id=edit_id,
        session_id=session_id,
        artifact_id="note-test",
        body_before="before",
        body_after="after",
        edit_summary="Rewrote intro",
        user_prompt="Rewrite the intro",
    )


def _undone_edit(original: AppliedEdit) -> UndoneEdit:
    return UndoneEdit(
        undo_id="u-001",
        session_id=original.session_id,
        artifact_id=original.artifact_id,
        original_edit=original,
    )


# ---------------------------------------------------------------------------
# AC: Canvas session opens/creates a session log at session start
# ---------------------------------------------------------------------------


def test_session_log_opened_at_session_start() -> None:
    writer = _FakeWriter()
    prov = _make_provenance(writer)

    assert prov.session_log_path is None, "Log path must not exist before open()"
    prov.open()

    assert prov.session_log_path is not None
    assert prov.is_open
    assert len(writer._sessions) == 1


def test_open_raises_if_called_twice() -> None:
    prov = _make_provenance()
    prov.open()
    with pytest.raises(RuntimeError):
        prov.open()


# ---------------------------------------------------------------------------
# AC: Canvas session appends turn/edit summaries during the session (not only at close)
# ---------------------------------------------------------------------------


def test_session_log_appends_during_session() -> None:
    writer = _FakeWriter()
    prov = _make_provenance(writer)
    prov.open()

    sid = prov.session_id
    assert len(writer.turns_for(sid)) == 0

    edit = _applied_edit()
    prov.record_edit(edit)
    assert len(writer.turns_for(sid)) == 1

    prov.record_edit(_applied_edit(edit_id="e-002"))
    assert len(writer.turns_for(sid)) == 2

    assert not writer.is_closed(sid), "Session must not be closed after recording turns"


# ---------------------------------------------------------------------------
# AC: assistant-applied body edits include provenance markers/summary
# ---------------------------------------------------------------------------


def test_assistant_edit_summary_recorded() -> None:
    writer = _FakeWriter()
    prov = _make_provenance(writer)
    prov.open()

    edit = _applied_edit(edit_id="e-abc")
    prov.record_edit(edit)

    turns = writer.turns_for(prov.session_id)
    assert len(turns) == 1
    turn = turns[0]
    assert "e-abc" in turn["change_summary"], "Edit ID must appear in provenance"
    assert "Rewrote intro" in turn["change_summary"]
    assert turn["user_prompt"] == "Rewrite the intro"


# ---------------------------------------------------------------------------
# AC: undone assistant edits are marked in provenance without deleting history
# ---------------------------------------------------------------------------


def test_undone_edit_marker_recorded() -> None:
    writer = _FakeWriter()
    prov = _make_provenance(writer)
    prov.open()

    edit = _applied_edit(edit_id="e-001")
    prov.record_edit(edit)

    undone = _undone_edit(edit)
    prov.record_undo(undone)

    turns = writer.turns_for(prov.session_id)
    assert len(turns) == 2, "Both the original edit and the undo must be recorded"

    undo_turn = turns[1]
    assert "undo" in undo_turn["change_summary"].lower()
    assert "e-001" in undo_turn["change_summary"], "Original edit ID must appear in undo marker"
    assert undo_turn["user_prompt"] == "(undo)"


# ---------------------------------------------------------------------------
# AC: UI/runtime exposes an inspectable session log path for the active session
# ---------------------------------------------------------------------------


def test_session_log_path_exposed_for_inspection() -> None:
    prov = _make_provenance()
    assert prov.session_log_path is None

    prov.open()

    path = prov.session_log_path
    assert path is not None
    assert isinstance(path, Path)

    summary = prov.summary()
    assert summary is not None
    assert summary.session_log_path == path
    assert summary.is_open


# ---------------------------------------------------------------------------
# AC: paused/interrupted sessions retain provenance up to interruption
# ---------------------------------------------------------------------------


def test_interrupted_session_retains_provenance() -> None:
    writer = _FakeWriter()
    prov = _make_provenance(writer)
    prov.open()

    edit = _applied_edit()
    prov.record_edit(edit)

    prov.record_interruption("paused")

    sid = prov.session_id
    turns = writer.turns_for(sid)
    assert len(turns) == 2, "Edit and interruption marker must both be recorded"

    interruption_turn = turns[1]
    assert "paused" in interruption_turn["change_summary"]
    assert not writer.is_closed(sid), "Session must not be auto-closed on interruption"


def test_interrupted_session_provenance_not_lost() -> None:
    writer = _FakeWriter()
    prov = _make_provenance(writer)
    prov.open()

    prov.record_edit(_applied_edit(edit_id="e-1"))
    prov.record_edit(_applied_edit(edit_id="e-2"))
    prov.record_interruption("interrupted")

    # After interruption, all previously recorded turns are still accessible.
    turns = writer.turns_for(prov.session_id)
    summaries = " ".join(t["change_summary"] for t in turns)
    assert "e-1" in summaries
    assert "e-2" in summaries


# ---------------------------------------------------------------------------
# AC: session provenance is subordinate to note artifact and not rendered as body
# ---------------------------------------------------------------------------


def test_provenance_is_subordinate_to_note() -> None:
    """Provenance module must not treat session log as canonical body content."""
    import inspect
    from companion_ui.canvas_core import session_provenance as mod

    src = inspect.getsource(mod)

    assert "canonical" not in src or "subordinate" in src, (
        "If 'canonical' appears, 'subordinate' must also appear to preserve framing"
    )
    assert "session_log" not in src.split("from")[0] or "subordinate" in src

    # ProvenanceSummary must not carry a 'body' field — provenance is not body content.
    from companion_ui.canvas_core.session_provenance import ProvenanceSummary
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(ProvenanceSummary)}
    assert "body" not in field_names
    assert "artifact_body" not in field_names


def test_provenance_record_operations_require_open() -> None:
    prov = _make_provenance()

    with pytest.raises(RuntimeError):
        prov.record_edit(_applied_edit())

    with pytest.raises(RuntimeError):
        prov.record_undo(_undone_edit(_applied_edit()))

    with pytest.raises(RuntimeError):
        prov.record_interruption("paused")


def test_provenance_close_requires_open() -> None:
    prov = _make_provenance()

    with pytest.raises(RuntimeError):
        prov.close("done")
