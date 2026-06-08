from __future__ import annotations

from companion_ui.workspace.serve_dev_page import (
    _correction_proposals_for_editor,
    render_index_html,
)


def _fields(*, body: str = "# Draft\n\nI will recieve the form tomorrow.\n") -> dict:
    return {
        "title": "Correction Note",
        "note_path": "notes/correction.md",
        "artifact_id": "art-correction",
        "content_hash": "hash-correction",
        "body": body,
        "guard_writeguard_status": "ok",
        "guard_canvas_enabled": True,
        "guard_degraded": False,
        "guard_workspace_update_available": True,
        "guard_update_flow_available": True,
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


def _html() -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/correction.md",
        fields=_fields(),
    )


def _note_editor_script(html: str) -> str:
    start = html.index("window.noteEditor")
    end = html.index("</script>", start)
    return html[start:end]


def test_correction_proposal_surface_is_ui_internal() -> None:
    html = _html()

    assert 'data-testid="text-correction-proposals"' in html
    assert 'data-authority="proposal-class-ui-internal"' in html
    assert 'data-backend-api="none"' in html
    assert "/api/companion/text-corrections" not in html


def test_correction_proposal_fields_are_visible() -> None:
    html = _html()

    assert 'data-testid="text-correction-original"' in html
    assert ">recieve<" in html
    assert 'data-testid="text-correction-proposed"' in html
    assert ">receive<" in html
    assert 'data-testid="text-correction-tier"' in html
    assert 'data-testid="text-correction-reason"' in html
    assert 'data-testid="text-correction-meaning-cue"' in html
    assert 'data-correction-action="keep-mine"' in html


def test_accepting_correction_updates_draft_without_save() -> None:
    html = _html()
    script = _note_editor_script(html)
    accept_block = script[script.index("applyCorrection"): script.index("keepCorrection")]

    assert "ta.value.slice(0, start) + proposed + ta.value.slice(end)" in accept_block
    assert "ta.dataset.correctionReviewState = 'accepted'" in accept_block
    assert "fetch(" not in accept_block
    assert "/api/companion/note/save" not in accept_block


def test_canonical_save_remains_explicit_note_save() -> None:
    html = _html()
    script = _note_editor_script(html)

    assert "save: function ()" in script
    assert "fetch('/api/companion/note/save'" in script
    assert 'data-correction-action="accept"' in html
    assert 'data-testid="workspace-note-edit-save"' in html
    assert 'onclick="noteEditor.save()"' in html


def test_real_word_flags_are_never_auto_applied() -> None:
    html = _html()

    assert 'data-correction-tier="1"' in html
    assert "real-word/context flag" in html
    assert 'data-auto-apply="false"' in html
    assert "possibly `from`" in html


def test_real_word_correction_matches_only_whole_words() -> None:
    proposals = _correction_proposals_for_editor("Platform forms are valid, but form may be from.")

    assert [proposal["original_text"] for proposal in proposals] == ["form"]
    assert proposals[0]["range"] == {"start": 30, "end": 34}


def test_readback_targets_actual_draft_after_correction_review() -> None:
    html = _html()
    readback_start = html.index("function draftText")
    readback_end = html.index("function readText", readback_start)
    readback = html[readback_start:readback_end]

    assert "document.getElementById('note-source-editor')" in readback
    assert "String(editor.value || '')" in readback
    assert 'data-testid="workspace-note-edit-read-draft"' in html
