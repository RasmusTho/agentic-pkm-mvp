"""Tests for Act mode rendering in the Companion workspace shell (#1143)."""

from __future__ import annotations

from typing import Any

from companion_ui.workspace.real_note_workspace_dev_page import (
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)
from companion_ui.workspace.serve_dev_page import render_index_html


class _FakeClient:
    def __init__(self, *, receipt: bool = False) -> None:
        self._receipt = receipt

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        assert url == "/api/companion/workspace"
        assert params == {"note_path": "Notes/act.md"}
        panel: dict[str, Any] = {
            "state": "proposals-staged",
            "proposal_count": 1,
            "proposals": [
                {
                    "proposal_id": "proposal-1143",
                    "artifact_id": "art-1143",
                    "description": "Promote this note to evergreen.",
                    "evidence": {
                        "trigger_summary": "Frontmatter maturity is seed.",
                        "action_class": "promotion",
                        "cognition_route": "rule",
                    },
                    "affordances": ["confirm", "correct", "reject"],
                    "status": "staged",
                }
            ],
        }
        return {
            "artifact": {
                "artifact_id": "art-1143",
                "note_path": "Notes/act.md",
                "title": "Act Note",
                "body": "# Act Note",
                "content_hash": "hash-act",
            },
            "canvas": {"session_state": "idle", "can_edit_body": False},
            "panel": panel,
            "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
            "runtime": {},
            "suggestions": {},
        }


def _render_act(*, response: dict[str, Any] | None = None) -> str:
    page = RealNoteWorkspaceDevPage(_FakeClient())  # type: ignore[arg-type]
    state = page.load(NoteLoadIntent(note_path="Notes/act.md"))
    assert state.is_loaded is True
    state.panel_last_response = response
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/act.md",
        fields=fields,
    )


def test_proposal_review_with_context() -> None:
    html = _render_act()

    assert 'data-testid="act-mode"' in html
    assert 'data-testid="act-proposal-review"' in html
    assert 'data-testid="act-action-bundle-context"' in html
    assert "Promote this note to evergreen." in html
    assert "Frontmatter maturity is seed." in html
    assert "promotion" in html
    assert "rule" in html


def test_apply_uses_panel_confirm() -> None:
    html = _render_act()

    assert 'data-testid="act-confirm"' in html
    assert 'data-api-method="POST"' in html
    assert 'data-api-path="/api/panel/confirm"' in html
    assert 'data-proposal-id="proposal-1143"' in html
    assert 'data-artifact-id="art-1143"' in html


def test_durable_receipt_rendered() -> None:
    html = _render_act(
        response={
            "proposal_id": "proposal-1143",
            "artifact_id": "art-1143",
            "status": "executed",
            "outcome": "success",
            "receipt": {
                "action_taken": "promote",
                "outcome": "success",
                "timestamp": "2026-05-20T20:00:00Z",
                "message": "receipt written",
            },
        }
    )

    assert 'data-testid="act-durable-receipt"' in html
    assert 'data-testid="act-receipt-status"' in html
    assert "executed" in html
    assert "receipt written" in html


def test_no_writeguard_bypass() -> None:
    html = _render_act()

    assert 'data-authority-surface="panel"' in html
    assert 'data-writeguard-bypass="false"' in html
    assert "/api/canvas/sessions" not in html.split('data-testid="act-mode"', 1)[1]
