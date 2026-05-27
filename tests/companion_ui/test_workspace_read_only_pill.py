"""Tests for read-only body pill — shell error surface (§8.5 / #1341 AC1–2)."""
from __future__ import annotations

import re

from companion_ui.workspace.serve_dev_page import render_index_html


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
    def test_pill_visible_when_canvas_disabled(self) -> None:
        html = _render(guard_canvas_enabled=False)
        assert 'data-testid="workspace-read-only-pill"' in html
        m = re.search(r'data-testid="workspace-read-only-pill"[^>]*title="([^"]+)"', html)
        assert m, "read-only pill missing title attribute"
        assert re.search(r"Canvas off", m.group(1)), f"title does not mention Canvas off: {m.group(1)!r}"

    def test_pill_absent_when_canvas_enabled(self) -> None:
        html = _render(guard_canvas_enabled=True)
        assert 'data-testid="workspace-read-only-pill"' not in html

    def test_pill_has_height_constraint_in_css(self) -> None:
        html = _render(guard_canvas_enabled=False)
        assert re.search(r"\.workspace-read-only-pill\s*\{[^}]*height:\s*24px", html, re.DOTALL)

    def test_read_only_appears_in_at_most_three_surfaces(self) -> None:
        import re as _re
        html = _render(guard_canvas_enabled=False)
        # Strip style/script blocks so we only count user-visible text and data-* attrs
        stripped = _re.sub(r"<style[^>]*>.*?</style[^>]*>", "", html, flags=_re.DOTALL | _re.IGNORECASE)
        stripped = _re.sub(r"<script[^>]*>.*?</script[^>]*>", "", stripped, flags=_re.DOTALL | _re.IGNORECASE)
        # Remove HTML tags, leaving only text and attribute values
        text_only = _re.sub(r"<[^>]+>", " ", stripped)
        count = text_only.lower().count("read-only")
        # Three pre-existing + new surfaces are acceptable:
        #   1) vault-browser-read-only span (vault browser status, always shown)
        #   2) reorient-mode rail-state-value "read-only" (panel affordance, empty state)
        #   3) workspace-read-only-pill text "▍ read-only" (the new note-level indicator)
        assert count <= 3, f"'read-only' visible text appears {count} times (expected ≤ 3)"
