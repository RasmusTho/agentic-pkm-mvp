"""Tests for body suggestion apply wiring in the workspace shell (#1134)."""

from __future__ import annotations

from typing import Any

from companion_ui.workspace.real_note_workspace_dev_page import (
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)


class _FakeClient:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.get_calls: list[tuple[str, dict[str, Any]]] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append((url, params))
        return self.payloads.pop(0)

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        self.post_calls.append((url, json))
        return {"session_id": "session-1", "ok": True}


def _workspace_payload(
    *,
    body: str = "# Canvas Note\n\nBody.",
    content_hash: str = "hash-1",
    suggestion_state: str = "staged_body",
) -> dict[str, Any]:
    return {
        "artifact": {
            "artifact_id": "art-1134",
            "note_path": "Notes/canvas.md",
            "title": "Canvas Note",
            "body": body,
            "content_hash": content_hash,
        },
        "canvas": {
            "session_id": "session-1",
            "session_state": "active",
            "user_present": True,
            "can_edit_body": True,
            "recovery_needed": False,
            "session_log_path": ".chats/canvas/session.md",
            "undo_available": False,
            "applied_edit_count": 1 if content_hash == "hash-2" else 0,
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
                    "suggestion_id": "s-body",
                    "server_declared_classification": "body",
                    "title": "Add bridge paragraph",
                    "preview_text": "Bridge preview",
                    "anchor_description": "after intro",
                    "proposed_text": "# Canvas Note\n\nBody.\n\nBridge text.",
                }
            ],
        },
    }


def _loaded_page(client: _FakeClient) -> RealNoteWorkspaceDevPage:
    page = RealNoteWorkspaceDevPage(client)  # type: ignore[arg-type]
    page.load(NoteLoadIntent(note_path="Notes/canvas.md"))
    return page


def test_body_apply_calls_canvas_api() -> None:
    client = _FakeClient([
        _workspace_payload(content_hash="hash-1"),
        _workspace_payload(
            body="# Canvas Note\n\nBody.\n\nBridge text.",
            content_hash="hash-2",
            suggestion_state="idle",
        ),
    ])
    page = _loaded_page(client)

    state = page.apply_body_suggestion(
        suggestion_id="s-body",
        session_id="session-1",
        note_path="Notes/canvas.md",
    )

    assert state.is_loaded is True
    assert client.post_calls == [
        (
            "/api/canvas/sessions/session-1/edits",
            {
                "new_body": "# Canvas Note\n\nBody.\n\nBridge text.",
                "change_summary": "Applied body suggestion s-body",
                "content_hash": "hash-1",
            },
        ),
    ]
    assert client.get_calls == [
        ("/api/companion/workspace", {"note_path": "Notes/canvas.md"}),
        ("/api/companion/workspace", {"note_path": "Notes/canvas.md"}),
    ]


def test_body_apply_state_transition() -> None:
    client = _FakeClient([
        _workspace_payload(content_hash="hash-1"),
        _workspace_payload(content_hash="hash-2", suggestion_state="idle"),
    ])
    page = _loaded_page(client)

    state = page.apply_body_suggestion(
        suggestion_id="s-body",
        session_id="session-1",
        note_path="Notes/canvas.md",
    )

    fields = page.render_fields()
    assert state.suggestion_state == "idle"
    assert fields is not None
    assert fields["suggestion_apply_transition_path"] == [
        "staged_body",
        "apply_pending",
        "applied",
        "idle",
    ]
    assert fields["suggestion_composer_enabled"] is True


def test_no_panel_receipt_for_body_edit() -> None:
    client = _FakeClient([
        _workspace_payload(content_hash="hash-1"),
        _workspace_payload(content_hash="hash-2", suggestion_state="idle"),
    ])
    page = _loaded_page(client)

    state = page.apply_body_suggestion(
        suggestion_id="s-body",
        session_id="session-1",
        note_path="Notes/canvas.md",
    )

    fields = page.render_fields()
    assert state.panel_last_response is None
    assert fields is not None
    assert fields["panel_last_response"] == {}
    assert all(url != "/api/panel/confirm" for url, _payload in client.post_calls)
