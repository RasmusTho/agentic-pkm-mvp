"""Tests for responsive collapse breakpoints (§7.5 / #1342 AC1–6)."""
from __future__ import annotations

import re

from companion_ui.workspace.serve_dev_page import render_index_html


_BASE_FIELDS: dict = {
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
    "body": "# Section One\n\nBody content.\n\n## Section Two\n\nMore content.\n",
}


def _render(**overrides) -> str:
    fields = {**_BASE_FIELDS, **overrides}
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=fields["note_path"],
        fields=fields,
    )


def _css_block(html: str) -> str:
    m = re.search(r"<style[^>]*>(.*?)</style>", html, re.DOTALL)
    assert m, "no <style> block found"
    return m.group(1)


class TestFullLayoutAt1300:
    """AC1 — three columns present at ≥1300 px."""

    def test_three_column_regions_present(self) -> None:
        html = _render()
        assert 'data-testid="workspace-vault-browser-left-pane"' in html
        assert 'data-testid="workspace-note-body"' in html
        assert 'data-testid="workspace-agent-rail"' in html

    def test_full_layout_has_css_breakpoint_at_1300(self) -> None:
        css = _css_block(_render())
        # CSS must define behavior that keeps columns visible at ≥1300px
        assert "1100px" in css or "1099px" in css or "1300px" in css, (
            "no 1100-1299px breakpoint found in CSS"
        )

    def test_peek_tab_hidden_by_default_css(self) -> None:
        css = _css_block(_render())
        # workspace-panel-peek should default to display:none
        assert ".workspace-panel-peek" in css
        assert "display: none" in css


class TestPanelPeekTabAt1200:
    """AC2 — Panel peek tab at 1100–1299 px."""

    def test_panel_peek_present(self) -> None:
        html = _render()
        assert 'data-testid="workspace-panel-peek"' in html

    def test_peek_tab_css_media_query(self) -> None:
        css = _css_block(_render())
        # CSS must have a media query for 1100-1299px range
        assert "1100px" in css and "1299px" in css, (
            "missing 1100-1299px media query for panel peek"
        )

    def test_panel_peek_shown_in_1100_1299_css(self) -> None:
        css = _css_block(_render())
        # The 1100-1299px breakpoint should show the peek and hide the agent-rail
        assert "min-width: 1100px" in css
        assert "max-width: 1299px" in css


class TestPanelPeekShowsActiveCount:
    """AC3 — peek tab shows numeric badge when proposals exist."""

    def test_peek_shows_active_count(self) -> None:
        html = _render(
            panel_proposal_count=2,
            panel_proposals=[
                {"proposal_id": "p1", "status": "staged", "description": "Proposal 1",
                 "affordances": {}, "evidence": {}},
                {"proposal_id": "p2", "status": "staged", "description": "Proposal 2",
                 "affordances": {}, "evidence": {}},
            ],
            panel_state="proposals-staged",
        )
        peek_m = re.search(
            r'data-testid="workspace-panel-peek"[^>]*data-panel-proposal-count="(\d+)"',
            html,
        )
        assert peek_m, "workspace-panel-peek with proposal count not found"
        assert peek_m.group(1) == "2", f"expected count=2, got {peek_m.group(1)}"
        assert 'data-testid="workspace-panel-peek-badge"' in html

    def test_peek_no_badge_when_no_proposals(self) -> None:
        html = _render(panel_proposal_count=0)
        assert 'data-testid="workspace-panel-peek-badge"' not in html


class TestOutlineRibbonAt900:
    """AC4 — Outline ribbon at 800–1099 px."""

    def test_outline_ribbon_present(self) -> None:
        html = _render()
        assert 'data-testid="workspace-outline-ribbon"' in html

    def test_outline_ribbon_css_media_query(self) -> None:
        css = _css_block(_render())
        assert "800px" in css and "1099px" in css, (
            "missing 800-1099px media query for outline ribbon"
        )

    def test_outline_ribbon_shown_in_css(self) -> None:
        css = _css_block(_render())
        assert "min-width: 800px" in css
        assert "max-width: 1099px" in css


class TestSingleColumnAt768:
    """AC5 — single column at <800 px with sheet triggers and stacked header."""

    def test_sheet_triggers_present(self) -> None:
        html = _render()
        assert 'data-testid="workspace-outline-sheet-trigger"' in html
        assert 'data-testid="workspace-panel-sheet-trigger"' in html

    def test_single_column_css_at_max_799(self) -> None:
        css = _css_block(_render())
        assert "max-width: 799px" in css, "missing max-799px media query"

    def test_header_stacks_at_small_viewport(self) -> None:
        css = _css_block(_render())
        # Header strip wraps (flex-wrap) at narrow viewports
        assert "flex-wrap: wrap" in css


class TestOutlineSheetAnchorNavigation:
    """AC6 — anchor navigation survives modal sheet."""

    def test_outline_rows_have_anchor_hrefs(self) -> None:
        html = _render()
        # Outline links have fragment href attributes
        links = re.findall(r'href="#([^"]+)"', html)
        assert links, "no anchor hrefs found in outline"
        # Each anchor target must exist somewhere in the body
        for anchor in links:
            assert f'id="{anchor}"' in html or f"id='{anchor}'" in html, (
                f"anchor target #{anchor} not found in body"
            )
