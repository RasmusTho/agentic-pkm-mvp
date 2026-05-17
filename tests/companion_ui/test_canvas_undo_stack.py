"""Tests for Canvas Core undo stack (#1027).

Undo is the rollback path for direct body co-authoring edits in an active
Canvas session.  These tests verify session-scope, artifact-scope, provenance
preservation, and distinction from bounded-suggestion discard.

ACs from #1027:
- test_assistant_edits_recorded_in_undo_stack
- test_undo_reverts_latest_assistant_body_edit
- test_undo_is_session_scoped
- test_undo_is_artifact_scoped
- test_undo_preserves_provenance_marker
- test_undo_is_not_bounded_suggestion_discard
"""

import pytest

from companion_ui.canvas_core.active_artifact_shell import CanvasArtifactShell
from companion_ui.canvas_core.body_edit import AppliedEdit
from companion_ui.canvas_core.undo_stack import CanvasUndoStack, UndoDivergenceError, UndoneEdit

SESSION_ID = "session-undo-001"
OTHER_SESSION_ID = "session-other-999"
ARTIFACT_ID = "note-undo"
OTHER_ARTIFACT_ID = "note-other"


def _active_shell(artifact_id: str = ARTIFACT_ID, body: str = "original") -> CanvasArtifactShell:
    from companion_ui.canvas_core.session_state import CanvasSessionState

    _ = CanvasSessionState(artifact_id=artifact_id)
    return CanvasArtifactShell(
        artifact_id=artifact_id,
        artifact_title="Undo Test Note",
        body=body,
    )


def _make_edit(
    body_before: str = "before",
    body_after: str = "after",
    session_id: str = SESSION_ID,
    artifact_id: str = ARTIFACT_ID,
) -> AppliedEdit:
    return AppliedEdit(
        edit_id="edit-001",
        session_id=session_id,
        artifact_id=artifact_id,
        body_before=body_before,
        body_after=body_after,
        edit_summary="test edit",
        user_prompt="test prompt",
    )


# ---------------------------------------------------------------------------
# AC: assistant-applied body edits are recorded in an undo stack for the session
# ---------------------------------------------------------------------------


def test_assistant_edits_recorded_in_undo_stack() -> None:
    stack = CanvasUndoStack(session_id=SESSION_ID, artifact_id=ARTIFACT_ID)
    edit1 = _make_edit(body_before="v0", body_after="v1")
    edit2 = _make_edit(body_before="v1", body_after="v2")

    stack.push(edit1)
    stack.push(edit2)

    assert stack.can_undo
    assert len(stack.applied_edits) == 2
    assert stack.applied_edits[0].body_after == "v1"
    assert stack.applied_edits[1].body_after == "v2"


# ---------------------------------------------------------------------------
# AC: undo reverts the latest assistant-applied body edit for the active artifact
# ---------------------------------------------------------------------------


def test_undo_reverts_latest_assistant_body_edit() -> None:
    shell = _active_shell(body="v1")
    stack = CanvasUndoStack(session_id=SESSION_ID, artifact_id=ARTIFACT_ID)
    edit = _make_edit(body_before="original", body_after="v1")
    stack.push(edit)

    undone = stack.undo(shell)

    assert shell.body == "original", "Body must be reverted to pre-edit state"
    assert isinstance(undone, UndoneEdit)
    assert undone.original_edit is edit
    assert not stack.can_undo


def test_undo_reverts_latest_edit_when_multiple_pushed() -> None:
    shell = _active_shell(body="v2")
    stack = CanvasUndoStack(session_id=SESSION_ID, artifact_id=ARTIFACT_ID)

    edit1 = AppliedEdit(
        edit_id="e1", session_id=SESSION_ID, artifact_id=ARTIFACT_ID,
        body_before="v0", body_after="v1", edit_summary="", user_prompt="",
    )
    edit2 = AppliedEdit(
        edit_id="e2", session_id=SESSION_ID, artifact_id=ARTIFACT_ID,
        body_before="v1", body_after="v2", edit_summary="", user_prompt="",
    )
    stack.push(edit1)
    stack.push(edit2)

    undone = stack.undo(shell)
    assert shell.body == "v1"
    assert undone.original_edit.edit_id == "e2"
    assert stack.can_undo  # edit1 still present

    undone2 = stack.undo(shell)
    assert shell.body == "v0"
    assert undone2.original_edit.edit_id == "e1"
    assert not stack.can_undo


