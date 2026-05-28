"""Tests for browser binding to the Canvas suggestion-flow state machine (#1132)."""

from __future__ import annotations

from typing import Any

from companion_ui.canvas_suggestion_flow.rail_state_machine import (
    CanvasRailStateMachine,
    RAIL_STATES,
)
from companion_ui.workspace.real_note_workspace_dev_page import (
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)
from companion_ui.workspace.serve_dev_page import render_index_html
from tests.companion_ui.vault_browser_test_helpers import (
    default_vault_browser_payload,
    is_vault_browser_get,
)


class _FakeClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        if is_vault_browser_get(url):
            return default_vault_browser_payload()
        assert url == "/api/companion/workspace"
        assert params == {"note_path": "Notes/suggestion.md"}
        return self.payload


def _workspace_payload(state: str) -> dict[str, Any]:
    return {
        "artifact": {
            "artifact_id": "art-1132",
            "note_path": "Notes/suggestion.md",
            "title": "Suggestion Note",
            "body": "# Suggestion Note\n\nBody.",
            "content_hash": "sha256-suggestion",
        },
        "canvas": {
            "session_id": "session-1",
            "session_state": "active",
            "user_present": True,
            "can_edit_body": True,
            "recovery_needed": False,
            "session_log_path": None,
            "session_persistence": "in_memory",
        },
        "panel": {"state": "idle", "proposal_count": 0},
        "suggestions": {"current_suggestion_state": state},
        "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
        "runtime": {},
    }


def _html_for_state(state: str) -> str:
    page = RealNoteWorkspaceDevPage(_FakeClient(_workspace_payload(state)))  # type: ignore[arg-type]
    loaded = page.load(NoteLoadIntent(note_path="Notes/suggestion.md"))
    assert loaded.is_loaded is True
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/suggestion.md",
        fields=fields,
    )


def test_all_states_render() -> None:
    for state in sorted(RAIL_STATES):
        html = _html_for_state(state)
        machine = CanvasRailStateMachine(state)

        assert 'data-testid="workspace-suggestion-flow"' in html
        assert f'data-suggestion-state="{state}"' in html
        assert f'data-suggestion-dom-alias="{machine.dom_alias}"' in html
        assert state in html


def test_illegal_transitions_blocked() -> None:
    state = "staged_governance"
    html = _html_for_state(state)
    allowed = CanvasRailStateMachine(state).allowed_transitions()

    assert 'data-transition-to="governance_pending"' in html
    assert 'data-transition-to="discarded"' in html
    assert 'data-transition-to="apply_pending"' not in html
    assert "apply_pending" not in allowed


def test_suggestion_state_attribute() -> None:
    html = _html_for_state("staged_body")

    assert 'data-testid="workspace-suggestion-flow"' in html
    assert 'data-suggestion-state="staged_body"' in html


def test_unknown_suggestion_state_falls_back_to_idle() -> None:
    html = _html_for_state("future_runtime_state")

    assert 'data-testid="workspace-suggestion-flow"' in html
    assert 'data-suggestion-state="idle"' in html
