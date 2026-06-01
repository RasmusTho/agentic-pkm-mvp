from __future__ import annotations

from companion_ui.workspace.serve_dev_page import render_index_html


def _fields() -> dict:
    return {
        "title": "Panel Note",
        "note_path": "notes/panel.md",
        "artifact_id": "note-uuid-1",
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_owns_identity": True,
        "content_hash": "content-hash",
        "body": (
            "# Panel Note\n\n"
            "- [ ] ordinary task\n\n"
            "%% AI:Start %%\n"
            "## AI-instruktion\n"
            "Do the thing.\n"
            "## AI-åtgärder\n"
            "- [ ] Send email <!--ai:option_id=opt_ui--> <!--ai:id=send.email--> <!--ai:proposed=979-->\n"
            "%% AI:End %%\n"
        ),
        "panel_state": "proposals-staged",
        "panel_proposal_count": 1,
        "panel_selectable_options": [
            {
                "artifact_id": "note-uuid-1",
                "note_path": "notes/panel.md",
                "panel_id": "panel-1",
                "option_id": "opt_ui",
                "action_id": "send.email",
                "label": "Send email",
                "checked": False,
                "proposal_pending": True,
                "source_range": {"start_line": 8, "end_line": 9},
                "source_hash": "source-hash",
                "content_hash": "content-hash",
                "selectable": True,
            }
        ],
        "guard_writeguard_status": "ok",
        "guard_canvas_enabled": True,
        "guard_degraded": False,
        "is_production_ui": False,
        "dev_page_label": "dev/staging",
    }


def test_read_mode_panel_option_has_projection_affordance_and_ordinary_task_is_disabled() -> None:
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/panel.md",
        fields=_fields(),
    )

    ordinary_index = html.index("ordinary task")
    ordinary_input = html.rfind("<input", 0, ordinary_index)
    assert "disabled" in html[ordinary_input:ordinary_index]

    assert 'data-panel-checkbox="true"' in html
    assert 'data-panel-id="panel-1"' in html
    assert 'data-option-id="opt_ui"' in html
    assert 'data-source-hash="source-hash"' in html
    assert "/api/panel/checkbox-projection" in html
    assert "/api/companion/workspace?note_path=" in html
    assert "panelProjectionSucceeded(result.data)" in html
    assert "'blocked'" in html
    assert "'failed'" in html
    assert "panel-checkbox-feedback" in html
