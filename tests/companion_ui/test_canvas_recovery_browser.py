"""Tests for Canvas recovery and conflict display in the workspace shell (#1131)."""

from __future__ import annotations

from typing import Any

from companion_ui.workspace.real_note_workspace_dev_page import (
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)
from companion_ui.workspace.serve_dev_page import render_index_html
from companion_ui.workspace.workspace_http_client import WorkspaceClientNetworkError


class _FakeClient:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.get_calls: list[tuple[str, dict[str, Any]]] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append((url, params))
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        self.post_calls.append((url, json))
        return {"session_id": "session-1", "ok": True}


def _workspace_payload(
    *,
    content_hash: str = "hash-1",
    session_state: str = "active",
    recovery_needed: bool = False,
    can_edit_body: bool = True,
) -> dict[str, Any]:
    return {
        "artifact": {
            "artifact_id": "art-1131",
            "note_path": "Notes/canvas.md",
            "title": "Canvas Note",
            "body": "# Canvas Note\n\nBody.",
            "content_hash": content_hash,
        },
        "canvas": {
            "session_id": "session-1",
            "session_state": session_state,
            "user_present": True,
            "can_edit_body": can_edit_body,
            "recovery_needed": recovery_needed,
            "session_log_path": ".chats/canvas/session.md",
            "undo_available": False,
            "applied_edit_count": 0,
            "undone_edit_count": 0,
            "session_persistence": "in_memory",
        },
        "panel": {"state": "idle", "proposal_count": 0},
        "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
        "runtime": {},
        "suggestions": {},
    }


def _load_page(client: _FakeClient) -> RealNoteWorkspaceDevPage:
    page = RealNoteWorkspaceDevPage(client)  # type: ignore[arg-type]
    state = page.load(NoteLoadIntent(note_path="Notes/canvas.md"))
    assert state.is_loaded is True
    return page


def _html(page: RealNoteWorkspaceDevPage) -> str:
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/canvas.md",
        fields=fields,
    )


def test_edits_blocked_during_recovery() -> None:
    client = _FakeClient([_workspace_payload(recovery_needed=True)])
    page = _load_page(client)
    html = _html(page)

    state = page.apply_canvas_edit(
        session_id="session-1",
        note_path="Notes/canvas.md",
        new_body="Updated.",
        change_summary="edit during recovery",
        content_hash="hash-1",
    )

    assert state.is_loaded is False
    assert "unavailable" in (state.error or "")
    assert client.post_calls == []
    assert "disabled>Apply body edit</button>" in html


def test_conflict_indicator_visible() -> None:
    for session_state in ("paused", "interrupted"):
        client = _FakeClient([
            _workspace_payload(session_state=session_state, recovery_needed=True)
        ])
        page = _load_page(client)
        html = _html(page)

        assert 'data-testid="workspace-canvas-recovery-conflict"' in html
        assert session_state in html
        assert 'data-testid="workspace-canvas-recovery-ack"' in html
        assert 'data-testid="workspace-canvas-recovery-copy"' in html
        assert "Acknowledge recovery before applying body edits." in html


def test_edits_resume_after_recovery_ack() -> None:
    client = _FakeClient([
        _workspace_payload(content_hash="hash-1"),
        _workspace_payload(content_hash="hash-2", recovery_needed=True),
        _workspace_payload(content_hash="hash-3", recovery_needed=False),
    ])
    page = _load_page(client)
    page.load(NoteLoadIntent(note_path="Notes/canvas.md"))

    state_before_ack = page.apply_canvas_edit(
        session_id="session-1",
        note_path="Notes/canvas.md",
        new_body="Updated.",
        change_summary="blocked before ack",
        content_hash="hash-2",
    )
    assert state_before_ack.is_loaded is False
    assert client.post_calls == []

    page.acknowledge_canvas_recovery(note_path="Notes/canvas.md")
    state_after_ack = page.apply_canvas_edit(
        session_id="session-1",
        note_path="Notes/canvas.md",
        new_body="Updated.",
        change_summary="allowed after ack",
        content_hash="hash-2",
    )

    assert state_after_ack.is_loaded is True
    assert client.post_calls == [
        (
            "/api/canvas/sessions/session-1/edits",
            {
                "new_body": "Updated.",
                "change_summary": "allowed after ack",
                "content_hash": "hash-2",
            },
        ),
    ]


def test_hash_drift_blocks_without_recovery_flag() -> None:
    client = _FakeClient([
        _workspace_payload(content_hash="hash-1"),
        _workspace_payload(content_hash="hash-2", recovery_needed=False),
    ])
    page = _load_page(client)
    state = page.load(NoteLoadIntent(note_path="Notes/canvas.md"))

    assert state.canvas_conflict_detected is True
    assert state.canvas_can_edit_body is False


def test_recovery_ack_resets_for_new_conflict_cycle() -> None:
    client = _FakeClient([
        _workspace_payload(content_hash="hash-1", recovery_needed=True),
        _workspace_payload(content_hash="hash-2", recovery_needed=True),
    ])
    page = _load_page(client)
    page.acknowledge_canvas_recovery(note_path="Notes/canvas.md")

    state = page.load(NoteLoadIntent(note_path="Notes/canvas.md"))

    assert state.canvas_conflict_detected is True
    assert state.canvas_recovery_acknowledged is False
    assert state.canvas_can_edit_body is False


def test_failed_post_edit_refresh_clears_trusted_hash_bypass() -> None:
    client = _FakeClient([
        _workspace_payload(content_hash="hash-1"),
        WorkspaceClientNetworkError("refresh failed"),
        _workspace_payload(content_hash="hash-2", recovery_needed=False),
    ])
    page = _load_page(client)

    failed_refresh = page.apply_canvas_edit(
        session_id="session-1",
        note_path="Notes/canvas.md",
        new_body="Updated.",
        change_summary="edit before failed refresh",
        content_hash="hash-1",
    )
    assert failed_refresh.is_loaded is False

    state = page.load(NoteLoadIntent(note_path="Notes/canvas.md"))

    assert state.canvas_conflict_detected is True
    assert state.canvas_can_edit_body is False
