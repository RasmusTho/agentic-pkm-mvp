"""Persistent left-pane Vault Browser layout tests (#1288).

Pins the R2 layout requirement from VAULT_BROWSER_UI_REQUIREMENTS.md:

- A persistent left-pane Vault Browser is visible alongside the central note pane
- Clicking a browser entry opens that artifact in the central pane
- Left-pane browsing uses client-reachable same-origin behavior
- Modal/popup browsing is not the default target interaction when the left pane is available
- Future capabilities (graph, timeline) are not rendered

These tests are structural/HTML contract tests. AC6 (real browser UAT receipt)
is a merge gate enforced by verification-and-closure, not by this test file.
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import MagicMock, patch

from companion_ui.workspace.real_note_workspace_dev_page import NoteLoadIntent, RealNoteWorkspaceDevPage
from companion_ui.workspace.serve_dev_page import render_index_html
from companion_ui.workspace.workspace_http_client import WorkspaceHttpClient


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
            "trace_id": "trace-left-pane",
            "vault_identity": {"vault_name": "Niflheim", "channel": "dev", "provenance": "env"},
        },
        "suggestions": {},
    }


def _vault_browser_payload(notes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if notes is None:
        notes = [
            {
                "note_path": "notes/first.md",
                "title": "First Note",
                "kind": "human_note",
                "zone": "notes",
                "review_state": "needs_review",
                "trust": "assert",
                "origin": "vault",
                "source_ref": None,
                "created": None,
                "updated": None,
                "uuid": "uuid-1",
                "frontmatter_valid": True,
                "missing_required_fields": [],
            },
            {
                "note_path": "notes/second.md",
                "title": "Second Note",
                "kind": "human_note",
                "zone": "notes",
                "review_state": "needs_review",
                "trust": "assert",
                "origin": "vault",
                "source_ref": None,
                "created": None,
                "updated": None,
                "uuid": "uuid-2",
                "frontmatter_valid": True,
                "missing_required_fields": [],
            },
        ]
    return {
        "notes": notes,
        "query": "",
        "total_notes": len(notes),
        "filtered_notes": len(notes),
        "read_only": True,
        "vault_identity": {"vault_name": "Niflheim", "channel": "dev", "provenance": "env"},
        "identity_available": True,
        "active_filters": {},
    }


def _mock_get_response(payload: dict[str, Any]) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = payload
    return mock


def _load_html(
    *,
    note_path: str = "notes/current.md",
    browser_payload: dict[str, Any] | None = None,
) -> str:
    workspace = _mock_get_response(_workspace_payload(note_path=note_path))
    browser = _mock_get_response(browser_payload or _vault_browser_payload())

    def _side_effect(url: str, *, params: dict[str, Any], timeout: float):
        if url.endswith("/api/companion/workspace"):
            return workspace
        if url.endswith("/api/companion/vault-browser"):
            return browser
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("httpx.get", side_effect=_side_effect):
        client = WorkspaceHttpClient(base_url="http://localhost:18001")
        page = RealNoteWorkspaceDevPage(client)
        page.load(NoteLoadIntent(note_path=note_path))

    fields = page.render_fields()
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=note_path,
        fields=fields,
    )


# ---- AC1: left pane visible with central note pane ----


def test_left_pane_visible_with_central_note_pane() -> None:
    """AC1: Persistent left-pane vault browser is visible alongside the central note pane."""
    html = _load_html()
    assert 'data-testid="workspace-vault-browser-left-pane"' in html, (
        "workspace-vault-browser-left-pane must be present in the page"
    )
    assert 'data-testid="workspace-note-body"' in html, (
        "workspace-note-body (central pane) must be present alongside the left pane"
    )


def test_left_pane_contains_vault_browser() -> None:
    """AC1 structural: The vault browser is nested inside the left-pane element."""
    html = _load_html()
    left_pane_start = html.find('data-testid="workspace-vault-browser-left-pane"')
    browser_start = html.find('data-testid="workspace-vault-browser"')
    assert left_pane_start != -1, "workspace-vault-browser-left-pane not found"
    assert browser_start != -1, "workspace-vault-browser not found"
    assert browser_start > left_pane_start, (
        "workspace-vault-browser must be nested inside workspace-vault-browser-left-pane"
    )


# ---- AC2: clicking browser entry opens artifact in central pane ----


def test_clicking_browser_entry_opens_artifact_in_central_pane() -> None:
    """AC2: Browser entry links navigate to the note in the central pane (same-page URL param)."""
    html = _load_html()
    assert 'data-testid="workspace-vault-browser-note-link"' in html, (
        "workspace-vault-browser-note-link must be present"
    )
    # Links should use /?note_path=... for same-page navigation
    assert '/?note_path=' in html or '?note_path=' in html, (
        "browser entry links must use note_path param for in-page navigation"
    )


# ---- AC3: same-origin browser route ----


def test_left_pane_uses_same_origin_browser_route() -> None:
    """AC3: Browser entry links are same-origin (no absolute external URLs)."""
    html = _load_html()
    links = re.findall(
        r'<a\s+href="([^"]*)"[^>]*data-testid="workspace-vault-browser-note-link"',
        html,
    )
    assert links, "No vault-browser-note-link hrefs found"
    for link in links:
        assert not link.startswith("http://") and not link.startswith("https://"), (
            f"vault-browser-note-link must be same-origin, got absolute URL: {link!r}"
        )


# ---- AC4: left pane is default browser surface ----


def test_left_pane_is_default_browser_surface() -> None:
    """AC4: Vault browser is placed in the left pane (not only in the agent-rail/aside)."""
    html = _load_html()
    # The vault browser must exist in a left-pane element
    assert 'data-testid="workspace-vault-browser-left-pane"' in html, (
        "Left pane must be present as the default browser surface"
    )
    # The left pane must come before the agent-rail in document order
    left_pane_pos = html.find('data-testid="workspace-vault-browser-left-pane"')
    agent_rail_pos = html.find('data-testid="workspace-agent-rail"')
    assert left_pane_pos < agent_rail_pos, (
        "Left pane must appear before the agent-rail in document order"
    )


# ---- AC5: no graph/timeline/out-of-scope capabilities ----


def test_left_pane_does_not_render_graph_timeline_or_inspector() -> None:
    """AC5: Left pane does not render graph view, timeline, or other out-of-scope capabilities."""
    html = _load_html()
    assert 'data-testid="workspace-vault-browser-graph"' not in html
    assert 'data-testid="workspace-vault-browser-timeline"' not in html
    assert 'data-testid="workspace-graph-view"' not in html
    assert 'data-testid="workspace-timeline-view"' not in html


# ---- Layout structural tests ----


def test_workspace_layout_three_col_class() -> None:
    """Layout: workspace-layout has three-col class for left-pane mode."""
    html = _load_html()
    assert "workspace-layout--three-col" in html, (
        "workspace-layout must carry workspace-layout--three-col class in left-pane mode"
    )


def test_left_pane_data_region_attribute() -> None:
    """Layout: left pane carries data-region=vault-browser-pane for region tracking."""
    html = _load_html()
    assert 'data-region="vault-browser-pane"' in html, (
        "Left pane must carry data-region=vault-browser-pane"
    )
