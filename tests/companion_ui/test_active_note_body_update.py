from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from companion_ui.workspace.real_note_workspace_dev_page import NoteLoadIntent, RealNoteWorkspaceDevPage
from companion_ui.workspace.serve_dev_page import render_index_html
from companion_ui.workspace.workspace_http_client import WorkspaceClientNetworkError, WorkspaceHttpClient


def _workspace_payload(note_path: str = "notes/current.md", title: str = "Current") -> dict[str, Any]:
    return {
        "artifact": {
            "artifact_id": "note-uuid-update-1",
            "artifact_kind": "human_note",
            "note_path": note_path,
            "title": title,
            "body": "# Body\n\nInitial text.\n",
            "content_hash": "hash-current",
            "identity_source": "frontmatter.uuid",
            "identity_state": "resolved",
            "companion_of": None,
            "owns_identity": True,
        },
        "canvas": {"session_state": "idle", "session_persistence": "in_memory"},
        "panel": {"state": "idle", "proposal_count": 0},
        "guards": {
            "canvas_enabled": True,
            "writeguard_status": "ok",
            "workspace_update": {
                "available": True,
                "state": "available",
                "reason": "explicit_dev_config",
                "scope": "active_note_body",
                "governance_actions_enabled": False,
                "config_mode": "explicit",
            },
        },
        "runtime": {
            "environment_label": "dev",
            "api_base_url_label": "local-dev",
            "trace_id": "trace-active-note-update",
            "vault_identity": {"vault_name": "Niflheim", "channel": "dev", "provenance": "env"},
        },
        "suggestions": {},
    }


def _vault_browser_payload() -> dict[str, Any]:
    return {
        "notes": [
            {
                "note_path": "notes/current.md",
                "title": "Current",
                "zone": "notes",
            }
        ],
        "query": "",
        "total_notes": 1,
        "filtered_notes": 1,
        "read_only": True,
        "vault_identity": {"vault_name": "Niflheim", "channel": "dev", "provenance": "env"},
        "identity_available": True,
    }


def _mock_get_response(payload: dict[str, Any]) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = payload
    return mock


def _load_page(*, workspace_payload: dict[str, Any] | None = None) -> RealNoteWorkspaceDevPage:
    workspace = _mock_get_response(workspace_payload or _workspace_payload())
    browser = _mock_get_response(_vault_browser_payload())

    def _side_effect(url: str, *, params: dict[str, Any], timeout: float):
        if url.endswith("/api/companion/workspace"):
            return workspace
        if url.endswith("/api/companion/vault-browser"):
            return browser
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("httpx.get", side_effect=_side_effect):
        client = WorkspaceHttpClient(base_url="http://localhost:18001")
        page = RealNoteWorkspaceDevPage(client)
        page.load(NoteLoadIntent(note_path="notes/current.md"))
    return page


def test_user_can_enter_active_note_body_update_flow() -> None:
    page = _load_page()
    fields = page.render_fields()
    assert fields is not None

    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )
    assert 'data-testid="workspace-active-note-body-update-flow"' in html
    assert 'data-testid="workspace-active-note-body-update-input"' in html
    assert 'data-testid="workspace-active-note-body-update-submit"' in html


def test_body_update_renders_success_blocked_and_failure_states() -> None:
    page = _load_page()
    fields = page.render_fields()
    assert fields is not None

    fields["active_note_body_update_state"] = "success"
    fields["active_note_body_update_message"] = "active_note_body_updated"
    success_html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )
    assert 'data-testid="workspace-active-note-body-update-state-success"' in success_html

    fields["active_note_body_update_state"] = "blocked"
    fields["active_note_body_update_message"] = "writeguard blocked"
    blocked_html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )
    assert 'data-testid="workspace-active-note-body-update-state-blocked"' in blocked_html

    fields["active_note_body_update_state"] = "failure"
    fields["active_note_body_update_message"] = "network timeout"
    failure_html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )
    assert 'data-testid="workspace-active-note-body-update-state-failure"' in failure_html


def test_blocked_body_update_preserves_loaded_state_and_renders_blocked_status() -> None:
    page = _load_page()
    page.state.guard_workspace_update_available = False
    state = page.update_active_note_body(new_body="# Body\n\nBlocked")
    assert state.is_loaded is True
    assert state.shell is not None
    assert state.active_note_body_update_state == "blocked"


def test_failed_body_update_preserves_loaded_state_and_renders_failure_status() -> None:
    page = _load_page()
    with patch.object(page._http, "post", side_effect=WorkspaceClientNetworkError("network timeout")):
        state = page.update_active_note_body(new_body="# Body\n\nFail")
    assert state.is_loaded is True
    assert state.shell is not None
    assert state.active_note_body_update_state == "failure"
