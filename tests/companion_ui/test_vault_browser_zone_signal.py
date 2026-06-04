"""Vault Browser zone-signal surfacing — #1555 (TOPOLOGY_AWARE_ZONE_PROJECTION/SURFACE_ZONE_SIGNALS).

The Vault Browser UI must make the #1488 zone envelope legible: a durable, frontmatter-authored
zone (``durable_vault_metadata``) must be visibly distinguishable from a path-derived guess
(``runtime_projection``), and the provenance/degradation of a degraded zone must be inspectable.
The UI reads the server-declared envelope verbatim — it never re-derives zone authority locally.

Verify targets for #1555 ACs. (The issue named ``companion-ui/tests/vault_browser_zone_signal.test.*``;
the repo's Python companion-ui render tests live under ``tests/companion_ui/``, so this is the
nearest-authority home, matching the existing ``test_vault_browser_inspector.py``.)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from companion_ui.workspace.real_note_workspace_dev_page import NoteLoadIntent, RealNoteWorkspaceDevPage
from companion_ui.workspace.serve_dev_page import render_index_html
from companion_ui.workspace.workspace_http_client import WorkspaceHttpClient


def _workspace_payload(note_path: str) -> dict[str, Any]:
    return {
        "artifact": {
            "artifact_id": "note-uuid-1",
            "artifact_kind": "human_note",
            "note_path": note_path,
            "title": "Current",
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
            "trace_id": "trace-zone-signal",
            "vault_identity": {"vault_name": "Niflheim", "channel": "dev", "provenance": "env"},
        },
        "suggestions": {},
    }


def _note(
    *,
    note_path: str,
    zone: str,
    zone_source: str,
    zone_authority_role: str,
    zone_provenance: str,
    zone_degradation: str,
) -> dict[str, Any]:
    return {
        "note_path": note_path,
        "title": "Current",
        "uuid": "uuid-1",
        "kind": "human_note",
        "zone": zone,
        "zone_source": zone_source,
        "zone_authority_role": zone_authority_role,
        "zone_provenance": zone_provenance,
        "zone_degradation": zone_degradation,
        "review_state": "needs_review",
        "trust": "assert",
        "origin": "vault",
        "source_ref": None,
        "created": None,
        "updated": None,
        "frontmatter_valid": True,
        "missing_required_fields": [],
        "relations_state": "empty",
    }


def _browser_payload(note: dict[str, Any]) -> dict[str, Any]:
    return {
        "notes": [note],
        "query": "",
        "total_notes": 1,
        "filtered_notes": 1,
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


def _render(note: dict[str, Any]) -> str:
    note_path = str(note["note_path"])
    workspace = _mock_get_response(_workspace_payload(note_path))
    browser = _mock_get_response(_browser_payload(note))

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


def _durable_note() -> dict[str, Any]:
    return _note(
        note_path="notes/durable.md",
        zone="active",
        zone_source="frontmatter.zone",
        zone_authority_role="durable_vault_metadata",
        zone_provenance="frontmatter.zone",
        zone_degradation="none",
    )


def _path_fallback_note() -> dict[str, Any]:
    return _note(
        note_path="Projects/path.md",
        zone="Projects",
        zone_source="vault_path_segment",
        zone_authority_role="runtime_projection",
        zone_provenance="vault_path[0]=Projects",
        zone_degradation="frontmatter_absent",
    )


def _zone_field(html: str) -> str:
    """Extract the inspector zone <div>...</div> block."""
    start = html.find('data-testid="workspace-vault-browser-inspector-zone"')
    assert start != -1, "inspector zone field not found"
    div_start = html.rfind("<div", 0, start)
    div_end = html.find("</div>", start)
    return html[div_start : div_end + len("</div>")]


# ---- AC1: durable vs path-derived zone render differently ----


def test_durable_and_path_derived_zone_render_states_differ() -> None:
    durable_field = _zone_field(_render(_durable_note()))
    path_field = _zone_field(_render(_path_fallback_note()))

    assert durable_field != path_field, "durable and path-derived zone must render differently"

    # Authority role is carried verbatim from the server envelope and is distinguishable.
    assert 'data-zone-authority-role="durable_vault_metadata"' in durable_field
    assert 'data-zone-authority-role="runtime_projection"' in path_field

    # The visible authority affordance differs.
    assert "frontmatter" in durable_field
    assert "derived from path" in path_field


def test_durable_zone_is_not_flagged_as_degraded() -> None:
    durable_field = _zone_field(_render(_durable_note()))
    assert 'data-zone-degradation="none"' in durable_field
    # No degradation provenance affordance for a clean durable zone.
    assert "workspace-vault-browser-inspector-zone-provenance" not in durable_field


# ---- AC2: provenance + degradation inspectable for a path-fallback note ----


def test_path_fallback_zone_exposes_provenance_and_degradation() -> None:
    path_field = _zone_field(_render(_path_fallback_note()))

    assert 'data-zone-source="vault_path_segment"' in path_field
    assert 'data-zone-provenance="vault_path[0]=Projects"' in path_field
    assert 'data-zone-degradation="frontmatter_absent"' in path_field

    # A dedicated, inspectable provenance/degradation affordance is present.
    assert "workspace-vault-browser-inspector-zone-provenance" in path_field
    assert "frontmatter_absent" in path_field
    assert "vault_path[0]=Projects" in path_field


def test_malformed_frontmatter_zone_surfaces_invalid_degradation() -> None:
    note = _note(
        note_path="Inbox/broken.md",
        zone="Inbox",
        zone_source="vault_path_segment",
        zone_authority_role="runtime_projection",
        zone_provenance="vault_path[0]=Inbox",
        zone_degradation="frontmatter_invalid",
    )
    path_field = _zone_field(_render(note))
    assert 'data-zone-degradation="frontmatter_invalid"' in path_field
    assert "derived from path" in path_field


# ---- AC3: UI reads the server envelope; no local re-derivation ----


def test_zone_envelope_is_driven_purely_by_api_payload() -> None:
    # A deliberately inconsistent payload (path-looking zone declared as durable) must be rendered
    # as the server declares it — proving the UI does not recompute authority from the path/value.
    note = _note(
        note_path="Projects/declared-durable.md",
        zone="Projects",
        zone_source="frontmatter.zone",
        zone_authority_role="durable_vault_metadata",
        zone_provenance="frontmatter.zone",
        zone_degradation="none",
    )
    field = _zone_field(_render(note))
    assert 'data-zone-authority-role="durable_vault_metadata"' in field
    assert "frontmatter" in field
    assert "derived from path" not in field


# ---- AC4: no zone-based ordering/overlay introduced ----


def test_no_zone_ordering_overlay_introduced() -> None:
    html = _render(_path_fallback_note())
    assert 'data-testid="workspace-vault-browser-zone-ordering"' not in html
    assert 'data-testid="workspace-vault-browser-zone-overlay"' not in html
    # Note links remain in deterministic path order (no zone-based reordering control rendered).
    assert "data-sort=\"zone\"" not in html
