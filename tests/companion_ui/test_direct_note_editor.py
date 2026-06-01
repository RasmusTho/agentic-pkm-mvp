"""Direct human note editor UI (Read <-> Edit, native spellcheck).

The note carries an always-available plain-textarea editor, independent of the
Canvas/update flow. Edit mode swaps the rendered body for the raw (frontmatter-
stripped) source in a ``<textarea spellcheck>`` (OS-grade spellcheck), and Save
POSTs to the same-origin ``/api/companion/note/save`` proxy.
"""

from __future__ import annotations

from companion_ui.workspace.serve_dev_page import render_index_html


def _fields(*, body: str, canvas_enabled: bool, content_hash: str = "hash-1") -> dict:
    return {
        "title": "Editor Note",
        "note_path": "notes/editor.md",
        "artifact_id": "art-ed-1",
        "content_hash": content_hash,
        "body": body,
        "guard_writeguard_status": "ok",
        "guard_canvas_enabled": canvas_enabled,
        "guard_degraded": not canvas_enabled,
        "guard_workspace_update_available": canvas_enabled,
        "guard_update_flow_available": canvas_enabled,
        "runtime_vault_provenance": "resolved",
        "runtime_vault_name": "V",
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
        "dev_page_label": "dev",
        "workspace_loaded_at": None,
    }


def _render(*, body: str = "---\ntitle: T\nuuid: u\n---\n# Head\n\nBody text.\n", canvas_enabled: bool = False, **kw) -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/editor.md",
        fields=_fields(body=body, canvas_enabled=canvas_enabled, **kw),
    )


def test_editor_present_when_canvas_disabled() -> None:
    # The whole point: editing works even with Canvas off (no ceremony).
    html = _render(canvas_enabled=False)
    assert 'data-testid="workspace-note-source-editor"' in html
    assert 'data-testid="workspace-note-edit-toggle"' in html
    assert 'data-testid="workspace-note-edit-save"' in html
    assert 'data-testid="workspace-note-edit-cancel"' in html


def test_editor_present_when_canvas_enabled() -> None:
    html = _render(canvas_enabled=True)
    assert 'data-testid="workspace-note-source-editor"' in html


def test_editor_has_native_spellcheck() -> None:
    html = _render()
    # Native browser/OS spellcheck — the state-of-the-art path (impossible in CM).
    assert 'spellcheck="true"' in html
    assert 'autocapitalize="sentences"' in html
    assert 'autocorrect="on"' in html


def test_editor_carries_frontmatter_stripped_source_and_hash() -> None:
    html = _render(
        body="---\ntitle: T\nuuid: secret-uuid\n---\n# Head\n\nBody text.\n",
        content_hash="hash-xyz",
    )
    editor = html.split('data-testid="workspace-note-source-editor"', 1)[1].split("</textarea>", 1)[0]
    # The editor shows the body, never the frontmatter (save preserves it).
    assert "# Head" in editor
    assert "Body text." in editor
    assert "secret-uuid" not in editor
    assert "title: T" not in editor
    # Optimistic-concurrency token + target path for the save call.
    assert 'data-content-hash="hash-xyz"' in editor
    assert 'data-note-path="notes/editor.md"' in editor


def test_editor_js_saves_to_note_save_endpoint() -> None:
    html = _render()
    assert "window.noteEditor" in html
    assert "/api/companion/note/save" in html


def test_no_edit_disabled_nag() -> None:
    html = _render(canvas_enabled=False)
    assert "Editing is not enabled in this workspace" not in html


def test_editor_strips_url_fragment_from_note_path() -> None:
    # #1447 — the save call strips any #section anchor from the note identity.
    html = _render()
    assert ".split('#')[0]" in html


def test_editor_shows_human_error_copy_not_raw_json() -> None:
    # #1447 — failures map to human-readable copy; raw JSON is not surfaced and
    # the runtime-route-missing (deploy skew) case gets specific guidance.
    html = _render()
    assert "needs the latest build" in html  # route-missing / deploy-skew case
    assert "Note not found for: " in html
    assert "writes blocked" in html
    assert "JSON.parse(d.message)" in html
    assert "wrapped.detail || wrapped" in html
    assert "console.error('note save failed'" in html  # raw detail kept inspectable
    # The old behaviour ('Save failed: ' + raw JSON message) is gone.
    assert "'Save failed: ' + msg" not in html


def test_no_canvas_off_readonly_pill() -> None:
    # #1447 — editing is always available, so the misleading read-only pill is
    # suppressed (canvas disabled no longer implies read-only).
    html = _render(canvas_enabled=False)
    assert 'data-testid="workspace-read-only-pill"' not in html


def test_page_server_proxies_note_save() -> None:
    # The page server must proxy the human-save path to the runtime (same-origin).
    from companion_ui.workspace import serve_dev_page as mod

    source = (mod.__file__)
    text = open(source, encoding="utf-8").read()
    assert '"/api/companion/note/save"' in text
    assert "_POST_PROXY_PATHS" in text
