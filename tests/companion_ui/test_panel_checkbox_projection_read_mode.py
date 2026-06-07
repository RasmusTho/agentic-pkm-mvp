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


def test_read_mode_panel_option_renders_structured_decision_surface() -> None:
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/panel.md",
        fields=_fields(),
    )

    assert 'class="panel-decision-surface"' in html
    assert 'data-panel-decision-field="decision"' in html
    assert 'data-panel-decision-field="recommendation"' in html
    assert 'data-panel-decision-field="why"' in html
    assert 'data-panel-decision-field="risk"' in html
    assert 'data-panel-decision-field="source"' in html
    assert 'data-panel-decision-field="choices"' in html
    assert 'data-panel-decision-field="status"' in html
    assert "Confirm this Panel proposal?" in html
    assert "Send email" in html
    assert "Panel staged action" in html
    assert "source freshness is checked before projection" in html
    assert "notes/panel.md lines 8-9; source hash source-hash" in html
    assert 'data-panel-choice="confirm"' in html
    assert 'data-panel-local-choice="defer"' in html
    assert 'data-panel-local-choice="reject"' in html
    assert 'data-panel-status="pending">Awaiting confirmation.' in html
    assert 'data-panel-id="panel-1"' in html
    assert 'data-option-id="opt_ui"' in html
    assert 'data-source-hash="source-hash"' in html

    source_index = html.index('data-panel-decision-field="source"')
    confirm_index = html.index('data-panel-choice="confirm"')
    assert source_index < confirm_index

    option_index = html.index('data-panel-checkbox="true"')
    option_input = html.rfind("<input", 0, option_index)
    option_input_end = html.index(">", option_index)
    assert " checked" not in html[option_input:option_input_end]


def test_read_mode_panel_defer_reject_are_local_only() -> None:
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/panel.md",
        fields=_fields(),
    )

    assert 'data-panel-local-choice="defer" data-affordance-status="local-only"' in html
    assert 'data-panel-local-choice="reject" data-affordance-status="local-only"' in html
    assert "no durable change was written" in html

    local_handler_start = html.index("button[data-panel-local-choice]")
    local_handler_end = html.index("input[data-panel-checkbox", local_handler_start)
    local_handler = html[local_handler_start:local_handler_end]
    assert "fetch(" not in local_handler
    assert "/api/panel/checkbox-projection" not in local_handler
    assert "/api/companion/note/save" not in local_handler
