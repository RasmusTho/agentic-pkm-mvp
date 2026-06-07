from __future__ import annotations

from dataclasses import dataclass, field
from html import escape


@dataclass(frozen=True)
class SourcePreservingSummaryFixture:
    source_id: str | None
    source_ref: str | None
    source_fact: str
    agent_interpretation: str
    summary_text: str
    anchor_limitation: str | None = None
    source_audio_available: bool = False
    summary_audio_available: bool = True
    signal_labels: list[str] = field(default_factory=list)


def render_source_preserving_summary_review(fixture: SourcePreservingSummaryFixture) -> str:
    """Render a source-first summary review fixture.

    This is a deterministic regression surface for the cognitive-load summary
    boundary. It models the review posture without generating summaries or
    changing confirmation APIs.
    """

    source_available = bool(fixture.source_id and fixture.source_ref and not fixture.anchor_limitation)
    posture = "source-backed" if source_available else "degraded-source-anchor-limited"
    confirm_state = "unavailable" if not source_available else "source-review-required"
    signals = "".join(
        f'<span class="summary-signal">{escape(str(signal))}</span>'
        for signal in fixture.signal_labels
    )
    limitation = fixture.anchor_limitation or "Source identity is present; compare before confirming."
    source_ref = fixture.source_ref or "source identity unavailable"
    return f"""
    <section class="source-summary-review"
      data-testid="source-preserving-summary-review"
      data-authority="non-authoritative-projection"
      data-posture="{posture}"
      data-source-id="{escape(str(fixture.source_id or ''))}">
      <div class="summary-source-first" data-testid="summary-source-first">
        <span>Source</span>
        <code>{escape(source_ref)}</code>
      </div>
      <dl class="summary-review-fields">
        <dt>Source fact</dt>
        <dd data-testid="summary-source-fact">{escape(fixture.source_fact)}</dd>
        <dt>Agent interpretation</dt>
        <dd data-testid="summary-agent-interpretation">{escape(fixture.agent_interpretation)}</dd>
        <dt>Summary projection</dt>
        <dd data-testid="summary-projection-text">{escape(fixture.summary_text)}</dd>
        <dt>Anchor limitation</dt>
        <dd data-testid="summary-anchor-limitation">{escape(limitation)}</dd>
      </dl>
      <div class="summary-signals">{signals}</div>
      <button type="button"
        data-testid="summary-confirm-affordance"
        data-affordance-status="{confirm_state}"
        data-api-path="">
        Confirm unavailable from summary alone
      </button>
      <button type="button"
        data-testid="summary-readback"
        data-tts-action="read-summary"
        data-source-scope="summary-projection"
        data-source-audio="{str(fixture.source_audio_available).lower()}"
        data-summary-audio="{str(fixture.summary_audio_available).lower()}">
        Read summary projection
      </button>
    </section>"""


__all__ = ["SourcePreservingSummaryFixture", "render_source_preserving_summary_review"]
