"""Tests for live workspace suggestion layout and shortcut integration (#1136)."""

from __future__ import annotations

import re
from typing import Any

from companion_ui.workspace.real_note_workspace_dev_page import (
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)
from companion_ui.workspace.serve_dev_page import render_index_html
from tests.companion_ui.vault_browser_test_helpers import (
    default_vault_browser_payload,
    is_vault_browser_get,
)


class _FakeClient:
    def __init__(
        self,
        *,
        suggestion_state: str,
        variant: str = "body",
    ) -> None:
        self.suggestion_state = suggestion_state
        self.variant = variant

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        if is_vault_browser_get(url):
            return default_vault_browser_payload()
        assert url == "/api/companion/workspace"
        assert params == {"note_path": "Notes/canvas.md"}
        return {
            "artifact": {
                "artifact_id": "art-1136",
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
            "suggestions": {
                "current_suggestion_state": self.suggestion_state,
                "proposals": [
                    {
                        "suggestion_id": "s-layout",
                        "server_declared_classification": self.variant,
                        "title": "Suggestion",
                        "preview_text": "Preview",
                        "proposed_text": "# Canvas Note\n\nUpdated.",
                    }
                ],
            },
        }


def _render_workspace(*, suggestion_state: str, variant: str = "body") -> str:
    page = RealNoteWorkspaceDevPage(
        _FakeClient(suggestion_state=suggestion_state, variant=variant)  # type: ignore[arg-type]
    )
    state = page.load(NoteLoadIntent(note_path="Notes/canvas.md"))
    assert state.is_loaded is True
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/canvas.md",
        fields=fields,
    )


def test_desktop_side_rail() -> None:
    html = _render_workspace(suggestion_state="staged_body")

    assert 'data-testid="workspace-agent-rail"' in html
    assert 'data-layout-desktop="side-rail"' in html
    assert "@media (min-width: 900px)" in html


def test_portrait_bottom_sheet() -> None:
    html = _render_workspace(suggestion_state="staged_body")

    assert 'data-testid="portrait-sheet"' in html
    assert 'data-layout-portrait="bottom-sheet"' in html
    assert "@media (max-width: 899px)" in html
    assert 'data-touch-target-min-height="44px"' in html


def test_proposal_arrival_snaps_half() -> None:
    html = _render_workspace(suggestion_state="staged_governance", variant="governance")
    sheet = re.search(r'<aside\s+class="portrait-sheet".*?</aside>', html, re.DOTALL)

    assert sheet is not None
    sheet_html = sheet.group(0)
    assert 'data-current-snap="half"' in html
    assert 'data-auto-snap-target="half"' in html
    assert 'data-forbidden-auto-snap="full"' in html
    assert 'data-current-snap="full"' not in sheet_html


def test_keyboard_shortcuts_staged_only() -> None:
    staged_body = _render_workspace(suggestion_state="staged_body", variant="body")
    idle_body = _render_workspace(suggestion_state="idle", variant="body")
    staged_governance = _render_workspace(
        suggestion_state="staged_governance",
        variant="governance",
    )

    assert 'data-testid="workspace-shortcut-map"' in staged_body
    assert 'data-intent="suggestion.apply" data-key="A"' in staged_body
    assert 'data-intent="governance.queue" data-key="Q"' not in staged_body
    assert 'data-ignore-input-focus="true"' in staged_body

    assert 'data-intent="governance.queue" data-key="Q"' in staged_governance
    assert 'data-intent="suggestion.apply" data-key="A"' not in staged_governance

    assert 'data-intent="suggestion.apply" data-key="A"' not in idle_body
    assert 'data-intent="suggestion.discard" data-key="D"' not in idle_body
