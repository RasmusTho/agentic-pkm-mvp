from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from companion_ui.workspace.real_note_workspace_dev_page import NoteLoadIntent, RealNoteWorkspaceDevPage
from companion_ui.workspace.serve_dev_page import render_index_html
from companion_ui.workspace.workspace_http_client import WorkspaceClientNetworkError, WorkspaceHttpClient


def _workspace_payload(note_path: str = "notes/current.md", title: str = "Current") -> dict[str, Any]:
    return {
        "artifact": {
            "artifact_id": "note-uuid-1",
            "artifact_kind": "human_note",
            "note_path": note_path,
            "title": title,
            "body": "# Body\n",
            "content_hash": "abc",
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
            "trace_id": "trace-vault-browser",
            "vault_identity": {"vault_name": "Niflheim", "channel": "dev", "provenance": "env"},
        },
        "suggestions": {},
    }


def _vault_browser_payload(
    *,
    notes: list[dict[str, str]] | None = None,
    query: str = "",
    total_notes: int = 1,
    filtered_notes: int = 1,
    identity_available: bool = True,
) -> dict[str, Any]:
    return {
        "notes": notes
        or [
            {
                "note_path": "notes/Companion UI UAT.md",
                "title": "Companion UI UAT",
                "zone": "notes",
            }
        ],
        "query": query,
        "total_notes": total_notes,
        "filtered_notes": filtered_notes,
        "read_only": True,
        "vault_identity": {"vault_name": "Niflheim", "channel": "dev", "provenance": "env"},
        "identity_available": identity_available,
    }


def _mock_get_response(payload: dict[str, Any]) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = payload
    return mock


def _load_page(
    *,
    workspace_payload: dict[str, Any] | None = None,
    browser_payload: dict[str, Any] | None = None,
    browser_error: Exception | None = None,
    note_path: str = "notes/current.md",
) -> RealNoteWorkspaceDevPage:
    workspace = _mock_get_response(workspace_payload or _workspace_payload(note_path=note_path))
    browser = _mock_get_response(browser_payload or _vault_browser_payload())

    def _side_effect(url: str, *, params: dict[str, Any], timeout: float):
        if url.endswith("/api/companion/workspace"):
            return workspace
        if url.endswith("/api/companion/vault-browser"):
            if browser_error is not None:
                raise browser_error
            return browser
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("httpx.get", side_effect=_side_effect):
        client = WorkspaceHttpClient(base_url="http://localhost:18001")
        page = RealNoteWorkspaceDevPage(client)
        page.load(NoteLoadIntent(note_path=note_path))
    return page


def test_workspace_can_open_vault_browser() -> None:
    page = _load_page()
    fields = page.render_fields()
    assert fields is not None

    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )
    assert 'data-testid="workspace-vault-browser"' in html
    assert 'data-testid="workspace-vault-browser-toggle"' in html
    assert 'data-testid="workspace-vault-browser-list"' in html
    assert 'data-testid="workspace-vault-browser-note-link"' in html


def test_selecting_note_loads_workspace_note() -> None:
    page = _load_page(
        workspace_payload=_workspace_payload(note_path="notes/Companion UI UAT.md", title="Companion UI UAT"),
        note_path="notes/Companion UI UAT.md",
    )
    fields = page.render_fields()
    assert fields is not None

    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/Companion UI UAT.md",
        fields=fields,
    )
    assert fields["note_path"] == "notes/Companion UI UAT.md"
    assert "Companion UI UAT" in html
    assert "/?note_path=notes/Companion%20UI%20UAT.md" in html


def test_vault_browser_renders_active_vault_identity() -> None:
    page = _load_page()
    fields = page.render_fields()
    assert fields is not None

    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )
    assert 'data-testid="workspace-vault-browser-active-identity"' in html
    assert "Niflheim/dev" in html


def test_vault_browser_distinguishes_empty_error_and_identity_states() -> None:
    empty_page = _load_page(
        browser_payload=_vault_browser_payload(notes=[], total_notes=2, filtered_notes=0),
    )
    empty_fields = empty_page.render_fields()
    assert empty_fields is not None
    empty_html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=empty_fields,
    )
    assert 'data-testid="workspace-vault-browser-state-empty"' in empty_html

    error_page = _load_page(browser_error=WorkspaceClientNetworkError("connection refused"))
    error_fields = error_page.render_fields()
    assert error_fields is not None
    error_html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=error_fields,
    )
    assert 'data-testid="workspace-vault-browser-state-error"' in error_html

    identity_page = _load_page(
        browser_payload=_vault_browser_payload(identity_available=False),
    )
    identity_fields = identity_page.render_fields()
    assert identity_fields is not None
    identity_html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=identity_fields,
    )
    assert 'data-testid="workspace-vault-browser-state-identity-unavailable"' in identity_html
