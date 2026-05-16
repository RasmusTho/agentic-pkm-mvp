"""Tests for Canvas Core session lifecycle state (#1024).

Canvas Core is direct in-place co-authoring of the active note body during a
user-present session.  These tests verify the state machine, legal transitions,
and body-edit authority rules.
"""

from pathlib import Path
import importlib.util
import pytest


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "companion-ui" / "companion-app" / "canvas_core_state.py"
    spec = importlib.util.spec_from_file_location("canvas_core_state", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_canvas_session_states_defined() -> None:
    m = _load_module()
    assert "start" in m.CANVAS_SESSION_STATES
    assert "active" in m.CANVAS_SESSION_STATES
    assert "paused" in m.CANVAS_SESSION_STATES
    assert "interrupted" in m.CANVAS_SESSION_STATES
    assert "closed" in m.CANVAS_SESSION_STATES


def test_canvas_session_legal_transitions() -> None:
    m = _load_module()

    # start → active
    s = m.CanvasSessionState(artifact_id="note-a")
    s.transition("active")
    assert s.state == "active"

    # active → paused
    s.transition("paused")
    assert s.state == "paused"

    # paused → active
    s.transition("active")
    assert s.state == "active"

    # active → interrupted
    s.transition("interrupted")
    assert s.state == "interrupted"

    # interrupted → active
    s.transition("active")
    assert s.state == "active"

    # active → closed
    s.transition("closed")
    assert s.state == "closed"


def test_canvas_session_legal_transitions_paused_to_closed() -> None:
    m = _load_module()
    s = m.CanvasSessionState(artifact_id="note-b")
    s.transition("active")
    s.transition("paused")
    s.transition("closed")
    assert s.is_closed


def test_canvas_session_illegal_transition_raises() -> None:
    m = _load_module()

    # start cannot jump to closed directly
    s = m.CanvasSessionState(artifact_id="note-c")
    with pytest.raises(ValueError, match="Illegal Canvas session transition"):
        s.transition("closed")

    # closed is terminal
    s2 = m.CanvasSessionState(artifact_id="note-d")
    s2.transition("active")
    s2.transition("closed")
    with pytest.raises(ValueError, match="Illegal Canvas session transition"):
        s2.transition("active")


def test_body_edits_allowed_only_when_active() -> None:
    m = _load_module()
    s = m.CanvasSessionState(artifact_id="note-e")

    assert not s.body_edits_allowed  # start

    s.transition("active")
    assert s.body_edits_allowed  # active — user-present authority granted


def test_paused_session_blocks_new_edits() -> None:
    m = _load_module()
    s = m.CanvasSessionState(artifact_id="note-f")
    s.transition("active")
    s.transition("paused")

    assert not s.body_edits_allowed
    assert s.recovery_needed

    with pytest.raises(PermissionError):
        s.assert_body_edit_allowed()


def test_interrupted_session_blocks_new_edits() -> None:
    m = _load_module()
    s = m.CanvasSessionState(artifact_id="note-g")
    s.transition("active")
    s.transition("interrupted")

    assert not s.body_edits_allowed
    assert s.recovery_needed

    with pytest.raises(PermissionError):
        s.assert_body_edit_allowed()


def test_closed_session_rejects_edits() -> None:
    m = _load_module()
    s = m.CanvasSessionState(artifact_id="note-h")
    s.transition("active")
    s.transition("closed")

    assert not s.body_edits_allowed
    assert not s.recovery_needed
    assert s.is_closed

    with pytest.raises(PermissionError):
        s.assert_body_edit_allowed()


def test_canvas_core_state_is_not_suggestion_flow_state() -> None:
    """Canvas Core state machine must not reference suggestion flow states."""
    m = _load_module()
    assert "suggestion" not in m.CANVAS_SESSION_STATES
    assert "proposed" not in m.CANVAS_SESSION_STATES
    assert "review" not in m.CANVAS_SESSION_STATES
    # Core module must not import canvas_suggestion_flow
    import inspect
    src = inspect.getsource(m)
    assert "canvas_suggestion_flow" not in src
    assert "suggestion_flow" not in src
