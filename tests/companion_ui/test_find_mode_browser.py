"""Tests for Find mode rendering in the Companion workspace shell (#1140)."""

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
        assert params == {"note_path": "Notes/find.md"}
        return {
            "artifact": {
                "artifact_id": "art-1140",
                "note_path": "Notes/find.md",
                "title": "Find Note",
                "body": "# Find Note",
                "content_hash": "hash-find",
            },
            "canvas": {"session_state": "idle", "can_edit_body": False},
            "panel": {"state": "idle", "proposal_count": 0},
            "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
            "runtime": {
                "find": {
                    "scope": "active-project",
                    "candidates": [
                        {
                            "candidate_id": "cand-1",
                            "title": "Project brief",
                            "snippet": "Relevant source excerpt.",
                            "citation": "Notes/project-brief.md#L12",
                            "scope": "project",
                            "why": "Matched the active artifact title and project tag.",
                            "panel_handoff": True,
                        }
                    ],
                }
            },
            "suggestions": {},
        }


def _render_find() -> str:
    page = RealNoteWorkspaceDevPage(_FakeClient())  # type: ignore[arg-type]
    state = page.load(NoteLoadIntent(note_path="Notes/find.md"))
    assert state.is_loaded is True
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/find.md",
        fields=fields,
    )


def test_candidates_with_explanations() -> None:
    html = _render_find()

    assert 'data-testid="find-mode"' in html
    assert 'data-testid="find-candidate"' in html
    assert 'data-affordance-status="read-only"' in html
    assert 'data-runtime-backed="true"' in html
    assert "Project brief" in html
    assert 'data-testid="find-candidate-why"' in html
    assert "Matched the active artifact title and project tag." in html


def test_candidate_citation_and_scope() -> None:
    html = _render_find()

    assert 'data-testid="find-candidate-citation"' in html
    assert 'data-citation-state="available"' in html
    assert "Notes/project-brief.md#L12" in html
    assert 'data-testid="find-candidate-scope"' in html
    assert "project" in html


def test_panel_handoff() -> None:
    html = _render_find()

    assert 'data-testid="find-panel-handoff"' in html
    assert 'data-intent="find.panelHandoff"' in html
    assert 'data-affordance-status="unavailable"' in html
    assert 'data-runtime-backed="false"' in html
    assert "Panel unavailable" in html


class _NoFindPayloadClient:
    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        assert url == "/api/companion/workspace"
        assert params == {"note_path": "Notes/find.md"}
        return {
            "artifact": {
                "artifact_id": "art-1140",
                "note_path": "Notes/find.md",
                "title": "Find Note",
                "body": "# Find Note",
                "content_hash": "hash-find",
            },
            "canvas": {"session_state": "idle", "can_edit_body": False},
            "panel": {"state": "idle", "proposal_count": 0},
            "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
            "runtime": {},
            "suggestions": {},
        }


def test_find_unavailable_state_renders_without_backend_payload() -> None:
    page = RealNoteWorkspaceDevPage(_NoFindPayloadClient())  # type: ignore[arg-type]
    state = page.load(NoteLoadIntent(note_path="Notes/find.md"))
    assert state.is_loaded is True
    fields = page.render_fields()
    assert fields is not None

    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/find.md",
        fields=fields,
    )

    assert 'data-testid="find-mode"' in html
    assert 'data-testid="find-unavailable-state"' in html
    assert 'data-affordance-status="unavailable"' in html
    assert "Find is unavailable" in html


class _EmptyFindPayloadClient:
    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        assert url == "/api/companion/workspace"
        assert params == {"note_path": "Notes/find.md"}
        return {
            "artifact": {
                "artifact_id": "art-1187-empty",
                "note_path": "Notes/find.md",
                "title": "Find Note",
                "body": "# Find Note",
                "content_hash": "hash-find-empty",
            },
            "canvas": {"session_state": "idle", "can_edit_body": False},
            "panel": {"state": "idle", "proposal_count": 0},
            "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
            "runtime": {"find": {"scope": "active-project", "candidates": []}},
            "suggestions": {},
        }


def test_find_empty_state_distinct_from_unavailable() -> None:
    page = RealNoteWorkspaceDevPage(_EmptyFindPayloadClient())  # type: ignore[arg-type]
    state = page.load(NoteLoadIntent(note_path="Notes/find.md"))
    assert state.is_loaded is True
    fields = page.render_fields()
    assert fields is not None

    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/find.md",
        fields=fields,
    )

    assert 'data-testid="find-mode"' in html
    assert 'data-testid="find-empty-state"' in html
    assert 'data-testid="find-unavailable-state"' not in html
    assert 'data-affordance-status="read-only"' in html
    assert "Find returned no candidates" in html


class _MissingCitationFindClient:
    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        assert url == "/api/companion/workspace"
        assert params == {"note_path": "Notes/find.md"}
        return {
            "artifact": {
                "artifact_id": "art-1187-uncited",
                "note_path": "Notes/find.md",
                "title": "Find Note",
                "body": "# Find Note",
                "content_hash": "hash-find-uncited",
            },
            "canvas": {"session_state": "idle", "can_edit_body": False},
            "panel": {"state": "idle", "proposal_count": 0},
            "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
            "runtime": {
                "find": {
                    "scope": "active-project",
                    "candidates": [
                        {
                            "candidate_id": "uncited-1",
                            "title": "Uncited source",
                            "snippet": "Relevant but uncited.",
                            "why_this_source": "Runtime supplied a candidate without a citation.",
                            "panel_handoff_status": "read-only",
                        }
                    ],
                }
            },
            "suggestions": {},
        }


def test_find_missing_citation_is_marked_clearly() -> None:
    page = RealNoteWorkspaceDevPage(_MissingCitationFindClient())  # type: ignore[arg-type]
    state = page.load(NoteLoadIntent(note_path="Notes/find.md"))
    assert state.is_loaded is True
    fields = page.render_fields()
    assert fields is not None

    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/find.md",
        fields=fields,
    )

    assert 'data-testid="find-candidate-citation"' in html
    assert 'data-citation-state="missing"' in html
    assert "uncited" in html
    assert 'data-affordance-status="read-only"' in html
    assert "Panel read-only" in html
