"""Tests for Canvas session browser controls in the workspace shell (#1128)."""

from __future__ import annotations

from typing import Any

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
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.get_calls: list[tuple[str, dict[str, Any]]] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []
        self.delete_calls: list[tuple[str, dict[str, Any] | None]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append((url, params))
        if is_vault_browser_get(url):
            return default_vault_browser_payload()
        return self.payloads.pop(0)

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        self.post_calls.append((url, json))
        return {"session_id": "session-1"}

    def delete(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.delete_calls.append((url, params))
        return {"session_id": "session-1"}


def _workspace_payload(
    *,
    session_id: str | None = None,
    session_state: str | None = None,
    user_present: bool = False,
    can_edit_body: bool = False,
    session_persistence: str = "in_memory",
) -> dict[str, Any]:
    return {
        "artifact": {
            "artifact_id": "art-1128",
            "note_path": "Notes/canvas.md",
            "title": "Canvas Note",
            "body": "# Canvas Note\n\nBody.",
            "content_hash": "sha256-canvas",
        },
        "canvas": {
            "session_id": session_id,
            "session_state": session_state,
            "user_present": user_present,
            "can_edit_body": can_edit_body,
            "recovery_needed": session_state == "paused",
            "session_log_path": None,
            "session_persistence": session_persistence,
        },
        "panel": {"state": "idle", "proposal_count": 0},
        "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
        "runtime": {},
        "suggestions": {},
    }


def _html_for_canvas(**canvas_overrides: Any) -> str:
    client = _FakeClient([_workspace_payload(**canvas_overrides)])
    page = RealNoteWorkspaceDevPage(client)  # type: ignore[arg-type]
    state = page.load(NoteLoadIntent(note_path="Notes/canvas.md"))
    assert state.is_loaded is True
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/canvas.md",
        fields=fields,
    )


def test_session_controls_rendered() -> None:
    html = _html_for_canvas(session_id="session-1", session_state="active")

    assert 'data-testid="workspace-canvas-session-controls"' in html
    assert 'data-testid="workspace-canvas-start"' not in html
    assert 'data-action="start-session"' in html
    assert 'data-testid="workspace-canvas-close"' in html
    assert 'data-api-path="/api/canvas/sessions/session-1"' in html


def test_session_open_and_close_call_canvas_api() -> None:
    client = _FakeClient([
        _workspace_payload(session_id="session-1", session_state="active"),
        _workspace_payload(session_id=None, session_state="closed"),
    ])
    page = RealNoteWorkspaceDevPage(client)  # type: ignore[arg-type]

    page.open_canvas_session(NoteLoadIntent(note_path="Notes/canvas.md"))
    page.close_canvas_session(session_id="session-1", note_path="Notes/canvas.md")

    assert client.post_calls == [
        ("/api/canvas/sessions", {"note_path": "Notes/canvas.md"}),
    ]
    assert client.delete_calls == [
        (
            "/api/canvas/sessions/session-1",
            {"total_summary": "session closed from Companion UI"},
        ),
    ]
    assert [call for call in client.get_calls if call[0] == "/api/companion/workspace"] == [
        ("/api/companion/workspace", {"note_path": "Notes/canvas.md"}),
        ("/api/companion/workspace", {"note_path": "Notes/canvas.md"}),
    ]


def test_edit_controls_disabled_outside_active() -> None:
    html = _html_for_canvas(
        session_id=None,
        session_state="idle",
        can_edit_body=False,
    )

    assert 'data-testid="workspace-canvas-edit-submit"' not in html
    assert 'data-testid="workspace-canvas-action-unavailable"' in html
    assert 'data-action="apply-body-edit"' in html


def test_session_state_indicator() -> None:
    for state in ("active", "paused", "closed"):
        html = _html_for_canvas(session_id="session-1", session_state=state)
        assert 'data-testid="workspace-canvas-state"' in html
        assert state in html


def test_in_memory_persistence_notice() -> None:
    html = _html_for_canvas(session_persistence="in_memory")

    assert 'data-testid="workspace-session-persistence"' in html
    assert "Session persistence: in_memory" in html
