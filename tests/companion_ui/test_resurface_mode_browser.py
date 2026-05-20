"""Tests for Resurface mode rendering in the Companion workspace shell (#1142)."""

from __future__ import annotations

from typing import Any

from companion_ui.workspace.real_note_workspace_dev_page import (
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)
from companion_ui.workspace.serve_dev_page import render_index_html


class _FakeClient:
    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        assert url == "/api/companion/workspace"
        assert params == {"note_path": "Notes/resurface.md"}
        return {
            "artifact": {
                "artifact_id": "art-1142",
                "note_path": "Notes/resurface.md",
                "title": "Resurface Note",
                "body": "# Resurface Note",
                "content_hash": "hash-resurface",
            },
            "canvas": {"session_state": "idle", "can_edit_body": False},
            "panel": {"state": "idle", "proposal_count": 0},
            "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
            "runtime": {
                "resurface": {
                    "candidates": [
                        {
                            "candidate_id": "resurface-1",
                            "label": "Queued runtime work remains unresolved",
                            "why_now": (
                                "Derived relevance changed because the worker queue "
                                "has unresolved pending items."
                            ),
                            "relation_to_active_artifact": (
                                "Evaluated while Notes/resurface.md is active."
                            ),
                            "source_link": "status.worker_queue",
                            "signal_labels": ["worker_queue_pending=2"],
                        }
                    ]
                }
            },
            "suggestions": {},
        }


def _render_resurface() -> str:
    page = RealNoteWorkspaceDevPage(_FakeClient())  # type: ignore[arg-type]
    state = page.load(NoteLoadIntent(note_path="Notes/resurface.md"))
    assert state.is_loaded is True
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/resurface.md",
        fields=fields,
    )


def test_why_now_explanation() -> None:
    html = _render_resurface()

    assert 'data-testid="resurface-mode"' in html
    assert 'data-testid="resurface-candidate"' in html
    assert 'data-testid="resurface-why-now"' in html
    assert "Derived relevance changed" in html
    assert "should act now" not in html.lower()
    assert "urgent" not in html.lower()


def test_dismiss_snooze_pin() -> None:
    html = _render_resurface()

    assert 'data-testid="resurface-action-dismiss"' in html
    assert 'data-testid="resurface-action-snooze"' in html
    assert 'data-testid="resurface-action-pin"' in html
    assert 'data-intent="resurface.dismiss"' in html
    assert 'data-intent="resurface.snooze"' in html
    assert 'data-intent="resurface.pin"' in html


def test_relation_to_active_artifact() -> None:
    html = _render_resurface()

    assert 'data-testid="resurface-relation"' in html
    assert "Evaluated while Notes/resurface.md is active." in html
    assert 'data-testid="resurface-source-link"' in html
    assert "status.worker_queue" in html
