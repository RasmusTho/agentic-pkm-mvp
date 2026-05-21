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
    assert 'data-testid="resurface-candidate-label"' in html
    assert 'data-affordance-status="read-only"' in html
    assert 'data-runtime-backed="true"' in html
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


def test_resurface_actions_marked_read_only_or_unavailable_without_persistence() -> None:
    html = _render_resurface()

    assert 'data-testid="resurface-mode"' in html
    assert 'data-affordance-status="read-only"' in html
    assert 'data-testid="resurface-action-dismiss"' in html
    assert 'data-testid="resurface-action-snooze"' in html
    assert 'data-testid="resurface-action-pin"' in html
    assert html.count('data-affordance-status="unavailable"') >= 3
    assert html.count('data-runtime-backed="false"') >= 3
    assert html.count('data-persistence-backed="false"') >= 3
    assert "Dismiss unavailable" in html
    assert "Snooze unavailable" in html
    assert "Pin unavailable" in html
    assert "no persistence" in html


def test_relation_to_active_artifact() -> None:
    html = _render_resurface()

    assert 'data-testid="resurface-relation"' in html
    assert "Evaluated while Notes/resurface.md is active." in html
    assert 'data-testid="resurface-source-link"' in html
    assert "status.worker_queue" in html


def test_workspace_resurface_source_link_uses_logical_identifier(
    monkeypatch,
    tmp_path,
) -> None:
    from app.api.routes import companion
    from app.resurfacing.runtime import (
        ResurfacingCandidate,
        ResurfacingEvaluation,
        ResurfacingSignal,
        ResurfacingWhyNow,
    )

    note = tmp_path / "Notes" / "resurface.md"
    note.parent.mkdir()
    note.write_text("---\nuuid: note-1142\n---\n# Resurface Note\n", encoding="utf-8")

    monkeypatch.setattr(companion, "resolve_vault_root", lambda: tmp_path)
    monkeypatch.setattr(
        companion,
        "evaluate_resurfacing_candidates",
        lambda: ResurfacingEvaluation(
            generated_at="2026-05-21T00:00:00Z",
            status_summary="resurfacing_candidates=1",
            candidates=[
                ResurfacingCandidate(
                    candidate_id="resurface-worker-queue",
                    label="Queued runtime work remains unresolved",
                    why_now=ResurfacingWhyNow(
                        explanation="Worker queue has unresolved pending items.",
                        signals=[
                            ResurfacingSignal(
                                name="worker_queue_pending",
                                value=2,
                                source="postgresql://user:secret@example/app",
                            )
                        ],
                    ),
                )
            ],
        ),
    )

    response = companion.read_companion_workspace(note_path="Notes/resurface.md")

    candidate = response.runtime.resurface["candidates"][0]
    assert candidate["source_link"] == "status.worker_queue"
    assert "secret" not in str(candidate)


class _EmptyResurfaceClient:
    def __init__(self, *, degraded: bool = False) -> None:
        self.degraded = degraded

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        assert url == "/api/companion/workspace"
        assert params == {"note_path": "Notes/resurface.md"}
        return {
            "artifact": {
                "artifact_id": "art-1186",
                "note_path": "Notes/resurface.md",
                "title": "Resurface Note",
                "body": "# Resurface Note",
                "content_hash": "hash-resurface-empty",
            },
            "canvas": {"session_state": "idle", "can_edit_body": False},
            "panel": {"state": "idle", "proposal_count": 0},
            "guards": {
                "canvas_enabled": True,
                "writeguard_status": "ok",
                "degraded": self.degraded,
            },
            "runtime": {"resurface": {"candidates": []}},
            "suggestions": {},
        }


def _render_empty_resurface(*, degraded: bool = False) -> str:
    page = RealNoteWorkspaceDevPage(_EmptyResurfaceClient(degraded=degraded))  # type: ignore[arg-type]
    state = page.load(NoteLoadIntent(note_path="Notes/resurface.md"))
    assert state.is_loaded is True
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/resurface.md",
        fields=fields,
    )


def test_resurface_empty_state_is_visible() -> None:
    html = _render_empty_resurface()

    assert 'data-testid="resurface-mode"' in html
    assert 'data-testid="resurface-empty-state"' in html
    assert 'data-affordance-status="read-only"' in html
    assert "No Resurface candidates are available" in html
    assert "Nothing needs action" in html


def test_resurface_degraded_state_is_visible() -> None:
    html = _render_empty_resurface(degraded=True)

    assert 'data-testid="resurface-mode"' in html
    assert 'data-testid="resurface-degraded-state"' in html
    assert 'data-affordance-status="unavailable"' in html
    assert "runtime reported degraded guard state" in html