# ---------------------------------------------------------------------------
# AC: undo is scoped to active session and cannot undo edits from another session
# ---------------------------------------------------------------------------


def test_undo_is_session_scoped() -> None:
    stack = CanvasUndoStack(session_id=SESSION_ID, artifact_id=ARTIFACT_ID)
    foreign_edit = _make_edit(session_id=OTHER_SESSION_ID)

    with pytest.raises(ValueError, match="session_id"):
        stack.push(foreign_edit)


# ---------------------------------------------------------------------------
# AC: undo is scoped to active artifact and cannot affect another note/artifact
# ---------------------------------------------------------------------------


def test_undo_is_artifact_scoped() -> None:
    stack = CanvasUndoStack(session_id=SESSION_ID, artifact_id=ARTIFACT_ID)
    foreign_edit = _make_edit(artifact_id=OTHER_ARTIFACT_ID)

    with pytest.raises(ValueError, match="artifact_id"):
        stack.push(foreign_edit)


def test_undo_rejects_shell_from_different_artifact() -> None:
    stack = CanvasUndoStack(session_id=SESSION_ID, artifact_id=ARTIFACT_ID)
    stack.push(_make_edit())

    wrong_shell = _active_shell(artifact_id=OTHER_ARTIFACT_ID)
    with pytest.raises(ValueError, match="artifact_id"):
        stack.undo(wrong_shell)


def test_undo_raises_when_stack_empty() -> None:
    stack = CanvasUndoStack(session_id=SESSION_ID, artifact_id=ARTIFACT_ID)
    shell = _active_shell()

    with pytest.raises(IndexError):
        stack.undo(shell)


# ---------------------------------------------------------------------------
# AC: undo creates/marks provenance for an undone edit rather than deleting history
# ---------------------------------------------------------------------------


def test_undo_preserves_provenance_marker() -> None:
    shell = _active_shell(body="v1")
    stack = CanvasUndoStack(session_id=SESSION_ID, artifact_id=ARTIFACT_ID)
    edit = _make_edit(body_before="original", body_after="v1")
    stack.push(edit)

    undone = stack.undo(shell)

    assert undone in stack.undone_edits, "UndoneEdit must be in undone_edits list"
    assert undone.original_edit == edit, "Original edit must be preserved in UndoneEdit"
    assert undone.undo_id, "undo_id must be non-empty"
    assert undone.session_id == SESSION_ID
    assert undone.artifact_id == ARTIFACT_ID


# ---------------------------------------------------------------------------
# AC: undo is distinct from Canvas bounded suggestion discard
# ---------------------------------------------------------------------------


def test_undo_is_not_bounded_suggestion_discard() -> None:
    """Canvas Core undo stack must not couple to suggestion flow concepts."""
    import inspect
    from companion_ui.canvas_core import undo_stack as mod

    src = inspect.getsource(mod)
    assert "canvas_suggestion_flow" not in src
    assert "suggestion_flow" not in src
    # The module must not import or invoke bounded-suggestion discard logic.
    assert "SuggestionDiscard" not in src
    assert "discard_suggestion" not in src


# ---------------------------------------------------------------------------
# Review fix: undo surfaces conflict when body has diverged since assistant edit
# ---------------------------------------------------------------------------


def test_undo_raises_divergence_error_when_body_changed_after_edit() -> None:
    shell = _active_shell(body="v1")
    stack = CanvasUndoStack(session_id=SESSION_ID, artifact_id=ARTIFACT_ID)
    edit = _make_edit(body_before="original", body_after="v1")
    stack.push(edit)

    shell.body = "v1 plus user keystroke"

    with pytest.raises(UndoDivergenceError):
        stack.undo(shell)

    assert shell.body == "v1 plus user keystroke", "Body must not be mutated when undo diverges"
    assert stack.can_undo, "Edit must remain on stack after divergence error"


def test_undo_succeeds_when_body_matches_edit_after() -> None:
    shell = _active_shell(body="v1")
    stack = CanvasUndoStack(session_id=SESSION_ID, artifact_id=ARTIFACT_ID)
    edit = _make_edit(body_before="original", body_after="v1")
    stack.push(edit)

    undone = stack.undo(shell)

    assert shell.body == "original"
    assert isinstance(undone, UndoneEdit)
