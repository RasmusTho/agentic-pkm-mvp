from __future__ import annotations

from datetime import datetime, timezone

from app.observability.status_model import EventCounters, IngestionStatus, WorkerQueueStatus
from app.observability.status_service import OrientationSignals
from app.resurfacing.runtime import evaluate_resurfacing_candidates


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
