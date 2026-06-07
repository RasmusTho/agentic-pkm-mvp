from __future__ import annotations

from companion_ui.workspace.serve_dev_page import render_index_html


def _fields() -> dict:
    return {
        "title": "Readback Note",
        "note_path": "Notes/readback.md",
        "artifact_id": "note-readback",
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": "sha256-readback",
        "body": (
            "# Readback Note\n\n"
            "Source paragraph for read-back.\n\n"
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
                "artifact_id": "note-readback",
                "note_path": "Notes/readback.md",
                "panel_id": "panel-readback",
                "option_id": "opt_ui",
                "action_id": "send.email",
                "label": "Send email",
                "checked": False,
                "proposal_pending": True,
                "source_range": {"start_line": 8, "end_line": 9},
                "source_hash": "source-hash",
                "content_hash": "sha256-readback",
                "selectable": True,
            }
        ],
        "panel_rail": "Panel / agent rail placeholder",
        "runtime_environment_label": "dev",
        "runtime_api_base_url_label": "local-dev",
        "runtime_trace_id": "trace-readback",
        "runtime_vault_name": "vault/dev",
        "runtime_vault_channel": "local-dev",
        "runtime_vault_provenance": "resolved",
        "canvas_session_state": "idle",
        "canvas_session_persistence": "durable",
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


def _html() -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/readback.md",
        fields=_fields(),
    )


def _readback_script(html: str) -> str:
    start = html.index("var proposalFieldOrder")
    end = html.index("window.noteEditor", start)
    return html[start:end]


def test_tts_readback_controls_render() -> None:
    html = _html()

    assert 'data-testid="tts-readback-controls"' in html
    assert 'data-authority="read-only-projection"' in html
    assert 'data-source-scope="source-and-proposal"' in html
    assert 'data-testid="tts-rate"' in html
    assert 'data-testid="tts-read-full-note"' in html
    assert 'data-testid="tts-read-selection"' in html
    assert 'data-testid="tts-read-proposal"' in html
    assert 'data-testid="tts-pause"' in html
    assert 'data-testid="tts-resume"' in html
    assert 'data-testid="tts-stop"' in html
    assert 'data-testid="tts-readback-status"' in html

    draft_index = html.index('data-testid="workspace-note-edit-read-draft"')
    save_index = html.index('data-testid="workspace-note-edit-save"')
    assert draft_index < save_index


def test_tts_readback_uses_local_server_tts_not_browser_speech() -> None:
    html = _html()
    script = _readback_script(html)

    assert "'speechSynthesis' in window" not in script
    assert "SpeechSynthesisUtterance" not in script
    assert "/api/companion/tts/plan" in script
    assert "/api/companion/tts/synthesize" in script
    assert "data-tts-requires-speech=\"true\"" in html
    assert "controls[i].disabled = true" not in script
    assert "Local TTS idle." in script


def test_tts_readback_has_no_autoplay_or_backend_mutation_calls() -> None:
    html = _html()
    script = _readback_script(html)

    before_read_action = script[: script.index("function readText")]
    dom_ready = script[script.index("DOMContentLoaded") :]
    assert ".play()" not in before_read_action
    assert ".play()" not in dom_ready
    assert "fetch(" in script
    assert "/api/companion/note/save" not in script
    assert "/api/panel/checkbox-projection" not in script
    assert "/api/companion/tts/plan" in script


def test_tts_proposal_readback_uses_stable_field_order() -> None:
    html = _html()
    script = _readback_script(html)

    assert (
        "['decision', 'recommendation', 'why', 'risk', 'source', 'choices', 'status']"
        in script
    )
    assert 'data-panel-decision-field="decision"' in html
    assert 'data-panel-decision-field="recommendation"' in html
    assert 'data-panel-decision-field="why"' in html
    assert 'data-panel-decision-field="risk"' in html
    assert 'data-panel-decision-field="source"' in html
    assert 'data-panel-decision-field="choices"' in html
    assert 'data-panel-decision-field="status"' in html


def test_tts_draft_readback_reads_editor_textarea_without_save() -> None:
    html = _html()
    script = _readback_script(html)

    assert "document.getElementById('note-source-editor')" in script
    assert "String(editor.value || '')" in script
    assert 'data-tts-action="read-draft"' in html
    assert "noteEditor.save" not in script


def test_tts_readback_does_not_present_summary_as_source_audio() -> None:
    html = _html()
    script = _readback_script(html)

    assert 'data-tts-action="read-summary"' not in html
    assert "summary" not in script.lower()
    assert 'data-source-scope="source-and-proposal"' in html
