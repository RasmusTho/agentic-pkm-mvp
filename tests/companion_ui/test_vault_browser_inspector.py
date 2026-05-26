"""Artifact inspector panel tests for the vault browser (#1255).

Pins the MLP v0 UI invariants for the artifact inspector:

- selecting a browser result renders an inspector panel
- inspector renders normalized metadata fields from the server payload
- inspector renders frontmatter/health state (visible, not hidden)
- inspector distinguishes artifact identity from vault/channel identity
- links and agent receipts are shown as explicit placeholders
- inspector is read-only (no write/edit controls)

The inspector renders for the currently active browser note (the note
matching the current note_path). Data comes from the vault-browser API
payload; the client never parses vault files or frontmatter directly.
"""

from __future__ import annotations

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
            "trace_id": "trace-inspector",
            "vault_identity": {"vault_name": "Niflheim", "channel": "dev", "provenance": "env"},
        },
        "suggestions": {},
    }


def _browser_note(
    *,
    note_path: str = "notes/current.md",
    title: str = "Current",
    uuid: str | None = "test-uuid-abc",
    kind: str | None = "human_note",
    zone: str = "notes",
    review_state: str | None = "needs_review",
    trust: str | None = "assert",
    origin: str | None = "vault",
    source_ref: str | None = None,
    created: str | None = "2026-01-01",
    updated: str | None = "2026-05-01",
    frontmatter_valid: bool = True,
    missing_required_fields: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "note_path": note_path,
        "title": title,
        "uuid": uuid,
        "kind": kind,
        "zone": zone,
        "review_state": review_state,
        "trust": trust,
        "origin": origin,
        "source_ref": source_ref,
        "created": created,
        "updated": updated,
        "frontmatter_valid": frontmatter_valid,
        "missing_required_fields": missing_required_fields or [],
    }


def _vault_browser_payload(
    *,
    notes: list[dict[str, Any]] | None = None,
    vault_name: str = "Niflheim",
    channel: str = "dev",
    identity_available: bool = True,
) -> dict[str, Any]:
    if notes is None:
        notes = [_browser_note()]
    return {
        "notes": notes,
        "query": "",
        "total_notes": len(notes),
        "filtered_notes": len(notes),
        "read_only": True,
        "vault_identity": {"vault_name": vault_name, "channel": channel, "provenance": "env"},
        "identity_available": identity_available,
        "active_filters": {},
    }


def _mock_get_response(payload: dict[str, Any]) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = payload
    return mock


def _load_page(
    *,
    note_path: str = "notes/current.md",
    workspace_payload: dict[str, Any] | None = None,
    browser_payload: dict[str, Any] | None = None,
) -> tuple[RealNoteWorkspaceDevPage, dict | None, str]:
    workspace = _mock_get_response(workspace_payload or _workspace_payload(note_path=note_path))
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
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=note_path,
        fields=fields,
    )
    return page, fields, html


# ---- AC1: inspector renders when note is selected ----


def test_inspector_panel_renders_for_active_note() -> None:
    """AC1: Selecting a browser result renders an artifact inspector panel."""
    _, _, html = _load_page(note_path="notes/current.md")
    assert 'data-testid="workspace-vault-browser-inspector"' in html


def test_inspector_panel_absent_when_no_matching_note() -> None:
    """AC1 corollary: no active note match → inspector panel absent."""
    browser = _vault_browser_payload(notes=[_browser_note(note_path="notes/other.md")])
    _, _, html = _load_page(note_path="notes/current.md", browser_payload=browser)
    assert 'data-testid="workspace-vault-browser-inspector"' not in html


# ---- AC2: inspector renders metadata fields ----


def test_inspector_renders_title_and_path() -> None:
    """AC2: Inspector renders at minimum the title and path."""
    note = _browser_note(title="My Rich Note", note_path="notes/current.md")
    browser = _vault_browser_payload(notes=[note])
    _, _, html = _load_page(note_path="notes/current.md", browser_payload=browser)
    assert 'data-testid="workspace-vault-browser-inspector-title"' in html
    assert "My Rich Note" in html
    assert 'data-testid="workspace-vault-browser-inspector-path"' in html
    assert "notes/current.md" in html


def test_inspector_renders_uuid_when_present() -> None:
    """AC2: Inspector renders uuid when present in payload."""
    note = _browser_note(uuid="abc-uuid-123")
    browser = _vault_browser_payload(notes=[note])
    _, _, html = _load_page(note_path="notes/current.md", browser_payload=browser)
    assert 'data-testid="workspace-vault-browser-inspector-uuid"' in html
    assert "abc-uuid-123" in html


def test_inspector_omits_uuid_when_absent() -> None:
    """AC2 corollary: absent uuid → uuid section absent (not blank)."""
    note = _browser_note(uuid=None)
    browser = _vault_browser_payload(notes=[note])
    _, _, html = _load_page(note_path="notes/current.md", browser_payload=browser)
    assert 'data-testid="workspace-vault-browser-inspector-uuid"' not in html


def test_inspector_renders_metadata_section_fields() -> None:
    """AC2: Inspector renders kind, zone, review_state, trust when present."""
    note = _browser_note(
        kind="human_note",
        zone="active",
        review_state="needs_review",
        trust="assert",
    )
    browser = _vault_browser_payload(notes=[note])
    _, _, html = _load_page(note_path="notes/current.md", browser_payload=browser)
    assert 'data-testid="workspace-vault-browser-inspector-kind"' in html
    assert 'data-testid="workspace-vault-browser-inspector-zone"' in html
    assert 'data-testid="workspace-vault-browser-inspector-review-state"' in html
    assert 'data-testid="workspace-vault-browser-inspector-trust"' in html


