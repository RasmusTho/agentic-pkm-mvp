"""Tests for note-not-found empty state — shell error surface (§9 / #1341 AC5–6)."""
from __future__ import annotations

from companion_ui.workspace.serve_dev_page import render_index_html


def _render(**overrides) -> str:
    fields: dict = {
        "title": "",
        "note_path": "Does/Not/Exist.md",
        "artifact_id": "",
        "content_hash": "",
        "guard_writeguard_status": "ok",
        "guard_canvas_enabled": True,
        "guard_degraded": False,
        "guard_workspace_update_available": False,
        "guard_update_flow_available": False,
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
        "note_not_found": True,
    }
    fields.update(overrides)
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=fields["note_path"],
        fields=fields,
    )


class TestNoteNotFound:
    def test_empty_state_absent_by_default(self) -> None:
        html = render_index_html(
            api_base_url="http://127.0.0.1:18001",
            note_path="Notes/exists.md",
            fields={
                "title": "Existing Note",
                "note_path": "Notes/exists.md",
                "artifact_id": "art-001",
                "content_hash": "sha-abc",
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
            },
        )
        assert 'data-testid="workspace-note-not-found"' not in html

    def test_empty_state_shape(self) -> None:
        html = _render()
        assert 'data-testid="workspace-note-not-found"' in html
        assert "<h1>Note not found</h1>" in html
        assert "<code>Does/Not/Exist.md</code>" in html
        assert "The vault may have moved or this link may be stale." in html
        assert "Browse vault" in html
        assert "Open last note" in html

    def test_empty_state_uses_no_destructive_color(self) -> None:
        html = _render()
        import re
        not_found_m = re.search(
            r'data-testid="workspace-note-not-found".*?</div>',
            html,
            re.DOTALL,
        )
        assert not_found_m, "workspace-note-not-found not found"
        subtree = not_found_m.group()
        assert "--destructive" not in subtree, "note-not-found uses --destructive color token"

    def test_two_action_buttons_present(self) -> None:
        html = _render()
        assert html.count(">Browse vault<") >= 1
        assert 'data-testid="workspace-open-last-note"' in html
