"""Tests for Panel correction browser wiring (#1139)."""

from __future__ import annotations

from typing import Any

from companion_ui.workspace.real_note_workspace_dev_page import (
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)
from companion_ui.workspace.serve_dev_page import render_index_html


class _FakeClient:
    def __init__(
        self,
        payloads: list[dict[str, Any]],
        *,
        post_response: dict[str, Any] | None = None,
    ) -> None:
        self.payloads = payloads
        self.post_response = post_response or {
            "proposal_id": "proposal-1",
            "artifact_id": "art-1139",
            "status": "executed",
            "outcome": "success",
            "receipt": {"message": "corrected", "outcome": "success"},
            "idempotency_key": "server-key",
        }
        self.get_calls: list[tuple[str, dict[str, Any]]] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append((url, params))
        return self.payloads.pop(0)

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        self.post_calls.append((url, json))
        return self.post_response


def _workspace_payload() -> dict[str, Any]:
    return {
        "artifact": {
            "artifact_id": "art-1139",
            "note_path": "Notes/panel.md",
            "title": "Panel Note",
            "body": "# Panel Note\n\nBody.",
            "content_hash": "hash-1",
        },
        "canvas": {
            "session_id": None,
            "session_state": None,
            "user_present": False,
            "can_edit_body": False,
            "recovery_needed": False,
            "session_log_path": None,
            "undo_available": False,
            "applied_edit_count": 0,
            "undone_edit_count": 0,
            "session_persistence": "in_memory",
        },
        "panel": {
            "state": "proposals-staged",
            "proposal_count": 1,
            "proposals": [
                {
                    "proposal_id": "proposal-1",
                    "artifact_id": "art-1139",
                    "description": "Update status",
                    "status": "staged",
                    "affordances": {"confirm": True, "correct": True, "reject": True},
                }
            ],
        },
        "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
        "runtime": {},
        "suggestions": {},
    }


def _loaded_page(client: _FakeClient) -> RealNoteWorkspaceDevPage:
    page = RealNoteWorkspaceDevPage(client)  # type: ignore[arg-type]
    state = page.load(NoteLoadIntent(note_path="Notes/panel.md"))
    assert state.is_loaded is True
    return page


def _html(page: RealNoteWorkspaceDevPage) -> str:
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/panel.md",
        fields=fields,
    )


def test_correction_calls_api() -> None:
    client = _FakeClient([_workspace_payload(), _workspace_payload()])
    page = _loaded_page(client)

    page.correct_panel_proposal(
        proposal_id="proposal-1",
        artifact_id="art-1139",
        note_path="Notes/panel.md",
        corrected_action_id="proposal-1",
        corrected_parameters={"value": "evergreen"},
    )

    assert client.post_calls[0][0] == "/api/panel/confirm"
    payload = client.post_calls[0][1]
    assert payload["proposal_id"] == "proposal-1"
    assert payload["artifact_id"] == "art-1139"
    assert payload["action"] == "confirm"
    assert payload["idempotency_key"]
    assert payload["correction"] == {
        "enabled": True,
        "corrected_action_id": "proposal-1",
        "corrected_parameters": {"value": "evergreen"},
    }


def test_corrected_receipt_marked() -> None:
    client = _FakeClient([_workspace_payload(), _workspace_payload()])
    page = _loaded_page(client)
    page.correct_panel_proposal(
        proposal_id="proposal-1",
        artifact_id="art-1139",
        note_path="Notes/panel.md",
        corrected_action_id="proposal-1",
        corrected_parameters={"value": "evergreen"},
    )

    html = _html(page)

    assert 'data-testid="workspace-panel-corrected-receipt"' in html
    assert "corrected" in html


def test_invalid_correction_rejected() -> None:
    client = _FakeClient([_workspace_payload()])
    page = _loaded_page(client)

    state = page.correct_panel_proposal(
        proposal_id="proposal-1",
        artifact_id="art-1139",
        note_path="Notes/panel.md",
    )

    assert state.is_loaded is False
    assert "requires corrected_action_id or corrected_parameters" in (state.error or "")
    assert client.post_calls == []
