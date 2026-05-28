"""Tests for Panel section idle/active state model and Reorient collapse (§8 / #1338 AC1–6)."""
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
}

_PROPOSAL_FIXTURE = {
    "proposal_id": "prop-test-001",
    "artifact_id": "art-001",
    "description": "Add a section on agentic systems",
    "status": "staged",
    "agent": "hugin",
    "created_at": "2026-05-26T14:18",
    "confidence": "0.82",
    "affordances": {"confirm": True, "reject": True, "correct": True},
    "evidence": {
        "trigger_summary": "note gap detected",
        "action_class": "insert",
        "cognition_route": "reorient",
    },
}


def _render(**overrides) -> str:
    fields = {**_BASE_FIELDS, **overrides}
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=fields["note_path"],
        fields=fields,
    )


def _rail_region(html: str) -> str:
    m = re.search(r'data-testid="workspace-agent-rail".*?</aside>', html, re.DOTALL)
    assert m, "agent rail not found"
    return m.group()


class TestIdleRendersOneLine:
    """AC1 — idle state renders one-line strip."""

    def test_idle_renders_one_line_strip(self) -> None:
        html = _render()
        rail = _rail_region(html)
        # Reorient in idle state renders with data-section-state="idle"
        assert 'data-section-state="idle"' in rail

    def test_active_renders_agent_card(self) -> None:
        html = _render(
            panel_proposals=[_PROPOSAL_FIXTURE],
            panel_proposal_count=1,
            panel_state="proposals-staged",
        )
        rail = _rail_region(html)
        assert 'data-section-state="active"' in rail


class TestIdleHasNoAgentChrome:
    """AC2 — idle strips drop agent-blue tokens."""

    def test_idle_has_no_agent_chrome(self) -> None:
        html = _render()
        rail = _rail_region(html)
        # In idle state: no panel-section--active class should appear
        assert "panel-section--active" not in rail

    def test_idle_reorient_has_no_agent_left_rule(self) -> None:
        html = _render()
        # Scan the reorient section for --agent usage in style attributes
        reorient_m = re.search(
            r'data-testid="reorient-mode".*?</section>',
            html,
            re.DOTALL,
        )
        assert reorient_m
        subtree = reorient_m.group()
        # Should not contain inline agent-blue style
        assert "border-left-color: var(--agent)" not in subtree
        assert "panel-section--active" not in subtree


class TestReorientDefaultCollapsed:
    """AC3 — Reorient defaults to one-line with recall ▾ disclosure."""

    def test_reorient_default_collapsed(self) -> None:
        html = _render()
        assert 'data-testid="reorient-recall-disclosure"' in html
        # Match the whole <summary> opening tag to check aria-expanded
        trigger_m = re.search(
            r'<summary[^>]*data-testid="reorient-recall-trigger"[^>]*>',
            html,
        )
        assert trigger_m, "reorient-recall-trigger not found"
        assert 'aria-expanded="false"' in trigger_m.group(), (
            f"recall trigger not collapsed: {trigger_m.group()!r}"
        )

    def test_reorient_verbose_body_hidden_initially(self) -> None:
        html = _render(reorient_sections=None)
        body_m = re.search(
            r'data-testid="reorient-recall-body"[^>]*>',
            html,
        )
        assert body_m, "reorient-recall-body not found"
        # Must be hidden (hidden attribute) or inside unopened details
        details_m = re.search(
            r'<details[^>]*data-testid="reorient-recall-disclosure"[^>]*>',
            html,
        )
        assert details_m
        assert " open" not in details_m.group(), "reorient disclosure is open by default"


class TestActiveCardRequiresProvenance:
    """AC4 — active cards carry mandatory provenance line."""

    def test_active_card_requires_provenance(self) -> None:
        html = _render(
            panel_proposals=[_PROPOSAL_FIXTURE],
            panel_proposal_count=1,
            panel_state="proposals-staged",
        )
        assert 'data-testid="workspace-panel-provenance"' in html
        # Must match the provenance pattern
        prov_m = re.search(
            r'data-testid="workspace-panel-provenance"[^>]*>([^<]+)',
            html,
        )
        assert prov_m, "provenance element not found"
        # Pattern: agent · YYYY-MM-DDTHH:MM · confidence N (HTML entities decoded)
        text = (
            prov_m.group(1)
            .replace("&nbsp;", " ")
            .replace("&middot;", "·")
            .replace("·", "·")
            .strip()
        )
        assert re.search(
            r"[a-z]+ · \d{4}-\d{2}-\d{2}T?\d{2}:\d{2} · confidence",
            text,
        ), f"provenance text does not match pattern: {text!r}"


class TestActionRowOrderAndFocus:
    """AC5 — action row order: Apply, Discard, Defer; Apply not default focus."""

    def test_action_row_order_and_focus(self) -> None:
        html = _render(
            panel_proposals=[_PROPOSAL_FIXTURE],
            panel_proposal_count=1,
            panel_state="proposals-staged",
        )
        rail = _rail_region(html)
        # Find Apply, Discard, Defer positions
        apply_pos = rail.find(">Apply<")
        discard_pos = rail.find(">Discard<")
        defer_pos = rail.find(">Defer<")
        assert apply_pos != -1, "Apply button not found"
        assert discard_pos != -1, "Discard button not found"
        assert defer_pos != -1, "Defer button not found"
        assert apply_pos < discard_pos < defer_pos, (
            f"action row order wrong: Apply={apply_pos}, Discard={discard_pos}, Defer={defer_pos}"
        )

    def test_apply_has_no_default_focus(self) -> None:
        html = _render(
            panel_proposals=[_PROPOSAL_FIXTURE],
            panel_proposal_count=1,
            panel_state="proposals-staged",
        )
        # Apply button must not have data-default-focus or autofocus
        apply_m = re.search(r'<button[^>]*panel-action-apply[^>]*>', html)
        assert apply_m, "Apply button not found"
        btn_tag = apply_m.group()
        assert "data-default-focus" not in btn_tag, "Apply has data-default-focus"
        assert "autofocus" not in btn_tag, "Apply has autofocus"


class TestAllIdleColumnHeader:
    """AC6 — column header reads Panel · idle when all sections idle."""

    def test_all_idle_column_header(self) -> None:
        html = _render(panel_state="idle")
        assert 'data-testid="workspace-panel-column-header"' in html
        header_m = re.search(
            r'data-testid="workspace-panel-column-header".*?</div>',
            html,
            re.DOTALL,
        )
        assert header_m
        header_text = header_m.group()
        # Should contain "Panel" and "idle" near each other
        assert "Panel" in header_text
        assert "idle" in header_text.lower()
