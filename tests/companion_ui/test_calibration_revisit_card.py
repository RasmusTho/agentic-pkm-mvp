"""SSR contracts for the CAL-03 visual-pick revisit card."""

from __future__ import annotations

from typing import Any

from companion_ui.workspace.serve_dev_page import render_index_html


def _fields(surface: object) -> dict[str, Any]:
    return {
        "title": "Note Title",
        "note_path": "Notes/note.md",
        "artifact_id": "art-123",
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": "sha256-aaa",
        "body": "# Note\n\nBody content here.",
        "runtime_environment_label": "dev",
        "runtime_api_base_url_label": "local-dev",
        "runtime_trace_id": "trace-1",
        "runtime_vault_name": "vault/dev",
        "runtime_vault_channel": "local-dev",
        "runtime_vault_provenance": "resolved",
        "canvas_session_state": "idle",
        "canvas_session_persistence": "in_memory",
        "panel_state": "idle",
        "panel_proposal_count": 0,
        "panel_proposals": [],
        "panel_message": "",
        "panel_last_response": {},
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
        "calibration_revisit": surface,
    }


def _render(surface: object) -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/note.md",
        fields=_fields(surface),
    )


def _pending() -> dict[str, object]:
    return {
        "state": "pending",
        "decision_id": "8f2e-fixture",
        "title": "Postgres as projection, not source of truth",
        "decided_on": "2026-06-23",
        "rung_days": 14,
        "degraded": False,
    }


def test_answer_submits_without_typing() -> None:
    html = _render(_pending())

    assert 'data-testid="calibration-revisit-card"' in html
    assert 'data-state="pending"' in html
    assert 'action="/api/companion/calibration/revisits/8f2e-fixture/decision"' in html
    assert 'name="outcome" value="held"' in html
    assert 'name="outcome" value="partly_held"' in html
    assert 'name="outcome" value="did_not_hold"' in html
    assert 'name="outcome" value="unknown_yet"' in html
    assert 'name="note"' in html
    assert "if (note && note.value.trim()) body.note = note.value.trim();" in html
    assert 'name="rung_index"' in html
    assert "Workspace reread unavailable." in html
    assert "result.data.status !== expectedStatus" in html


def test_answer_and_dismiss_are_visually_distinct() -> None:
    html = _render(_pending())

    assert 'form class="cal-answer"' in html
    assert 'form class="cal-foot"' in html
    assert 'data-intent="answer"' in html
    assert 'data-intent="dismiss"' in html
    assert 'class="cal-dismiss"' in html
    assert 'action="/api/companion/calibration/revisits/8f2e-fixture/dismiss"' in html
    assert "Dismiss for now" in html
    assert "Records no outcome." in html


def test_degraded_or_absent_revisit_renders_safely() -> None:
    degraded = _render({"state": "degraded", "degraded": True})
    absent = _render(None)

    assert 'data-state="degraded"' in degraded
    assert "Pending revisits are unknown, not zero." in degraded
    assert 'data-state="absent"' in absent
    assert "revisit state unavailable" in absent
    assert "Pending revisits are unknown, not zero." in absent
    assert "pending decisions: 0" not in absent.lower()