# ---- AC3: health state visible and not hidden ----


def test_inspector_renders_health_section_for_invalid_frontmatter() -> None:
    """AC3: Inspector renders health state visibly for invalid/missing frontmatter."""
    note = _browser_note(frontmatter_valid=False, missing_required_fields=["uuid"])
    browser = _vault_browser_payload(notes=[note])
    _, _, html = _load_page(note_path="notes/current.md", browser_payload=browser)
    assert 'data-testid="workspace-vault-browser-inspector-health"' in html
    assert 'data-health-state="invalid"' in html
    assert "uuid" in html


def test_inspector_health_section_shows_valid_for_healthy_note() -> None:
    """AC3 corollary: valid frontmatter → health section shows valid state."""
    note = _browser_note(frontmatter_valid=True, missing_required_fields=[])
    browser = _vault_browser_payload(notes=[note])
    _, _, html = _load_page(note_path="notes/current.md", browser_payload=browser)
    assert 'data-testid="workspace-vault-browser-inspector-health"' in html
    assert 'data-health-state="valid"' in html


# ---- AC4: artifact identity vs vault/channel identity distinct ----


def test_inspector_distinguishes_artifact_identity_from_vault_identity() -> None:
    """AC4: Inspector renders artifact identity and vault identity as separate surfaces."""
    note = _browser_note(uuid="art-uuid-xyz", origin="vault")
    browser = _vault_browser_payload(notes=[note], vault_name="Niflheim", channel="dev")
    _, _, html = _load_page(note_path="notes/current.md", browser_payload=browser)
    assert 'data-testid="workspace-vault-browser-inspector-artifact-identity"' in html
    assert 'data-testid="workspace-vault-browser-inspector-vault-identity"' in html
    assert "Niflheim" in html
    assert "art-uuid-xyz" in html


# ---- AC5: links and receipts as explicit placeholders ----


def test_inspector_renders_links_placeholder() -> None:
    """AC5: Links section shown as explicit 'not connected yet' placeholder."""
    _, _, html = _load_page()
    assert 'data-testid="workspace-vault-browser-inspector-links-placeholder"' in html


def test_inspector_renders_receipts_section() -> None:
    """AC5: Agent receipts section is present (explicit unavailable or no-receipts state)."""
    _, _, html = _load_page()
    assert 'data-testid="workspace-vault-browser-inspector-receipts"' in html


# ---- AC6: read-only — no mutation controls ----


def test_inspector_has_no_edit_controls() -> None:
    """AC6: Inspector exposes no write/edit controls."""
    _, _, html = _load_page()
    inspector_start = html.find('data-testid="workspace-vault-browser-inspector"')
    assert inspector_start != -1
    inspector_end = html.find("</section>", inspector_start)
    if inspector_end == -1:
        inspector_end = inspector_start + 4000
    inspector_html = html[inspector_start:inspector_end]
    assert 'data-intent="write' not in inspector_html
    assert 'data-intent="edit' not in inspector_html
    assert "data-affordance-status=\"active\"" not in inspector_html


# ---- #1283: companion note visual distinction in inspector ----


def test_inspector_companion_note_carries_data_companion_true() -> None:
    """#1283 AC2: Inspector panel for companion_note carries data-companion="true"."""
    note = _browser_note(
        note_path="notes/current.md",
        kind="companion_note",
    )
    _, _, html = _load_page(
        browser_payload=_vault_browser_payload(notes=[note]),
    )
    inspector_start = html.find('data-testid="workspace-vault-browser-inspector"')
    assert inspector_start != -1
    # Extract just the opening section tag
    inspector_tag_end = html.find(">", inspector_start) + 1
    inspector_tag = html[inspector_start:inspector_tag_end]
    assert 'data-companion="true"' in inspector_tag, (
        f"companion_note inspector must carry data-companion=\"true\"; got: {inspector_tag!r}"
    )


def test_inspector_companion_note_carries_data_kind() -> None:
    """#1283 AC2: Inspector panel for companion_note carries data-kind="companion_note"."""
    note = _browser_note(
        note_path="notes/current.md",
        kind="companion_note",
    )
    _, _, html = _load_page(
        browser_payload=_vault_browser_payload(notes=[note]),
    )
    inspector_start = html.find('data-testid="workspace-vault-browser-inspector"')
    assert inspector_start != -1
    inspector_tag_end = html.find(">", inspector_start) + 1
    inspector_tag = html[inspector_start:inspector_tag_end]
    assert 'data-kind="companion_note"' in inspector_tag, (
        f"companion_note inspector must carry data-kind=\"companion_note\"; got: {inspector_tag!r}"
    )


def test_inspector_human_note_has_no_companion_attribute() -> None:
    """#1283 AC2 boundary: Inspector panel for human_note does NOT carry data-companion="true"."""
    note = _browser_note(
        note_path="notes/current.md",
        kind="human_note",
    )
    _, _, html = _load_page(
        browser_payload=_vault_browser_payload(notes=[note]),
    )
    inspector_start = html.find('data-testid="workspace-vault-browser-inspector"')
    assert inspector_start != -1
    inspector_tag_end = html.find(">", inspector_start) + 1
    inspector_tag = html[inspector_start:inspector_tag_end]
    assert 'data-companion="true"' not in inspector_tag
