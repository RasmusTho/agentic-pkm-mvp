from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.briefing.compose import (
    BriefingNote,
    BriefingReadError,
    BriefingSection,
    CommitmentBriefingItem,
    MomentBriefingItem,
)
from app.briefing.surface import collect_day_start_briefing
from app.vault.manager import VaultContext
from companion_ui.workspace.day_start_card import render_day_start_card_html


TODAY = date(2026, 7, 11)


def _context(tmp_path: Path) -> VaultContext:
    vault = tmp_path / "vault"
    vault.mkdir()
    return VaultContext(status="selected", active_vault_path=str(vault))


def _full_projection() -> dict[str, object]:
    return {
        "state": "full",
        "date": TODAY.isoformat(),
        "preview": "Reply to Anna",
        "degraded_sections": [],
        "read_only": True,
        "reason": None,
        "sections": [
            {
                "name": "commitments",
                "status": "available",
                "reason": None,
                "items": [
                    {
                        "summary": "Reply to Anna",
                        "artifact_path": "_system/commitments/c-1.md",
                        "target_ref": "Projects/Launch.md",
                    }
                ],
            },
            {
                "name": "moments",
                "status": "available",
                "reason": None,
                "items": [
                    {
                        "title": "Review launch decision",
                        "artifact_path": "_system/moments/m-1.md",
                        "surfaced_refs": [
                            {"ref": "Decisions/Launch.md", "why": "due today"}
                        ],
                    }
                ],
            },
        ],
    }


def test_day_start_card_renders_todays_briefing() -> None:
    html = render_day_start_card_html(_full_projection(), tts_available=True)

    assert 'data-testid="day-start-card"' in html
    assert 'data-briefing-state="full"' in html
    assert TODAY.isoformat() in html
    assert "Reply to Anna" in html
    assert 'data-testid="day-start-listen"' not in html
    assert 'data-testid="briefing-listen"' in html
    assert 'data-testid="day-start-read"' in html
    assert "Projects/Launch.md" in html
    assert "Decisions/Launch.md" in html


def test_day_start_card_has_no_text_input_affordances() -> None:
    html = render_day_start_card_html(_full_projection(), tts_available=True).lower()

    assert "<input" not in html
    assert "<textarea" not in html
    assert "contenteditable" not in html
    assert 'type="text"' not in html


def test_missing_todays_briefing_shows_pending_state_not_blank(tmp_path: Path) -> None:
    with patch("app.briefing.surface.load_briefing", return_value=None):
        projection = collect_day_start_briefing(
            vault_context=_context(tmp_path), for_date=TODAY
        )
    html = render_day_start_card_html(projection)

    assert projection["state"] == "pending"
    assert 'data-briefing-state="pending"' in html
    assert "isn't ready yet" in html
    assert "2026-07-10" not in html


def test_degraded_briefing_distinguished_from_pending_and_full(tmp_path: Path) -> None:
    note = BriefingNote(
        briefing_date=TODAY,
        degraded_sections=("decision_receipts",),
        sections={
            "commitments": BriefingSection(
                status="available",
                items=(
                    CommitmentBriefingItem(
                        commitment_id="c-1",
                        commitment_kind="next_action",
                        state="open",
                        summary="Reply to Anna",
                        artifact_path="_system/commitments/c-1.md",
                    ),
                ),
            ),
            "moments": BriefingSection(
                status="available",
                items=(
                    MomentBriefingItem(
                        moment_id="m-1",
                        title="Review launch",
                        need_basis="deadline",
                        urgency_band="today",
                        artifact_path="_system/moments/m-1.md",
                        surfaced_refs=({"ref": "Projects/Launch.md", "why": "today"},),
                    ),
                ),
            ),
            "decision_receipts": BriefingSection(
                status="degraded", items=(), reason="source_read_failed"
            ),
        },
    )
    with patch("app.briefing.surface.load_briefing", return_value=note):
        projection = collect_day_start_briefing(
            vault_context=_context(tmp_path), for_date=TODAY
        )
    degraded = render_day_start_card_html(projection)
    pending = render_day_start_card_html({"state": "pending", "date": TODAY.isoformat()})
    full = render_day_start_card_html(_full_projection())

    assert 'data-briefing-state="degraded"' in degraded
    assert 'data-testid="day-start-degraded"' in degraded
    assert "decision receipts unavailable" in degraded
    assert 'data-testid="day-start-degraded"' not in pending
    assert 'data-testid="day-start-degraded"' not in full


def test_day_start_card_is_read_only() -> None:
    html = render_day_start_card_html(_full_projection(), tts_available=False)

    assert 'data-authority="read-only-projection"' in html
    assert 'data-read-only="true"' in html
    for forbidden in (
        "/transition",
        "/complete",
        "/delete",
        "noteEditor.save",
        "commitment.apply",
        "method=\"post\"",
    ):
        assert forbidden not in html


def test_unreadable_briefing_is_not_reported_as_pending(tmp_path: Path) -> None:
    with patch(
        "app.briefing.surface.load_briefing",
        side_effect=BriefingReadError("bad schema"),
    ):
        projection = collect_day_start_briefing(
            vault_context=_context(tmp_path), for_date=TODAY
        )
    html = render_day_start_card_html(projection)

    assert projection["state"] == "unreadable"
    assert 'data-briefing-state="unreadable"' in html
    assert "cannot be read" in html
    assert "isn't ready yet" not in html
