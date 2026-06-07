from __future__ import annotations

from companion_ui.panel.summary_projection import (
    SourcePreservingSummaryFixture,
    render_source_preserving_summary_review,
)


def _fixture(**overrides) -> SourcePreservingSummaryFixture:
    data = {
        "source_id": "source-1",
        "source_ref": "notes/source.md#claim-1",
        "source_fact": "The source states that summaries are access aids.",
        "agent_interpretation": "The agent infers that confirmation requires source review.",
        "summary_text": "Summaries help review but do not replace the source.",
        "anchor_limitation": None,
        "signal_labels": ["source_fact", "agent_interpretation"],
    }
    data.update(overrides)
    return SourcePreservingSummaryFixture(**data)


def test_fixtures_distinguish_source_fact_from_agent_interpretation() -> None:
    html = render_source_preserving_summary_review(_fixture())

    assert 'data-testid="summary-source-fact"' in html
    assert "The source states" in html
    assert 'data-testid="summary-agent-interpretation"' in html
    assert "The agent infers" in html


def test_summary_projection_is_marked_non_authoritative() -> None:
    html = render_source_preserving_summary_review(_fixture())

    assert 'data-authority="non-authoritative-projection"' in html
    assert 'data-testid="summary-projection-text"' in html


def test_source_anchor_limitations_are_visible_when_claim_review_degrades() -> None:
    html = render_source_preserving_summary_review(
        _fixture(source_id=None, source_ref=None, anchor_limitation="No claim-level source anchor supplied.")
    )

    assert 'data-posture="degraded-source-anchor-limited"' in html
    assert "No claim-level source anchor supplied." in html


def test_governed_confirmation_cannot_proceed_from_summary_only_context() -> None:
    html = render_source_preserving_summary_review(
        _fixture(source_id=None, source_ref=None, anchor_limitation="Summary-only context.")
    )

    assert 'data-testid="summary-confirm-affordance"' in html
    assert 'data-affordance-status="unavailable"' in html
    assert "/api/panel/checkbox-projection" not in html


def test_source_first_review_appears_before_confirmation() -> None:
    html = render_source_preserving_summary_review(_fixture())

    assert html.index('data-testid="summary-source-first"') < html.index(
        'data-testid="summary-confirm-affordance"'
    )


def test_summary_readback_is_not_presented_as_source_audio() -> None:
    html = render_source_preserving_summary_review(_fixture())

    assert 'data-tts-action="read-summary"' in html
    assert 'data-source-scope="summary-projection"' in html
    assert 'data-source-audio="false"' in html
