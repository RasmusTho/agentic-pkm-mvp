"""Tests for read-only body pill — shell error surface (§8.5 / #1341 AC1–2)."""
from __future__ import annotations

import re

from companion_ui.workspace.serve_dev_page import render_index_html
from tests.companion_ui._visible_text import visible_text as _visible_text


def _render(**overrides) -> str:
    fields: dict = {
        "title": "Test Note",
        "note_path": "Notes/test.md",
        "artifact_id": "art-001",
        "content_hash": "sha256-abc",
        "guard_writeguard_status": "ok",
        "guard_canvas_enabled": True,
        "guard_degraded": False,
        "guard_workspace_update_available": False,
        "guard_update_flow_available": True,
        "runtime_vault_provenance": "resolved",
        "runtime_vault_name": "TestVault",
        "runtime_vault_channel": "dev",
        "panel_state": "idle",
        "panel_proposal_count": 0,
        "canvas_session_state": "idle",
        "canvas_session_persistence": "durable",
        "panel_proposals": [],
        "panel_message": "",
        "find_candidates": [],
        "reorient_sections": None,
        "resurface_candidates": [],
        "governance_receipts": [],
        "suggestion_state": "idle",
        "suggestion_composer_enabled": True,
        "is_production_ui": False,
        "dev_page_label": "dev/staging",
    }
    fields.update(overrides)
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=fields["note_path"],
        fields=fields,
    )


class TestReadOnlyPill:
    def test_no_readonly_pill_when_canvas_disabled(self) -> None:
        # #1447 — direct human editing is always available, so Canvas being off no
        # longer means the note is read-only. The misleading "Canvas off" read-only
        # pill is suppressed; a genuine write-blocked state surfaces at save time.
        html = _render(guard_canvas_enabled=False)
        assert 'data-testid="workspace-read-only-pill"' not in html
        # The editor is offered instead.
        assert 'data-testid="workspace-note-edit-toggle"' in html

    def test_pill_absent_when_canvas_enabled(self) -> None:
        html = _render(guard_canvas_enabled=True)
        assert 'data-testid="workspace-read-only-pill"' not in html

    def test_pill_has_height_constraint_in_css(self) -> None:
        html = _render(guard_canvas_enabled=False)
        assert re.search(r"\.workspace-read-only-pill\s*\{[^}]*height:\s*24px", html, re.DOTALL)

    def test_read_only_appears_in_at_most_three_surfaces(self) -> None:
        html = _render(guard_canvas_enabled=False)
        # Count only user-visible text occurrences. The parser-based helper
        # drops script/style subtrees and every tag/attribute, so data-* attrs
        # such as data-testid="workspace-read-only-pill" never inflate the count
        # (it lower-cases too, matching the lower-cased needle below).
        count = _visible_text(html).count("read-only")
        # Five surfaces are acceptable (CUIDR-02 / #2445 adds settings frame status-pill):
        #   1) vault-browser-read-only span (vault browser status, always shown)
        #   2) reorient-mode rail-state-value "read-only" (panel affordance, empty state)
        #   3) workspace-read-only-pill text "▍ read-only" (the note-level indicator)
        #   4) note-body-readonly-indicator "read-only" (daily-use body affordance, #1361)
        #   5) settings overlay-frame status-pill "read-only render" (CUIDR-02, #2445)
        assert count <= 5, f"'read-only' visible text appears {count} times (expected ≤ 5)"
