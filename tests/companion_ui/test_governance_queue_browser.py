"""Tests for governance suggestion queue wiring in the workspace shell (#1135)."""

from __future__ import annotations

from typing import Any

from companion_ui.workspace.real_note_workspace_dev_page import (
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)
from companion_ui.workspace.serve_dev_page import render_index_html


class _FakeClient:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.get_calls: list[tuple[str, dict[str, Any]]] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        if url == "/api/companion/vault-browser":
            return {}  # infrastructure; not under test
        self.get_calls.append((url, params))
        return self.payloads.pop(0)

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        self.post_calls.append((url, json))
        return {
            "intent_id": "intent-1135",
            "session_id": "session-1",
            "artifact_id": "Notes/canvas.md",
        }


def _workspace_payload(*, suggestion_state: str = "staged_governance") -> dict[str, Any]:
    return {
        "artifact": {
            "artifact_id": "art-1135",
            "note_path": "Notes/canvas.md",
            "title": "Canvas Note",
            "body": "# Canvas Note\n\nBody.",
            "content_hash": "hash-1",
        },
        "canvas": {
            "session_id": "session-1",
            "session_state": "active",
            "user_present": True,
            "can_edit_body": True,
            "recovery_needed": False,
            "session_log_path": ".chats/canvas/session.md",
            "undo_available": False,
            "applied_edit_count": 0,
            "undone_edit_count": 0,
            "session_persistence": "in_memory",
        },
        "panel": {"state": "idle", "proposal_count": 0},
        "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
        "runtime": {},
        "suggestions": {
            "current_suggestion_state": suggestion_state,
            "proposals": [
                {
                    "suggestion_id": "s-gov",
                    "server_declared_classification": "governance",
                    "title": "Move note",
                    "summary": "Queue lifecycle update",
                    "preview_text": "lifecycle.move",
                    "action_type": "note_lifecycle",
                    "payload": {"target": "Projects/Active"},
                }
            ],
        },
    }


def _loaded_page(client: _FakeClient) -> RealNoteWorkspaceDevPage:
    page = RealNoteWorkspaceDevPage(client)  # type: ignore[arg-type]
    page.load(NoteLoadIntent(note_path="Notes/canvas.md"))
    return page


def test_governance_queue_calls_api() -> None:
    client = _FakeClient([
        _workspace_payload(),
        _workspace_payload(suggestion_state="governance_pending"),
    ])
    page = _loaded_page(client)

    state = page.queue_governance_suggestion(
        suggestion_id="s-gov",
        session_id="session-1",
        note_path="Notes/canvas.md",
    )

    assert state.is_loaded is True
    assert client.post_calls == [
        (
            "/api/canvas/sessions/session-1/governance",
            {
                "action_type": "note_lifecycle",
                "payload": {"target": "Projects/Active"},
            },
        ),
    ]
    assert all(url != "/api/canvas/sessions/session-1/edits" for url, _ in client.post_calls)


def test_governance_pending_state_transition() -> None:
    client = _FakeClient([
        _workspace_payload(),
        _workspace_payload(suggestion_state="governance_pending"),
    ])
    page = _loaded_page(client)

    state = page.queue_governance_suggestion(
        suggestion_id="s-gov",
        session_id="session-1",
        note_path="Notes/canvas.md",
    )

    fields = page.render_fields()
    assert state.suggestion_state == "idle"
    assert fields is not None
    assert fields["governance_pending_transition_path"] == [
        "staged_governance",
        "governance_pending",
        "idle",
    ]


def test_receipt_pill_rendered() -> None:
    client = _FakeClient([
        _workspace_payload(),
        _workspace_payload(suggestion_state="governance_pending"),
    ])
    page = _loaded_page(client)

    state = page.queue_governance_suggestion(
        suggestion_id="s-gov",
        session_id="session-1",
        note_path="Notes/canvas.md",
    )

    fields = page.render_fields()
    assert state.governance_receipts is not None
    assert fields is not None
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/canvas.md",
        fields=fields,
    )
    assert 'data-testid="receipt-pill"' in html
    assert 'data-receipt-id="intent-1135"' in html
    assert 'data-intent="governance.openReceipt"' in html
