"""Tests for Reorient mode rendering in the Companion workspace shell (#1141)."""

from __future__ import annotations

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
    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        if is_vault_browser_get(url):
            return default_vault_browser_payload()
        assert url == "/api/companion/workspace"
        assert params == {"note_path": "Notes/reorient.md"}
        return {
            "artifact": {
                "artifact_id": "art-1141",
                "note_path": "Notes/reorient.md",
                "title": "Reorient Note",
                "body": "# Reorient Note",
                "content_hash": "hash-reorient",
            },
            "canvas": {"session_state": "idle", "can_edit_body": False},
            "panel": {"state": "idle", "proposal_count": 0},
            "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
            "runtime": {
                "reorient": {
                    "facts": [
                        {
                            "label": "Last leave-point came from runtime activity.",
                            "source_link": "runtime:orientation#leave-point",
                        }
                    ],
                    "inferences": [
                        {
                            "label": "The active note is likely mid-review.",
                            "source_link": "runtime:orientation#frame",
                        }
                    ],
                    "candidates": [
                        {
                            "label": "Review the next unresolved loop.",
                            "source_link": "runtime:orientation#candidate",
                            "panel_handoff": True,
                        }
                    ],
                    "stale_context": [
                        {
                            "label": "A prior counter snapshot may be stale.",
                            "source_link": "runtime:orientation#stale",
                        }
                    ],
                    "recent_deltas": [
                        {
                            "label": "Ingest counters changed since the last snapshot.",
                            "source_link": "runtime:orientation#deltas",
                        }
                    ],
                    "open_loops": [
                        {
                            "label": "One promotion intent remains open.",
                            "source_link": "runtime:orientation#open-loops",
                            "panel_handoff": True,
                        }
                    ],
                }
            },
            "suggestions": {},
        }


def _render_reorient() -> str:
    page = RealNoteWorkspaceDevPage(_FakeClient())  # type: ignore[arg-type]
    state = page.load(NoteLoadIntent(note_path="Notes/reorient.md"))
    assert state.is_loaded is True
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/reorient.md",
        fields=fields,
    )


def test_orientation_fields_rendered() -> None:
    html = _render_reorient()

    assert 'data-testid="reorient-mode"' in html
    assert 'data-affordance-status="read-only"' in html
    assert 'data-capability="reorient"' in html
    assert 'data-reorient-group="where-am-i"' in html
    assert 'data-reorient-group="what-changed"' in html
    assert 'data-reorient-group="what-next"' in html
    assert "Where am I?" in html
    assert "What changed?" in html
    assert "What next?" in html
    assert 'data-reorient-section="facts"' in html
    assert 'data-reorient-section="inferences"' in html
    assert 'data-reorient-section="candidates"' in html
    assert 'data-reorient-section="stale_context"' in html
    assert 'data-reorient-section="recent_deltas"' in html
    assert 'data-reorient-section="open_loops"' in html
    assert "Last leave-point came from runtime activity." in html
    assert "One promotion intent remains open." in html


def test_reorient_kinds_distinguish_facts_inferences_candidates_and_stale_context() -> None:
    html = _render_reorient()

    assert 'data-reorient-kind="fact"' in html
    assert 'data-reorient-kind="inference"' in html
    assert 'data-reorient-kind="candidate"' in html
    assert 'data-reorient-kind="stale-caution"' in html
    assert 'data-reorient-kind="recent-delta"' in html
    assert 'data-reorient-kind="open-loop"' in html
    assert "Stale context" in html
    assert "Candidates" in html


def test_source_links_present() -> None:
    html = _render_reorient()

    assert html.count('data-testid="reorient-source-link"') == 6
    assert "runtime:orientation#leave-point" in html
    assert "runtime:orientation#open-loops" in html


def test_panel_handoff() -> None:
    html = _render_reorient()

    assert 'data-testid="reorient-panel-handoff"' in html
    assert 'data-intent="reorient.panelHandoff"' in html
    assert 'data-affordance-status="read-only"' in html
    assert 'data-runtime-backed="false"' in html
    assert "Panel handoff candidate" in html


def test_reorient_empty_state_visible() -> None:
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/reorient.md",
        fields={
            "title": "Reorient Note",
            "note_path": "Notes/reorient.md",
            "artifact_id": "art-1141",
            "content_hash": "hash-reorient",
            "body": "# Reorient Note",
            "panel_rail": "Panel ready",
            "reorient_sections": {},
            "guard_canvas_enabled": True,
            "guard_writeguard_status": "ok",
        },
    )

    assert 'data-testid="reorient-empty-state"' in html
    assert "no orientation payload is available" in html


def test_workspace_reorient_failure_degrades_without_blocking_note_load(
    monkeypatch,
    tmp_path,
) -> None:
    from app.api.routes import companion

    note = tmp_path / "Notes" / "reorient.md"
    note.parent.mkdir()
    note.write_text("---\nuuid: note-1141\n---\n# Reorient Note\n", encoding="utf-8")

    monkeypatch.setattr(companion, "resolve_vault_root", lambda: tmp_path)

    def fail_orientation() -> None:
        raise RuntimeError("orientation unavailable")

    monkeypatch.setattr(companion, "build_orientation_frame", fail_orientation)

    response = companion.read_companion_workspace(note_path="Notes/reorient.md")

    assert response.artifact.artifact_id == "note-1141"
    assert response.runtime.reorient["stale_context"][0]["source_link"] == (
        "runtime:orientation#unavailable"
    )
