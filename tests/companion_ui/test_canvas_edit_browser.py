"""Tests for Canvas direct body-edit apply in the workspace shell (#1129)."""

from __future__ import annotations

from typing import Any

from companion_ui.workspace.real_note_workspace_dev_page import (
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)
from companion_ui.workspace.serve_dev_page import render_index_html
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
    canvas_enabled: bool = True,
    writeguard_status: str = "ok",
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
        "guards": {"canvas_enabled": canvas_enabled, "writeguard_status": writeguard_status},
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


def test_edit_requires_preview_confirmation() -> None:
    client = _FakeClient([_workspace_payload(content_hash="hash-1")])
    page = _loaded_page(client)

    state = page.apply_canvas_edit(
        session_id="session-1",
        note_path="Notes/canvas.md",
        new_body="Updated.",
        change_summary="apply without preview",
        content_hash="hash-1",
        preview_confirmed=False,
    )

    assert state.is_loaded is False
    assert "requires preview" in (state.error or "")
    assert client.post_calls == []


def _render_canvas(client: _FakeClient) -> str:
    page = _loaded_page(client)
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/canvas.md",
        fields=fields,
    )


def test_canvas_body_edit_apply_disabled_outside_active_editable_session() -> None:
    html = _render_canvas(_FakeClient([_workspace_payload(can_edit_body=False)]))

    assert 'data-testid="workspace-canvas-edit-submit"' in html
    assert 'data-testid="workspace-canvas-body-edit-composer"' not in html
    assert 'data-testid="workspace-canvas-body-edit-unavailable"' in html
    assert 'data-capability="canvas.applyBodyEdit"' in html
    assert 'data-affordance-status="unavailable"' in html
    assert 'data-testid="workspace-canvas-edit-submit"' in html
    assert "Apply body edit</button>" in html
    assert 'disabled>Apply body edit</button>' in html


def test_canvas_body_edit_composer_preview_and_discard_visible_when_editable() -> None:
    html = _render_canvas(_FakeClient([_workspace_payload(can_edit_body=True)]))

    assert 'data-testid="workspace-canvas-body-edit-composer"' in html
    assert 'data-testid="workspace-canvas-body-edit-textarea"' in html
    assert 'data-testid="workspace-canvas-body-edit-preview"' in html
    assert 'data-preview-state="required"' in html
    assert "Preview required before apply" in html
    assert 'data-testid="workspace-canvas-edit-discard"' in html
    assert 'data-runtime-backed="false"' in html
    assert 'data-api-method="LOCAL"' in html
    assert 'name="content_hash" value="hash-1"' in html


def test_canvas_in_memory_session_volatility_visible() -> None:
    html = _render_canvas(_FakeClient([_workspace_payload(can_edit_body=True)]))

    assert 'data-testid="workspace-session-persistence"' in html
    assert "Session persistence: in_memory" in html


def test_canvas_disabled_blocks_body_edit_affordances() -> None:
    html = _render_canvas(
        _FakeClient([_workspace_payload(can_edit_body=True, canvas_enabled=False)])
    )

    assert 'data-testid="workspace-guard-indicator"' in html
    assert "Canvas disabled" in html
    assert 'data-capability="canvas.applyBodyEdit"' in html
    assert 'data-affordance-status="blocked"' in html
    assert 'disabled>Apply body edit</button>' in html
    assert 'data-testid="workspace-canvas-body-edit-composer"' not in html


def test_canvas_body_edit_lane_does_not_render_governance_queue_action() -> None:
    html = _render_canvas(_FakeClient([_workspace_payload(can_edit_body=True)]))

    canvas_region = html.split('data-testid="workspace-canvas-session-controls"', 1)[1]
    canvas_region = canvas_region.split('data-testid="workspace-canvas-provenance"', 1)[0]
    assert "governance.queue" not in canvas_region
    assert "/governance" not in canvas_region


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
