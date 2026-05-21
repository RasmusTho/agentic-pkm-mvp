"""Tests for Canvas provenance and undo controls in the workspace shell (#1130)."""

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
        self.delete_calls: list[tuple[str, dict[str, Any] | None]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append((url, params))
        return self.payloads.pop(0)

    def delete(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.delete_calls.append((url, params))
        return {"session_id": "session-1", "ok": True}


def _workspace_payload(
    *,
    body: str = "# Canvas Note\n\nBody.",
    session_log_path: str | None = ".chats/canvas/session.md",
    undo_available: bool = False,
    applied_edit_count: int = 0,
    undone_edit_count: int = 0,
) -> dict[str, Any]:
    return {
        "artifact": {
            "artifact_id": "art-1130",
            "note_path": "Notes/canvas.md",
            "title": "Canvas Note",
            "body": body,
            "content_hash": "hash-1",
        },
        "canvas": {
            "session_id": "session-1",
            "session_state": "active",
            "user_present": True,
            "can_edit_body": True,
            "recovery_needed": False,
            "session_log_path": session_log_path,
            "undo_available": undo_available,
            "applied_edit_count": applied_edit_count,
            "undone_edit_count": undone_edit_count,
            "session_persistence": "in_memory",
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


def test_session_log_path_visible() -> None:
    html = _html_for_canvas(session_log_path=".chats/canvas/session.md")

    assert 'data-testid="workspace-canvas-provenance"' in html
    assert 'data-testid="workspace-canvas-session-log-path"' in html
    assert ".chats/canvas/session.md" in html


def test_undo_enabled_only_when_available() -> None:
    disabled_html = _html_for_canvas(undo_available=False)
    enabled_html = _html_for_canvas(undo_available=True)

    assert 'data-testid="workspace-canvas-undo"' in disabled_html
    assert "disabled>Undo</button>" in disabled_html
    assert 'data-testid="workspace-canvas-undo-state"' in disabled_html
    assert "No undo available" in disabled_html
    assert 'data-api-path="/api/canvas/sessions/session-1/edits/last">Undo</button>' in enabled_html
    assert "Undo available" in enabled_html


def test_provenance_preserved_after_undo() -> None:
    client = _FakeClient(
        [
            _workspace_payload(undo_available=True, applied_edit_count=1),
            _workspace_payload(
                body="# Canvas Note\n\nOriginal.",
                undo_available=False,
                applied_edit_count=0,
                undone_edit_count=1,
            ),
        ]
    )
    page = RealNoteWorkspaceDevPage(client)  # type: ignore[arg-type]
    page.load(NoteLoadIntent(note_path="Notes/canvas.md"))

    state = page.undo_last_canvas_edit(
        session_id="session-1",
        note_path="Notes/canvas.md",
    )

    assert state.is_loaded is True
    assert client.delete_calls == [
        ("/api/canvas/sessions/session-1/edits/last", None),
    ]
    fields = page.render_fields()
    assert fields is not None
    assert fields["canvas_session_log_path"] == ".chats/canvas/session.md"
    assert fields["canvas_undone_edit_count"] == 1
