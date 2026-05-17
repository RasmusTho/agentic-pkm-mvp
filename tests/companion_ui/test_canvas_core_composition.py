"""Thin Canvas Core composition demo — module-level, not production UI.

Proves that the seven Canvas Core MVP helpers compose into one coherent flow:
  CanvasArtifactShell → CanvasSessionState → CanvasBodyEditor
  → CanvasSessionProvenance (fake writer) → CanvasUndoStack
  → CanvasEscapeHatchRouter → CanvasSessionRecovery

This test is intentionally self-contained and uses only in-memory fakes.
It does NOT wire backend APIs, real vault write paths, runtime startup,
watcher, Panel UI, or Canvas bounded suggestion UI.

Surface boundary: Canvas Core only.
  Not Panel (#1019/#995/#996).
  Not Canvas bounded suggestion flow (#868–#874).
  canvas_suggestion_flow.html is never imported or referenced.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from companion_ui.canvas_core.active_artifact_shell import CanvasArtifactShell
from companion_ui.canvas_core.body_edit import (
    BodyEditRequest,
    CanvasBodyEditor,
    GovernanceBearingEditError,
)
from companion_ui.canvas_core.escape_hatch import CanvasEscapeHatchRouter
from companion_ui.canvas_core.session_provenance import CanvasSessionProvenance
from companion_ui.canvas_core.session_recovery import (
    CanvasSessionRecovery,
    RecoveryStatus,
)
from companion_ui.canvas_core.session_state import CanvasSessionState
from companion_ui.canvas_core.undo_stack import CanvasUndoStack

# ---------------------------------------------------------------------------
# Fake in-memory provenance writer — no real vault I/O.
# ---------------------------------------------------------------------------

SESSION_ID = "session-compose-001"
ARTIFACT_ID = "note-compose-abc"
NOTE_PATH = Path("vault/notes/compose-demo.md")


class _FakeProvenanceSession:
    """In-memory stand-in for app.chat.session_log.SessionLog."""

    def __init__(self, note_path: Path, label: str) -> None:
        self.log_path = Path(".chats") / note_path.stem / f"{label}.md"
        self.session_id = SESSION_ID
        self.turns: list[dict[str, str]] = []
        self.closed_with: str | None = None


class FakeProvenanceWriter:
    """In-memory ProvenanceWriter — structurally matches the ProvenanceWriter protocol."""

    def __init__(self) -> None:
        self.sessions: list[_FakeProvenanceSession] = []

    def open_session(self, note_path: Path, session_label: str) -> _FakeProvenanceSession:
        session = _FakeProvenanceSession(note_path, session_label)
        self.sessions.append(session)
        return session

    def append_turn(self, session: Any, user_prompt: str, change_summary: str) -> None:
        session.turns.append({"user_prompt": user_prompt, "change_summary": change_summary})

    def close_session(self, session: Any, total_summary: str) -> None:
        session.closed_with = total_summary


# ---------------------------------------------------------------------------
# Composition test
# ---------------------------------------------------------------------------


class TestCanvasCoreComposition:
    """Full module-level composition exercising all seven Canvas Core helpers."""

    def test_full_composition_flow(self) -> None:
        """Prove the Canvas Core MVP modules compose into one coherent flow.

        Steps exercised (in order):
        1.  Create CanvasArtifactShell with initial body "original".
        2.  Create CanvasSessionState and transition to active.
        3.  Open CanvasSessionProvenance via fake in-memory writer.
        4.  Apply a direct body edit ("original" → "updated") via CanvasBodyEditor.
        5.  Record the edit in provenance.
        6.  Push the edit onto CanvasUndoStack.
        7.  Undo the edit; verify body returns to "original".
        8.  Record the undo in provenance.
        9.  Route a governance-bearing class ("lifecycle") through CanvasEscapeHatchRouter;
            verify it is not applied as a direct body edit.
        10. Transition session to paused; capture CanvasSessionRecovery payload.
        11. Simulate external body change; verify CONFLICT_DETECTED re-entry state.
        12. Assert canvas_suggestion_flow is never imported or invoked.
        """

        # 1. Create artifact shell
        shell = CanvasArtifactShell(
            artifact_id=ARTIFACT_ID,
            artifact_title="Compose Demo Note",
            body="original",
        )
        assert shell.body == "original"
        assert shell.portrait_artifact_anchor is True

        # 2. Create session and transition to active
        session = CanvasSessionState(artifact_id=ARTIFACT_ID)
        assert session.state == "start"
        assert not session.body_edits_allowed

        session.transition("active")
        assert session.state == "active"
        assert session.body_edits_allowed

        # 3. Open provenance via fake writer
        writer = FakeProvenanceWriter()
        prov = CanvasSessionProvenance(
            writer=writer,
            note_path=NOTE_PATH,
            session_label="compose-demo",
        )
        assert prov.session_log_path is None
        prov.open()
        assert prov.session_log_path is not None
        assert len(writer.sessions) == 1

        # 4. Apply direct body edit
        editor = CanvasBodyEditor()
        request = BodyEditRequest(
            artifact_id=ARTIFACT_ID,
            new_body="updated",
            edit_class="body",
            edit_summary="demo edit: original → updated",
            user_prompt="please update the intro",
        )
        applied = editor.apply_edit(shell, session, request, session_id=SESSION_ID)

        assert shell.body == "updated"
        assert applied.body_before == "original"
        assert applied.body_after == "updated"
        assert applied.artifact_id == ARTIFACT_ID
        assert applied.session_id == SESSION_ID

        # 5. Record edit in provenance
        prov.record_edit(applied)
        turns = writer.sessions[0].turns
        assert len(turns) == 1
        assert "edit:" in turns[0]["change_summary"]

        # 6. Push edit onto undo stack
        undo_stack = CanvasUndoStack(session_id=SESSION_ID, artifact_id=ARTIFACT_ID)
        undo_stack.push(applied)
        assert undo_stack.can_undo
        assert len(undo_stack.applied_edits) == 1

        # 7. Undo edit; verify body reverts to "original"
        undone = undo_stack.undo(shell)
        assert shell.body == "original"
        assert not undo_stack.can_undo
        assert len(undo_stack.undone_edits) == 1
        assert undone.original_edit.edit_id == applied.edit_id

        # 8. Record undo in provenance
        prov.record_undo(undone)
        assert len(writer.sessions[0].turns) == 2
        assert "undo:" in writer.sessions[0].turns[1]["change_summary"]

        # 9. Route governance-bearing class through escape hatch — not a direct body edit
        router = CanvasEscapeHatchRouter()

        # "lifecycle" must not go through the direct body-edit path
        lifecycle_result = router.route("lifecycle")
        assert lifecycle_result.is_governance_bearing is True
        assert lifecycle_result.route_target == "panel"

        # Attempt to apply "lifecycle" via CanvasBodyEditor must raise
        with pytest.raises(GovernanceBearingEditError):
            editor.apply_edit(
                shell,
                session,
                BodyEditRequest(
                    artifact_id=ARTIFACT_ID,
                    new_body="governed body",
                    edit_class="lifecycle",
                ),
                session_id=SESSION_ID,
            )
        # Body must be unchanged after the blocked attempt
        assert shell.body == "original"

        # "system_artifact" routes to governed_execution, not direct body edit
        sysart_result = router.route("system_artifact")
        assert sysart_result.is_governance_bearing is True
        assert sysart_result.route_target == "governed_execution"

        # "body" class is safe (sanity check)
        body_result = router.route("body")
        assert body_result.is_governance_bearing is False
        assert body_result.route_target == "none"

        # 10. Transition to paused; capture recovery payload
        prov.record_interruption("paused")
        session.transition("paused")
        assert session.recovery_needed is True
        assert not session.body_edits_allowed

        recovery = CanvasSessionRecovery()
        payload = recovery.capture(
            session_id=SESSION_ID,
            artifact_id=ARTIFACT_ID,
            body=shell.body,
            session_log_path=prov.session_log_path,
            applied_edit_count=len(undo_stack.applied_edits),
        )

        assert payload.session_id == SESSION_ID
        assert payload.artifact_id == ARTIFACT_ID
        assert payload.session_log_path == prov.session_log_path
        assert payload.pending_edit_count == 0
        assert recovery.blocks_new_edits is True
        assert recovery.reentry_state == "needs_review"

        # 11. Simulate external body change; verify CONFLICT_DETECTED
        external_body = "externally modified body"
        status = recovery.check_for_conflict(external_body)
        assert status == RecoveryStatus.CONFLICT_DETECTED
        assert recovery.reentry_state == "conflict_detected"
        assert recovery.blocks_new_edits is True

        # After mark_recovered, normal co-authoring may resume
        recovery.mark_recovered()
        assert recovery.reentry_state == "recovered"
        assert recovery.blocks_new_edits is False

        # 12. canvas_core source files must not reference canvas_suggestion_flow.
        # Checking sys.modules is unreliable in a shared test session because
        # other test modules import canvas_suggestion_flow during collection.
        # Source-file inspection is the correct check for the stated invariant.
        import pathlib
        canvas_core_dir = pathlib.Path(__file__).resolve().parents[2] / \
            "companion-ui" / "companion-app" / "companion_ui" / "canvas_core"
        for src_file in canvas_core_dir.glob("*.py"):
            content = src_file.read_text()
            assert "canvas_suggestion_flow" not in content, (
                f"{src_file.name} references canvas_suggestion_flow — this violates "
                "the Canvas Core surface boundary."
            )

    def test_governance_bearing_edit_classes_are_routed(self) -> None:
        """Every known governance-bearing class routes away from the direct edit path."""
        from companion_ui.canvas_core.body_edit import GOVERNANCE_BEARING_EDIT_CLASSES

        router = CanvasEscapeHatchRouter()
        shell = CanvasArtifactShell(
            artifact_id=ARTIFACT_ID,
            artifact_title="Escape Hatch Routing Note",
            body="stable body",
        )
        session = CanvasSessionState(artifact_id=ARTIFACT_ID)
        session.transition("active")
        editor = CanvasBodyEditor()

        for edit_class in GOVERNANCE_BEARING_EDIT_CLASSES:
            result = router.route(edit_class)
            assert result.is_governance_bearing, (
                f"Expected {edit_class!r} to be governance-bearing"
            )
            assert result.route_target != "none", (
                f"Expected {edit_class!r} to have a non-trivial route"
            )
            with pytest.raises(GovernanceBearingEditError):
                editor.apply_edit(
                    shell,
                    session,
                    BodyEditRequest(
                        artifact_id=ARTIFACT_ID,
                        new_body="should not apply",
                        edit_class=edit_class,
                    ),
                    session_id=SESSION_ID,
                )
            assert shell.body == "stable body", (
                f"Body must not change after blocked {edit_class!r} edit"
            )

    def test_session_not_active_blocks_body_edit(self) -> None:
        """Body edits are blocked when the session is not active."""
        shell = CanvasArtifactShell(
            artifact_id=ARTIFACT_ID,
            artifact_title="Permission Gate Note",
            body="locked body",
        )
        session = CanvasSessionState(artifact_id=ARTIFACT_ID)
        # session is in "start" state — edits must be blocked
        editor = CanvasBodyEditor()

        with pytest.raises(PermissionError):
            editor.apply_edit(
                shell,
                session,
                BodyEditRequest(
                    artifact_id=ARTIFACT_ID,
                    new_body="should not apply",
                    edit_class="body",
                ),
                session_id=SESSION_ID,
            )
        assert shell.body == "locked body"

    def test_provenance_records_composition_trace(self) -> None:
        """Provenance writer captures the full edit + undo + interruption trail."""
        writer = FakeProvenanceWriter()
        prov = CanvasSessionProvenance(
            writer=writer,
            note_path=NOTE_PATH,
            session_label="trace-demo",
        )
        prov.open()

        shell = CanvasArtifactShell(
            artifact_id=ARTIFACT_ID,
            artifact_title="Provenance Trace Note",
            body="v0",
        )
        session = CanvasSessionState(artifact_id=ARTIFACT_ID)
        session.transition("active")

        editor = CanvasBodyEditor()
        undo_stack = CanvasUndoStack(session_id=SESSION_ID, artifact_id=ARTIFACT_ID)

        edit1 = editor.apply_edit(
            shell, session,
            BodyEditRequest(ARTIFACT_ID, "v1", edit_summary="first edit"),
            session_id=SESSION_ID,
        )
        prov.record_edit(edit1)
        undo_stack.push(edit1)

        edit2 = editor.apply_edit(
            shell, session,
            BodyEditRequest(ARTIFACT_ID, "v2", edit_summary="second edit"),
            session_id=SESSION_ID,
        )
        prov.record_edit(edit2)
        undo_stack.push(edit2)

        undone = undo_stack.undo(shell)
        prov.record_undo(undone)

        prov.record_interruption("paused")
        prov.close("session total: 2 edits, 1 undo")

        fake_session = writer.sessions[0]
        # edit1, edit2, undo-of-edit2, interruption → 4 turns
        assert len(fake_session.turns) == 4
        assert fake_session.closed_with == "session total: 2 edits, 1 undo"
        assert shell.body == "v1"  # edit2 undone, edit1 applied
