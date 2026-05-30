"""UI seeding of the vault link index from the runtime API (#1431).

`RealNoteWorkspaceDevPage.load` fetches `GET /api/companion/vault-link-index`
and exposes the note-path list as `fields["vault_link_index"]`, which
`serve_dev_page` feeds into the `VaultLinkResolver` so wikilinks resolve
end-to-end. A failed/absent fetch degrades to an empty index (links stay
diagnostic), and the UI never reads the vault filesystem directly.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from companion_ui.workspace.real_note_workspace_dev_page import NoteLoadIntent, RealNoteWorkspaceDevPage
from companion_ui.workspace.workspace_http_client import WorkspaceClientNetworkError, WorkspaceHttpClient


def _workspace_payload() -> dict[str, Any]:
    return {
        "artifact": {
            "artifact_id": "note-uuid-link-1",
            "artifact_kind": "human_note",
            "note_path": "notes/current.md",
            "title": "Current",
            "body": "See [[Existing Note]].",
            "content_hash": "hash-current",
            "identity_source": "frontmatter.uuid",
            "identity_state": "resolved",
            "companion_of": None,
            "owns_identity": True,
        },
        "canvas": {"session_state": "idle", "session_persistence": "in_memory"},
        "panel": {"state": "idle", "proposal_count": 0},
        "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
        "runtime": {
            "environment_label": "dev",
            "api_base_url_label": "local-dev",
            "trace_id": "trace-link-index",
            "vault_identity": {"vault_name": "Niflheim", "channel": "dev", "provenance": "env"},
        },
        "suggestions": {},
    }


def _vault_browser_payload() -> dict[str, Any]:
    return {
        "notes": [{"note_path": "notes/current.md", "title": "Current", "zone": "notes"}],
        "query": "",
        "total_notes": 1,
        "filtered_notes": 1,
        "read_only": True,
        "vault_identity": {"vault_name": "Niflheim", "channel": "dev", "provenance": "env"},
        "identity_available": True,
    }


def _link_index_payload() -> dict[str, Any]:
    return {
        "note_paths": ["notes/current.md", "Notes/Existing Note.md", "Archive/Other.md"],
        "total_notes": 3,
        "truncated": False,
        "read_only": True,
        "vault_identity": {"vault_name": "Niflheim", "channel": "dev", "provenance": "env"},
        "identity_available": True,
    }


def _mock_get_response(payload: dict[str, Any]) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = payload
    return mock


def _load_page(*, link_index_error: bool = False) -> RealNoteWorkspaceDevPage:
    def _side_effect(url: str, *, params: dict[str, Any], timeout: float):
        if url.endswith("/api/companion/workspace"):
            return _mock_get_response(_workspace_payload())
        if url.endswith("/api/companion/vault-browser"):
            return _mock_get_response(_vault_browser_payload())
        if url.endswith("/api/companion/vault-link-index"):
            if link_index_error:
                raise WorkspaceClientNetworkError("link index unavailable")
            return _mock_get_response(_link_index_payload())
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("httpx.get", side_effect=_side_effect):
        client = WorkspaceHttpClient(base_url="http://localhost:18001")
        page = RealNoteWorkspaceDevPage(client)
        page.load(NoteLoadIntent(note_path="notes/current.md"))
    return page


def test_render_fields_populates_vault_link_index_from_endpoint() -> None:
    # AC2 — the page seeds fields["vault_link_index"] from the link-index API.
    page = _load_page()
    fields = page.render_fields()
    assert fields is not None
    assert fields["vault_link_index"] == [
        "notes/current.md",
        "Notes/Existing Note.md",
        "Archive/Other.md",
    ]


def test_link_index_fetch_failure_degrades_to_empty() -> None:
    # A failed link-index fetch must not break note load; index is empty.
    page = _load_page(link_index_error=True)
    fields = page.render_fields()
    assert fields is not None
    assert fields["vault_link_index"] == []
    assert fields["body"]  # the note still loaded and rendered
