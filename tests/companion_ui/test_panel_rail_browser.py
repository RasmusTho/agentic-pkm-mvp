"""Tests for live Panel state binding in the Companion workspace rail (#1137)."""

from __future__ import annotations

from typing import Any

from companion_ui.panel.render_model import PANEL_STATES_REQUIRED
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
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((url, params))
        if is_vault_browser_get(url):
            return default_vault_browser_payload()
        return self.payload


def _workspace_payload(panel: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact": {
            "artifact_id": "art-1137",
            "note_path": "Notes/panel.md",
            "title": "Panel Note",
            "body": "# Panel Note\n\nBody.",
            "content_hash": "sha256-panel",
        },
        "canvas": {"session_state": "idle", "session_persistence": "in_memory"},
        "panel": panel,
        "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
        "runtime": {},
        "suggestions": {},
    }


def _html_for_panel(panel: dict[str, Any]) -> str:
    client = _FakeClient(_workspace_payload(panel))
    page = RealNoteWorkspaceDevPage(client)  # type: ignore[arg-type]
    state = page.load(NoteLoadIntent(note_path="Notes/panel.md"))
    assert state.is_loaded is True
    workspace_get_calls = [
        call for call in client.calls if call[0] == "/api/companion/workspace"
    ]
    assert workspace_get_calls == [
        ("/api/companion/workspace", {"note_path": "Notes/panel.md"}),
    ]
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/panel.md",
        fields=fields,
    )


def test_all_panel_states_render() -> None:
    for state in sorted(PANEL_STATES_REQUIRED):
        panel: dict[str, Any] = {"state": state, "proposal_count": 0}
        if state == "proposals-staged":
            panel["proposal_count"] = 1
        if state == "blocked":
            panel["blocked_reason"] = "WriteGuard blocked this action."
        if state == "no-match":
            panel["no_match_reason"] = "No actionable proposals were found."

        html = _html_for_panel(panel)

        assert 'data-testid="workspace-panel-state"' in html
        assert state in html
        assert 'data-testid="workspace-panel-label"' in html


def test_proposal_rows_rendered() -> None:
    html = _html_for_panel({
        "state": "proposals-staged",
        "proposal_count": 2,
        "proposals": [
            {
                "proposal_id": "prop-1",
                "description": "Move note to Projects",
                "status": "staged",
                "evidence": {
                    "trigger_summary": "Project tag detected",
                    "action_class": "lifecycle.move",
                    "cognition_route": "rule",
                },
                "affordances": {"confirm": True, "correct": True, "reject": True},
            },
            {
                "proposal_id": "prop-2",
                "description": "Add follow-up reminder",
                "status": "staged",
                "evidence": {
                    "trigger_summary": "Contains commitment language",
                    "action_class": "followup.create",
                    "cognition_route": "freeform",
                },
                "affordances": ["confirm", "reject"],
            },
        ],
    })

    assert html.count('data-testid="workspace-panel-proposal-row"') == 2
    assert "Move note to Projects" in html
    assert "Add follow-up reminder" in html
    assert "Project tag detected" in html
    assert "lifecycle.move" in html
    assert "freeform" in html


def test_blocked_reason_visible() -> None:
    html = _html_for_panel({
        "state": "blocked",
        "proposal_count": 0,
        "blocked_reason": "WriteGuard blocked execution in dev.",
    })

    assert 'data-testid="workspace-panel-message"' in html
    assert "WriteGuard blocked execution in dev." in html


def test_no_match_reason_visible() -> None:
    html = _html_for_panel({
        "state": "no-match",
        "proposal_count": 0,
        "no_match_reason": "Panel found no matching catalog action.",
    })

    assert 'data-testid="workspace-panel-message"' in html
    assert "Panel found no matching catalog action." in html
