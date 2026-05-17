"""Tests for Canvas Core direct body-edit apply path (#1026).

Canvas Core is direct in-place co-authoring of the active note body during a
user-present session.  These tests verify the body-edit apply path, governance
blocking, and metadata recording.

ACs from #1026:
- test_assistant_body_edit_applies_when_session_active
- test_body_edit_rejected_when_session_not_active
- test_body_edit_records_undo_and_provenance_metadata
- test_body_edit_does_not_create_governance_receipt
- test_governance_bearing_edit_is_not_applied_directly
- test_direct_body_edit_is_not_bounded_suggestion_flow
"""

import pytest

from companion_ui.canvas_core.active_artifact_shell import CanvasArtifactShell
from companion_ui.canvas_core.body_edit import (
    GOVERNANCE_BEARING_EDIT_CLASSES,
    AppliedEdit,
    BodyEditRequest,
    CanvasBodyEditor,
    GovernanceBearingEditError,
)
from companion_ui.canvas_core.session_state import CanvasSessionState

SESSION_ID = "test-session-001"
ARTIFACT_ID = "note-test"


def _active_shell() -> CanvasArtifactShell:
    return CanvasArtifactShell(
        artifact_id=ARTIFACT_ID,
        artifact_title="Test Note",
        body="original body",
    )


def _active_session() -> CanvasSessionState:
    s = CanvasSessionState(artifact_id=ARTIFACT_ID)
    s.transition("active")
    return s


# ---------------------------------------------------------------------------
# AC: assistant body edit applies when session is active and user-present
# ---------------------------------------------------------------------------


def test_assistant_body_edit_applies_when_session_active() -> None:
    shell = _active_shell()
    session = _active_session()
    editor = CanvasBodyEditor()

    request = BodyEditRequest(
        artifact_id=ARTIFACT_ID,
        new_body="updated body",
        edit_summary="Rewrote intro",
        user_prompt="Can you rewrite the intro?",
    )
    result = editor.apply_edit(shell, session, request, session_id=SESSION_ID)

    assert shell.body == "updated body"
    assert isinstance(result, AppliedEdit)
    assert result.body_after == "updated body"
    assert result.artifact_id == ARTIFACT_ID


# ---------------------------------------------------------------------------
# AC: body edit is rejected when session is not active or user-present
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("initial_state", ["start", "paused", "interrupted", "closed"])
def test_body_edit_rejected_when_session_not_active(initial_state: str) -> None:
    shell = _active_shell()
    editor = CanvasBodyEditor()
    request = BodyEditRequest(artifact_id=ARTIFACT_ID, new_body="should not apply")

    s = CanvasSessionState(artifact_id=ARTIFACT_ID, initial_state="start")
    if initial_state in ("paused", "interrupted"):
        s.transition("active")
        s.transition(initial_state)
    elif initial_state == "closed":
        s.transition("active")
        s.transition("closed")
    # "start" is already the initial state

    with pytest.raises(PermissionError):
        editor.apply_edit(shell, s, request, session_id=SESSION_ID)

    assert shell.body == "original body", "Body must not be mutated on rejected edit"


# ---------------------------------------------------------------------------
# AC: applied body edit records edit id / metadata sufficient for undo and provenance
# ---------------------------------------------------------------------------


def test_body_edit_records_undo_and_provenance_metadata() -> None:
    shell = _active_shell()
    session = _active_session()
    editor = CanvasBodyEditor()

    request = BodyEditRequest(
        artifact_id=ARTIFACT_ID,
        new_body="new content",
        edit_summary="Added conclusion",
        user_prompt="Add a conclusion section",
    )
    result = editor.apply_edit(shell, session, request, session_id=SESSION_ID)

    assert result.edit_id, "edit_id must be non-empty"
    assert result.session_id == SESSION_ID
    assert result.artifact_id == ARTIFACT_ID
    assert result.body_before == "original body"
    assert result.body_after == "new content"
    assert result.edit_summary == "Added conclusion"
    assert result.user_prompt == "Add a conclusion section"


# ---------------------------------------------------------------------------
# AC: body edit path does not create Panel/governance receipt
# ---------------------------------------------------------------------------


def test_body_edit_does_not_create_governance_receipt() -> None:
    shell = _active_shell()
    session = _active_session()
    editor = CanvasBodyEditor()

    request = BodyEditRequest(artifact_id=ARTIFACT_ID, new_body="new body")
    result = editor.apply_edit(shell, session, request, session_id=SESSION_ID)

    # The result is a plain AppliedEdit dataclass with no receipt fields.
    assert isinstance(result, AppliedEdit)
    assert not hasattr(result, "receipt")
    assert not hasattr(result, "governance_receipt")
    assert not hasattr(result, "panel_receipt")


# ---------------------------------------------------------------------------
# AC: governance-bearing edit requests are rejected, not applied directly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "edit_class",
    sorted(GOVERNANCE_BEARING_EDIT_CLASSES),
)
def test_governance_bearing_edit_is_not_applied_directly(edit_class: str) -> None:
    shell = _active_shell()
    session = _active_session()
    editor = CanvasBodyEditor()

    request = BodyEditRequest(
        artifact_id=ARTIFACT_ID,
        new_body="governance mutation attempt",
        edit_class=edit_class,
    )
    with pytest.raises(GovernanceBearingEditError):
        editor.apply_edit(shell, session, request, session_id=SESSION_ID)

    assert shell.body == "original body", "Body must not be mutated on governance-bearing edit"


# ---------------------------------------------------------------------------
# AC: direct body-edit path is separate from Canvas bounded suggestion apply path
# ---------------------------------------------------------------------------


def test_direct_body_edit_is_not_bounded_suggestion_flow() -> None:
    """Canvas Core body-edit path must not reference suggestion flow concepts."""
    import inspect
    from companion_ui.canvas_core import body_edit as mod

    src = inspect.getsource(mod)
    assert "canvas_suggestion_flow" not in src
    assert "suggestion_flow" not in src
    assert "staged_body" not in src
    assert "staged_governance" not in src
    assert "GovernanceBearingEditError" in src
    assert "GOVERNANCE_BEARING_EDIT_CLASSES" in src
