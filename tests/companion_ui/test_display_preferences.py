from __future__ import annotations

import re

from companion_ui.workspace.serve_dev_page import render_index_html


def _fields(*, body: str = "# Note\n\nCanonical source paragraph.") -> dict:
    return {
        "title": "Display Note",
        "note_path": "Notes/display.md",
        "artifact_id": "art-display",
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": "sha256-display",
        "body": body,
        "panel_rail": "Panel / agent rail placeholder",
        "runtime_environment_label": "dev",
        "runtime_api_base_url_label": "local-dev",
        "runtime_trace_id": "trace-display",
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


def _html(**field_overrides: object) -> str:
    fields = _fields()
    fields.update(field_overrides)
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/display.md",
        fields=fields,
    )


def _display_preferences_script(html: str) -> str:
    # Slice exactly the shipped display-preference script: from its storage
    # key to the end of its own <script> block. (The previous end marker,
    # `window.noteEditor`, leaked the unrelated read-back script into the
    # slice once it gained network calls.)
    start = html.index("companion.displayPreferences.v1")
    end = html.index("</script>", start)
    return html[start:end]


def test_display_preferences_controls_render_on_note_surface() -> None:
    html = _html()

    assert 'data-testid="display-preferences"' in html
    assert 'data-storage-scope="browser-local"' in html
    assert 'data-authority="render-only"' in html
    assert 'data-testid="display-pref-font-size"' in html
    assert 'data-testid="display-pref-line-height"' in html
    assert 'data-testid="display-pref-reading-width"' in html
    assert 'data-testid="display-pref-focus-mode"' in html
    assert 'value="16px"' in html
    assert 'value="1.65"' in html
    assert 'value="68ch"' in html


def test_display_preferences_are_local_storage_and_css_only() -> None:
    html = _html()
    script = _display_preferences_script(html)

    assert "window.localStorage" in script
    assert "localStorage.setItem(storageKey" in script
    assert "--display-font-size" in html
    assert "--display-line-height" in html
    assert "--display-reading-width" in html
    assert "display-pref-focus" in html
    assert "fetch(" not in script
    assert "/api/companion/note/save" not in script
    assert "/api/panel/checkbox-projection" not in script


def test_display_preferences_preserve_canonical_body_and_content_hash() -> None:
    html = _html(body="# Note\n\nCanonical source paragraph.")

    rendered = re.search(
        r'<div class="note-body-content"[^>]*data-testid="workspace-note-rendered"'
        r'[^>]*data-content-hash="sha256-display"[^>]*>(.*?)</div>',
        html,
        re.S,
    )
    assert rendered, "rendered note body must carry the server content hash"
    assert "Canonical source paragraph." in rendered.group(1)
    assert 'data-content-hash="sha256-display"' in html
    assert 'data-note-path="Notes/display.md"' in html


def test_focus_mode_is_visual_only_and_does_not_delete_authority_regions() -> None:
    html = _html()

    assert 'data-region="vault-browser-pane"' in html
    assert 'data-region="agent-rail"' in html
    assert 'data-testid="workspace-runtime-telemetry"' in html
    focus_rule = re.search(
        r"body\.display-pref-focus \.vault-browser-left-pane,\s*"
        r"body\.display-pref-focus \.agent-rail\s*\{([^}]*)\}",
        html,
        re.S,
    )
    assert focus_rule, "focus mode must be a local visual class"
    assert "opacity:" in focus_rule.group(1)
    assert "display:" not in focus_rule.group(1)
