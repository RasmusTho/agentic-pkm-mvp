"""Tests for Canvas direct body-edit apply in the workspace shell (#1129)."""

from __future__ import annotations

from typing import Any

from companion_ui.workspace.real_note_workspace_dev_page import (
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)
from companion_ui.workspace.workspace_http_client import WorkspaceClientHTTPError


class _FakeClient:
    def __init__(
        self,
        payloads: list[dict[str, Any]],
        *,
        post_error: Exception | None = None,
    ) -> None:
        self.payloads = payloads
        self.post_error = post_error
        self.get_calls: list[tuple[str, dict[str, Any]]] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append((url, params))
        return self.payloads.pop(0)

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        self.post_calls.append((url, json))
        if self.post_error is not None:
            raise self.post_error
        return {"session_id": "session-1", "ok": True}


def _workspace_payload(
    *,
    body: str = "# Canvas Note\n\nBody.",
    content_hash: str = "hash-1",
    can_edit_body: bool = True,
) -> dict[str, Any]:
    return {
        "artifact": {
            "artifact_id": "art-1129",
            "note_path": "Notes/canvas.md",
            "title": "Canvas Note",
            "body": body,
            "content_hash": content_hash,
        },
        "canvas": {
            "session_id": "session-1",
            "session_state": "active" if can_edit_body else "idle",
            "user_present": can_edit_body,
            "can_edit_body": can_edit_body,
            "recovery_needed": False,
            "session_log_path": None,
            "session_persistence": "in_memory",
        },
        "panel": {"state": "idle", "proposal_count": 0},
        "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
        "runtime": {},
        "suggestions": {},
    }


def _loaded_page(client: _FakeClient) -> RealNoteWorkspaceDevPage:
    page = RealNoteWorkspaceDevPage(client)  # type: ignore[arg-type]
    page.load(NoteLoadIntent(note_path="Notes/canvas.md"))
    return page


def test_edit_submit_calls_api() -> None:
    client = _FakeClient([
        _workspace_payload(content_hash="hash-1"),
        _workspace_payload(body="# Canvas Note\n\nUpdated.", content_hash="hash-2"),
    ])
    page = _loaded_page(client)

    state = page.apply_canvas_edit(
        session_id="session-1",
        note_path="Notes/canvas.md",
        new_body="# Canvas Note\n\nUpdated.",
        change_summary="rewrote body",
        content_hash="hash-1",
    )

    assert state.is_loaded is True
    assert client.post_calls == [
        (
            "/api/canvas/sessions/session-1/edits",
            {
                "new_body": "# Canvas Note\n\nUpdated.",
                "change_summary": "rewrote body",
                "content_hash": "hash-1",
            },
        ),
    ]


def test_edit_disabled_outside_active_session() -> None:
    client = _FakeClient([_workspace_payload(can_edit_body=False)])
    page = _loaded_page(client)

    state = page.apply_canvas_edit(
        session_id="session-1",
        note_path="Notes/canvas.md",
        new_body="Updated.",
        change_summary="rewrote body",
        content_hash="hash-1",
    )

    assert state.is_loaded is False
    assert "unavailable" in (state.error or "")
    assert client.post_calls == []


def test_workspace_refreshed_after_edit() -> None:
    client = _FakeClient([
        _workspace_payload(content_hash="hash-1"),
        _workspace_payload(content_hash="hash-2"),
    ])
    page = _loaded_page(client)

    page.apply_canvas_edit(
        session_id="session-1",
        note_path="Notes/canvas.md",
        new_body="Updated.",
        change_summary="rewrote body",
        content_hash="hash-1",
    )

    assert client.get_calls == [
        ("/api/companion/workspace", {"note_path": "Notes/canvas.md"}),
        ("/api/companion/workspace", {"note_path": "Notes/canvas.md"}),
    ]


def test_edit_error_state_visible() -> None:
    client = _FakeClient(
        [_workspace_payload(content_hash="hash-1")],
        post_error=WorkspaceClientHTTPError(409, "content_hash mismatch"),
    )
    page = _loaded_page(client)

    state = page.apply_canvas_edit(
        session_id="session-1",
        note_path="Notes/canvas.md",
        new_body="Updated.",
        change_summary="rewrote body",
        content_hash="hash-1",
    )

    assert state.is_loaded is False
    assert state.error is not None
    assert "409" in state.error
    assert "content_hash mismatch" in state.error
