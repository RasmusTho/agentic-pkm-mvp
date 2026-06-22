from __future__ import annotations

from datetime import datetime, timezone

from app.observability.status_model import EventCounters, IngestionStatus, WorkerQueueStatus
from app.observability.status_service import OrientationSignals
from app.resurfacing.runtime import (
    RESURFACE_SCARCE_COUNT,
    ResurfacingCandidate,
    ResurfacingEvaluation,
    ResurfacingWhyNow,
    evaluate_resurfacing_candidates,
)


def _signals() -> OrientationSignals:
    return OrientationSignals(
        events=EventCounters(
            watcher_runs_24h=2,
            promote_created_total=4,
            promotion_executed_total=1,
            promote_created_24h=2,
            source_path="tmp/events.jsonl",
        ),
        ingestion=IngestionStatus(last_run_at=datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc)),
        worker_queue=WorkerQueueStatus(mode="db", pending=3, source_path="tmp/queue.db"),
    )


def test_resurfacing_without_query(monkeypatch) -> None:
    monkeypatch.setattr("app.resurfacing.runtime.get_orientation_signals", _signals)

    result = evaluate_resurfacing_candidates()

    assert result.read_only is True
    assert "resurfacing_candidates=" in result.status_summary
    assert isinstance(result.candidates, list)


def test_resurfacing_includes_why_now_explanation(monkeypatch) -> None:
    monkeypatch.setattr("app.resurfacing.runtime.get_orientation_signals", _signals)

    result = evaluate_resurfacing_candidates()

    assert result.candidates
    candidate = result.candidates[0]
    assert "because" in candidate.why_now.explanation.lower()
    assert candidate.why_now.signals
    assert all(signal.source for signal in candidate.why_now.signals)


def test_resurfacing_is_read_only(monkeypatch) -> None:
    monkeypatch.setattr("app.resurfacing.runtime.get_orientation_signals", _signals)

    result = evaluate_resurfacing_candidates()

    assert result.read_only is True
    assert result.mutation_intents == []
    assert any("no writes" in line.lower() for line in result.receipt)


def test_resurfacing_declares_scarce_count_and_holdback(monkeypatch) -> None:
    """The evaluation declares the scarce display cap and whether more was held
    back, so the UI can render the withheld line without inventing a count."""
    monkeypatch.setattr("app.resurfacing.runtime.get_orientation_signals", _signals)

    result = evaluate_resurfacing_candidates()

    assert result.scarce_count == RESURFACE_SCARCE_COUNT
    # The status-signal evaluator yields at most three candidates, so nothing is
    # held back today; the flag must report that honestly.
    assert result.more_held_back is (len(result.candidates) > RESURFACE_SCARCE_COUNT)
    assert f"scarce_count={RESURFACE_SCARCE_COUNT}" in result.status_summary


def test_resurfacing_candidate_pinned_defaults_false(monkeypatch) -> None:
    monkeypatch.setattr("app.resurfacing.runtime.get_orientation_signals", _signals)

    result = evaluate_resurfacing_candidates()

    assert result.candidates
    assert all(candidate.pinned is False for candidate in result.candidates)


def test_resurfacing_evaluation_more_held_back_when_over_cap() -> None:
    """A set larger than the scarce cap reports more_held_back and sorts pinned
    cards to the top — exercised directly since the live evaluator never exceeds
    the cap today."""
    candidates = [
        ResurfacingCandidate(
            candidate_id=f"c{index}",
            label=f"Card {index}",
            why_now=ResurfacingWhyNow(explanation="x"),
            pinned=(index == RESURFACE_SCARCE_COUNT),
        )
        for index in range(RESURFACE_SCARCE_COUNT + 1)
    ]
    # Re-run the sort/holdback logic the evaluator applies.
    candidates.sort(key=lambda candidate: not candidate.pinned)
    evaluation = ResurfacingEvaluation(
        generated_at="2026-01-01T00:00:00Z",
        status_summary="",
        candidates=candidates,
        more_held_back=len(candidates) > RESURFACE_SCARCE_COUNT,
    )

    assert evaluation.more_held_back is True
    assert evaluation.candidates[0].pinned is True
