from __future__ import annotations

import re
from typing import Any

from companion_ui.workspace.serve_dev_page import render_index_html


def _fields() -> dict[str, Any]:
    return {
        "title": "Note Title",
        "note_path": "Notes/panel.md",
        "artifact_id": "art-1829",
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": "sha256-aaa",
        "body": "# Note\n\nBody paragraph.",
        "panel_rail": "Panel / agent rail placeholder",
        "runtime_environment_label": "dev",
        "runtime_api_base_url_label": "local-dev",
        "runtime_trace_id": "trace-1",
        "runtime_vault_name": "vault/dev",
        "runtime_vault_channel": "local-dev",
        "runtime_vault_provenance": "resolved",
        "canvas_session_state": "idle",
        "canvas_session_persistence": "durable",
        "panel_state": "proposals-staged",
        "panel_proposal_count": 1,
        "panel_proposals": [
            {
                "proposal_id": "prop-1829",
                "artifact_id": "art-1829",
                "description": "Move note to Projects",
                "evidence": {
                    "trigger_summary": "Trigger",
                    "action_class": "lifecycle.move",
                    "cognition_route": "rule",
                },
                "status": "staged",
                "proposal_origin": None,
                "reflected_receipt": None,
                "affordances": {"confirm": True, "correct": True, "reject": True},
            }
        ],
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


def _render() -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/panel.md",
        fields=_fields(),
    )


def _palette_script(html: str) -> str:
    m = re.search(
        r"/\* panel-palette-controller \*/(.*?)/\* /panel-palette-controller \*/",
        html,
        re.S,
    )
    assert m, "panel palette controller script must render"
    return m.group(1)


def test_palette_action_posts_to_panel_confirm() -> None:
    html = _render()
    script = _palette_script(html)

    assert 'data-testid="palette-proposal-action"' in html
    assert 'data-api-path="/api/panel/confirm"' in html
    assert "function postPanelAction(btn)" in script
    assert "fetch(path" in script
    assert "method: 'POST'" in script
    assert "proposal_id: btn.getAttribute('data-proposal-id')" in script
    assert "artifact_id: btn.getAttribute('data-artifact-id')" in script
    assert "var action = btn.getAttribute('data-panel-action') || 'confirm'" in script
    assert "action: action" in script
    assert "data-runtime-backed') !== 'true'" in script
    assert "idempotency_key: 'palette:'" in script
    assert "postPanelAction(btn)" in script
    assert "railButton.click()" not in script


def test_palette_action_disables_in_flight_and_reports_result() -> None:
    # ST-2 (ui-audit): the POST is no longer fire-and-forget — it guards against
    # double-submit (aria-disabled) and reflects success/error on the button.
    script = _palette_script(_render())
    assert "aria-disabled" in script
    assert "data-action-state" in script
    assert ".then(function(r)" in script
    assert ".catch(function" in script


def test_palette_filter_has_no_match_state() -> None:
    # ST-3 (ui-audit): filtering to zero matches shows a 'no matches' row
    # instead of a silently blank list.
    html = _render()
    assert 'data-testid="palette-filter-empty"' in html
    script = _palette_script(html)
    assert "palette-filter-empty" in script
    assert "hits === 0" in script
