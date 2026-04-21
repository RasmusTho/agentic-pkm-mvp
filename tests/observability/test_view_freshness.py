from __future__ import annotations

from datetime import datetime, timezone

from app.observability.status_model import IngestionStatus, StoreStatus, WorkerQueueStatus
from app.observability.status_service import classify_view_freshness


def test_status_classifies_fresh_stale_partial_unknown_views() -> None:
    fresh = classify_view_freshness(
        stores=[StoreStatus(name="vault", object_count=1, last_ingest_at=datetime.now(timezone.utc))],
        ingestion=IngestionStatus(last_run_at=datetime.now(timezone.utc), last_run_ok=True),
        worker_queue=WorkerQueueStatus(mode="none"),
    )
    assert fresh.state == "fresh"

    stale = classify_view_freshness(
        stores=[StoreStatus(name="vault", object_count=1)],
        ingestion=IngestionStatus(last_run_ok=False),
    )
    assert stale.state == "stale"

    partial = classify_view_freshness(
        stores=[StoreStatus(name="vault", object_count=1, last_ingest_at=datetime.now(timezone.utc))],
        ingestion=IngestionStatus(last_run_at=datetime.now(timezone.utc), last_run_ok=True),
        worker_queue=WorkerQueueStatus(mode="jsonl", pending=3),
    )
    assert partial.state == "partial"

    unknown = classify_view_freshness(stores=[], ingestion=IngestionStatus())
    assert unknown.state == "unknown"
