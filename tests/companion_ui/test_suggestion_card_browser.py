"""Tests for runtime suggestion payload cards in the workspace shell (#1133)."""

from __future__ import annotations

from typing import Any

from companion_ui.workspace.real_note_workspace_dev_page import (
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)
from companion_ui.workspace.serve_dev_page import render_index_html


class _FakeClient:
    def __init__(self, suggestions: dict[str, Any]) -> None:
        self.suggestions = suggestions

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "artifact": {
                "artifact_id": "art-1133",
                "note_path": "Notes/canvas.md",
                "title": "Canvas Note",
                "body": "# Canvas Note\n\nBody.",
                "content_hash": "hash-1",
            },
            "canvas": {
                "session_id": "session-1",
                "session_state": "active",
                "user_present": True,
                "can_edit_body": True,
                "recovery_needed": False,
                "session_log_path": ".chats/canvas/session.md",
                "undo_available": False,
                "applied_edit_count": 0,
                "undone_edit_count": 0,
                "session_persistence": "in_memory",
            },
            "panel": {"state": "idle", "proposal_count": 0},
            "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
            "runtime": {},
            "suggestions": self.suggestions,
        }


def _html_for_suggestions(suggestions: dict[str, Any]) -> str:
    page = RealNoteWorkspaceDevPage(_FakeClient(suggestions))  # type: ignore[arg-type]
    state = page.load(NoteLoadIntent(note_path="Notes/canvas.md"))
    assert state.is_loaded is True
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/canvas.md",
        fields=fields,
    )


def test_body_proposal_renders_card_and_insertion() -> None:
    html = _html_for_suggestions(
        {
            "proposals": [
                {
                    "suggestion_id": "s-body",
                    "server_declared_classification": "body",
                    "title": "Add bridge paragraph",
                    "preview_text": "Bridge preview",
                    "anchor_description": "after intro",
                    "proposed_text": "Bridge text.",
                }
            ]
        }
    )

    assert 'data-testid="suggestion-card"' in html
    assert 'data-variant="body"' in html
    assert 'data-intent="suggestion.apply"' in html
    assert 'data-testid="suggested-insertion-block"' in html
    assert 'data-suggestion-id="s-body"' in html
    assert "Bridge text." in html


def test_governance_proposal_no_apply_action() -> None:
    html = _html_for_suggestions(
        {
            "proposals": [
                {
                    "suggestion_id": "s-gov",
                    "server_declared_classification": "governance",
                    "title": "Move note",
                    "preview_text": "lifecycle.move",
                }
            ]
        }
    )

    assert 'data-variant="governance"' in html
    assert 'data-intent="governance.queue"' in html
    assert 'data-intent="suggestion.apply"' not in html
    assert 'data-testid="suggested-insertion-block"' not in html


def test_blocked_proposal_renders_blocked_variant() -> None:
    html = _html_for_suggestions(
        {
            "proposals": [
                {
                    "suggestion_id": "s-blocked",
                    "server_declared_classification": "blocked",
                    "title": "Edit blocked",
                    "preview_text": "blocked",
                    "denial_reason": "Canvas disabled.",
                }
            ]
        }
    )

    assert 'data-variant="blocked"' in html
    assert 'role="alert"' in html
    assert 'data-intent="blocked.acknowledge"' in html
    assert "Canvas disabled." in html


def test_no_reclassification_controls() -> None:
    html = _html_for_suggestions(
        {
            "server_declared_classification": "governance",
            "proposal": {
                "suggestion_id": "s-owned",
                "title": "Queue lifecycle update",
                "preview_text": "frontmatter update",
            },
        }
    )

    lowered = html.lower()
    assert "reclassify" not in lowered
    assert "classification-control" not in lowered


def test_body_proposal_without_text_skips_insertion() -> None:
    html = _html_for_suggestions(
        {
            "proposals": [
                {
                    "suggestion_id": "s-empty",
                    "server_declared_classification": "body",
                    "title": "Metadata-only body proposal",
                }
            ]
        }
    )

    assert 'data-testid="suggestion-card"' in html
    assert 'data-variant="body"' in html
    assert 'data-testid="suggested-insertion-block"' not in html
