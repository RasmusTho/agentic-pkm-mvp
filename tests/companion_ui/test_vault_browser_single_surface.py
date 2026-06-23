"""Single canonical Vault Browser surface (#1398).

Applies ``ADAPTIVE_WORKSPACE_LAYOUT_HANDOFF.md`` §5: the normal desktop
workspace exposes exactly one canonical Vault Browser surface — the left
context panel in browse mode. Every Browse Vault entrypoint focuses that
canonical surface rather than opening a competing modal. The modal/sheet
browser remains only as a narrow responsive fallback (hidden by default),
and same-origin remote-client behaviour is preserved.

These are SSR markup/contract tests against the rendered dev-page HTML.
"""

from __future__ import annotations

import re

from companion_ui.workspace.serve_dev_page import render_index_html


def _fields(*, note_path: str = "Notes/note.md") -> dict:
    return {
        "title": "Note Title",
        "note_path": note_path,
        "artifact_id": "art-123",
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": "sha256-aaa",
        "body": "# Note\n\nBody content here.",
        "panel_rail": "Panel / agent rail placeholder",
        "runtime_environment_label": "dev",
        "runtime_api_base_url_label": "local-dev",
        "runtime_trace_id": "trace-1",
        "runtime_vault_name": "vault/dev",
        "runtime_vault_channel": "local-dev",
        "runtime_vault_provenance": "resolved",
        "canvas_session_state": "idle",
        "canvas_session_persistence": "durable",
        "panel_state": "idle",
        "panel_proposal_count": 0,
        "panel_proposals": [],
        "panel_message": "",
        "guard_writeguard_status": "ok",
        "guard_canvas_enabled": True,
        "guard_degraded": False,
        "guard_workspace_update_available": True,
        "guard_update_flow_available": True,
        "find_candidates": [],
        "find_payload_available": False,
        "reorient_sections": {},
        "resurface_candidates": [],
        "governance_receipts": [],
        "suggestion_state": "idle",
        "suggestion_composer_enabled": True,
        "is_production_ui": False,
        "dev_page_label": "dev/staging",
        "workspace_loaded_at": None,
    }


def _html(**kw) -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=kw.get("note_path", "Notes/note.md"),
        fields=_fields(**kw),
    )


# ---------------------------------------------------------------------------
# AC: exactly one default/canonical Vault Browser surface
# ---------------------------------------------------------------------------


def test_only_one_default_vault_browser_surface():
    html = _html()
    # Exactly one surface is declared canonical, and it is the left context pane.
    assert html.count('data-browser-role="canonical"') == 1
    canonical = re.search(
        r'<nav[^>]*data-testid="workspace-vault-browser-left-pane"[^>]*>', html
    )
    assert canonical and 'data-browser-role="canonical"' in canonical.group(0)
    # Exactly one canonical browser region (the left context pane) in the
    # default workspace; the modal overlay is not canonical.
    assert html.count('data-region="vault-browser-pane"') == 1
    assert html.count('data-testid="workspace-vault-browser-left-pane"') == 1


# ---------------------------------------------------------------------------
# AC: Browse Vault focuses the left-panel browse surface
# ---------------------------------------------------------------------------


def test_browse_vault_focuses_left_panel_browse_mode():
    # CUIDR-04 (#2447): the standalone header "Browse vault" launcher left the
    # front edge (identity + Capture only). Vault browse is now reached via the
    # vault identity chip, which routes to the canonical left-pane browse
    # surface, and via the System Map's vault node — never a second non-Capture
    # header button competing for topbar width.
    html = _html()
    chip = re.search(
        r'<a[^>]*data-testid="workspace-vault-chip"[^>]*>', html
    )
    assert chip, "vault identity chip missing"
    token = chip.group(0)
    # The chip routes to the canonical left-pane browse surface, not the modal.
    assert 'href="#vault-browser-left-pane"' in token


# ---------------------------------------------------------------------------
# AC: desktop browse does not open a duplicate modal
# ---------------------------------------------------------------------------


def test_desktop_browse_does_not_open_duplicate_modal():
    html = _html()
    # No browse entrypoint opens the modal directly via an onclick handler;
    # the modal is reachable only through the responsive fallback branch.
    assert 'onclick="vaultBrowser.open()"' not in html
    # The vault identity chip no longer jumps straight to the modal overlay.
    assert 'href="#vault-browser-overlay"' not in html
    # The modal overlay is explicitly a narrow responsive fallback, not canonical.
    overlay = re.search(
        r'<div[^>]*data-testid="vault-browser-overlay"[^>]*>', html
    )
    assert overlay and 'data-browser-role="responsive-fallback"' in overlay.group(0)


# ---------------------------------------------------------------------------
# AC: no duplicate visible browser regions in the default workspace
# ---------------------------------------------------------------------------


def test_no_duplicate_visible_browser_regions_in_default_workspace():
    html = _html()
    # Only one canonical left-pane browser region renders by default.
    assert html.count('data-testid="workspace-vault-browser-left-pane"') == 1
    # The fallback modal overlay is hidden by default (display:none until .open).
    m = re.search(r"\n {4}\.vault-browser-overlay\s*\{(.*?)\n {4}\}", html, re.S)
    assert m, ".vault-browser-overlay rule not found"
    assert "display: none;" in m.group(1)


# ---------------------------------------------------------------------------
# AC: same-origin remote-safe behaviour preserved
# ---------------------------------------------------------------------------


def test_same_origin_remote_safe_behavior_preserved():
    html = _html()
    # Browser-side vault listing uses a same-origin relative path...
    assert "'/api/companion/vault/notes'" in html
    # ...with no client-side dependency on a runtime localhost host.
    assert "127.0.0.1:18001/api/companion/vault/notes" not in html
    assert "fetch('http://127.0.0.1" not in html
    assert 'fetch("http://127.0.0.1' not in html
