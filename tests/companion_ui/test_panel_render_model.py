"""Tests for Panel render model / component shell (#1039).

Verifies:
- All 8 required Panel states are defined.
- Future-compatible states are named.
- Artifact-local anchoring is enforced.
- no-match and blocked are visible states with messages.
- State transitions are legal/illegal as expected.
- render_panel_state adapter produces sensible output per state.
- No dependency on Canvas Core or direct vault I/O.
"""

import pytest

from companion_ui.panel.render_model import (
    PANEL_STATES_REQUIRED,
    PANEL_STATES_FUTURE,
    PANEL_STATES_ALL,
    PanelRenderState,
    render_panel_state,
)


REQUIRED_STATES = [
    "idle",
    "running",
    "proposals-staged",
    "confirming",
    "executing",
    "receipt-displayed",
    "no-match",
    "blocked",
]

FUTURE_STATES = [
    "clarification-needed",
    "plan-staged",
    "capability-needed",
    "partial-complete",
]


class TestPanelStatesDefinition:
    def test_all_required_states_present(self) -> None:
        for state in REQUIRED_STATES:
            assert state in PANEL_STATES_REQUIRED, f"Required state missing: {state!r}"

    def test_future_compatible_states_present(self) -> None:
        for state in FUTURE_STATES:
            assert state in PANEL_STATES_FUTURE, f"Future state missing: {state!r}"

    def test_all_states_union(self) -> None:
        assert PANEL_STATES_REQUIRED.issubset(PANEL_STATES_ALL)
        assert PANEL_STATES_FUTURE.issubset(PANEL_STATES_ALL)


class TestPanelRenderStateArtifactAnchoring:
    def test_artifact_id_required(self) -> None:
        with pytest.raises(ValueError, match="artifact_id is required"):
            PanelRenderState(artifact_id="")

    def test_artifact_id_stored(self) -> None:
        s = PanelRenderState(artifact_id="note-123")
        assert s.artifact_id == "note-123"

    def test_default_state_is_idle(self) -> None:
        s = PanelRenderState(artifact_id="note-a")
        assert s.state == "idle"

    def test_unknown_state_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown Panel state"):
            PanelRenderState(artifact_id="note-a", state="nonexistent")


class TestPanelRenderStateTransitions:
    def test_idle_to_running(self) -> None:
        s = PanelRenderState(artifact_id="note-a")
        s.transition("running")
        assert s.state == "running"

    def test_running_to_proposals_staged(self) -> None:
        s = PanelRenderState(artifact_id="note-a")
        s.transition("running")
        s.transition("proposals-staged")
        assert s.state == "proposals-staged"

    def test_proposals_staged_to_confirming(self) -> None:
        s = PanelRenderState(artifact_id="note-a")
        s.transition("running")
        s.transition("proposals-staged")
        s.transition("confirming")
        assert s.state == "confirming"

    def test_confirming_to_executing(self) -> None:
        s = PanelRenderState(artifact_id="note-a")
        s.transition("running")
        s.transition("proposals-staged")
        s.transition("confirming")
        s.transition("executing")
        assert s.state == "executing"

    def test_executing_to_receipt_displayed(self) -> None:
        s = PanelRenderState(artifact_id="note-a")
        s.transition("running")
        s.transition("proposals-staged")
        s.transition("confirming")
        s.transition("executing")
        s.transition("receipt-displayed")
        assert s.state == "receipt-displayed"

    def test_receipt_displayed_to_idle(self) -> None:
        s = PanelRenderState(artifact_id="note-a")
        s.transition("running")
        s.transition("proposals-staged")
        s.transition("confirming")
        s.transition("executing")
        s.transition("receipt-displayed")
        s.transition("idle")
        assert s.state == "idle"

    def test_running_to_no_match(self) -> None:
        s = PanelRenderState(artifact_id="note-a")
        s.transition("running")
        s.transition("no-match")
        assert s.state == "no-match"

    def test_running_to_blocked(self) -> None:
        s = PanelRenderState(artifact_id="note-a")
        s.transition("running")
        s.transition("blocked")
        assert s.state == "blocked"

    def test_illegal_transition_raises(self) -> None:
        s = PanelRenderState(artifact_id="note-a")
        with pytest.raises(ValueError, match="Illegal Panel state transition"):
            s.transition("executing")  # idle → executing is illegal

    def test_unknown_target_state_raises(self) -> None:
        s = PanelRenderState(artifact_id="note-a")
        with pytest.raises(ValueError, match="Unknown Panel target state"):
            s.transition("bogus-state")

    def test_same_turn_generated_to_executed_not_direct_path(self) -> None:
        # There is no legal idle→executing transition.
        # Proposals must go through: running→proposals-staged→confirming→executing.
        s = PanelRenderState(artifact_id="note-a")
        with pytest.raises(ValueError, match="Illegal Panel state transition"):
            s.transition("executing")


class TestNoMatchAndBlockedVisibility:
    def test_no_match_is_visible_failure(self) -> None:
        s = PanelRenderState(artifact_id="note-a", state="no-match")
        assert s.is_visible_failure is True

    def test_blocked_is_visible_failure(self) -> None:
        s = PanelRenderState(artifact_id="note-a", state="blocked")
        assert s.is_visible_failure is True

    def test_no_match_carries_message(self) -> None:
        s = PanelRenderState(artifact_id="note-a", state="no-match", message="No lifecycle match found.")
        assert s.message == "No lifecycle match found."

    def test_blocked_carries_reason(self) -> None:
        s = PanelRenderState(artifact_id="note-a", state="blocked", message="WriteGuard denied: tag allowlist.")
        assert s.message == "WriteGuard denied: tag allowlist."

    def test_idle_is_not_visible_failure(self) -> None:
        s = PanelRenderState(artifact_id="note-a", state="idle")
        assert s.is_visible_failure is False


class TestRenderPanelStateAdapter:
    def test_idle_render(self) -> None:
        s = PanelRenderState(artifact_id="note-a", state="idle")
        out = render_panel_state(s)
        assert out["state"] == "idle"
        assert out["artifact_id"] == "note-a"
        assert out["visible"] is True

    def test_running_has_loading(self) -> None:
        s = PanelRenderState(artifact_id="note-a", state="running")
        out = render_panel_state(s)
        assert out.get("loading") is True

    def test_proposals_staged_includes_count(self) -> None:
        s = PanelRenderState(artifact_id="note-a", state="proposals-staged", proposal_count=3)
        out = render_panel_state(s)
        assert out["proposal_count"] == 3

    def test_no_match_render_has_message(self) -> None:
        s = PanelRenderState(artifact_id="note-a", state="no-match", message="No match.")
        out = render_panel_state(s)
        assert out["message"] == "No match."

    def test_blocked_render_has_message(self) -> None:
        s = PanelRenderState(artifact_id="note-a", state="blocked", message="Policy denied.")
        out = render_panel_state(s)
        assert out["message"] == "Policy denied."

    def test_no_canvas_core_dependency(self) -> None:
        import companion_ui.panel.render_model as mod
        src = open(mod.__file__).read()
        assert "canvas_core" not in src
        assert "canvas_suggestion_flow" not in src

    def test_no_vault_write_in_module(self) -> None:
        import companion_ui.panel.render_model as mod
        src = open(mod.__file__).read()
        assert "SessionLogWriter" not in src
        assert "WriteGuard" not in src

    @pytest.mark.parametrize("state", REQUIRED_STATES)
    def test_all_required_states_renderable(self, state: str) -> None:
        s = PanelRenderState(artifact_id="note-a", state=state)
        out = render_panel_state(s)
        assert out["state"] == state
        assert "label" in out
