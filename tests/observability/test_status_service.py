import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.observability.ingest_meta import record_ingest_run, reset_ingest_meta
from app.observability.status_service import get_system_status, record_ask_error, record_ask_query, reset_ask_metrics
from app.stores import get_object_store, reset_store_backends
import app.observability.status_service as status_service


def test_get_system_status_includes_ingest_and_ask_metrics(monkeypatch, tmp_path):
    reset_store_backends()
    reset_ingest_meta()
    reset_ask_metrics()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "memory")
    outbox_path = tmp_path / "status-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    status_service.INDEX_OUTBOX_PATH = outbox_path
    store = get_object_store()
    store.put(uuid4(), kind="note", source_ref="vault/path", payload={"title": "Vault note", "origin": "vault"})
    store.put(
        uuid4(),
        kind="note",
        source_ref="ext/path",
        payload={"title": "Ext", "origin": "external_raw", "plane": "external"},
    )

    vault_run = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    external_run = vault_run + timedelta(minutes=5)
    record_ingest_run("vault", scanned=3, ingested=2, errors=1, malformed=1, dt=vault_run, ok=False, message="oops")
    record_ingest_run("external", scanned=2, ingested=2, errors=0, malformed=0, dt=external_run, ok=True)

    record_ask_query(50.0)
    record_ask_query(150.0)
    record_ask_error()
    status = get_system_status()

    assert status.timestamp <= datetime.now(timezone.utc)
    stores = {s.name: s for s in status.stores}
    assert stores["vault"].object_count == 1
    assert stores["vault"].last_ingest_at == vault_run
    assert stores["vault"].last_error_at == vault_run
    assert stores["external"].object_count == 1
    assert stores["external"].last_ingest_at == external_run

    assert status.ingestion.total_scanned == 5
    assert status.ingestion.total_ingested == 4
    assert status.ingestion.total_errors == 1
    assert status.ingestion.total_malformed == 1
    planes = {p.plane: p for p in status.ingestion.planes}
    assert planes["vault"].errors == 1
    assert planes["vault"].malformed == 1
    assert planes["external"].ingested == 2

    assert status.ask.total_queries_24h == 2
    assert status.ask.error_count_24h == 1
    assert status.ask.avg_latency_ms_24h == pytest.approx(100.0)

    assert status.feature_line_version == status.sot_forward_line_version
    assert status.active_features
    assert status.intents is not None
    assert status.intents.promote_created_total == 0
    assert status.intents.promote_created_24h == 0
    assert status.events is not None
    assert status.events.panel_runs_total == 0
    assert status.events.promote_created_total == 0
    assert status.events.promotion_executed_total == 0
    assert status.events.ingest_runs_by_plane.get("vault") == 1


def test_event_counts_from_outbox(monkeypatch, tmp_path):
    reset_store_backends()
    reset_ingest_meta()
    reset_ask_metrics()
    outbox = tmp_path / "outbox.jsonl"
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "memory")

    monkeypatch.setattr("app.observability.status_service.INDEX_OUTBOX_PATH", outbox)

    now = datetime.now(timezone.utc)
    older = now - timedelta(days=2)
    records = [
        {"event": "panel.intent.executed", "timestamp": now.isoformat().replace("+00:00", "Z")},
        {"event": "panel.intent.executed", "timestamp": older.isoformat().replace("+00:00", "Z")},
        {"event": "promote.intent.created", "timestamp": now.isoformat().replace("+00:00", "Z")},
        {"event": "promote.done", "timestamp": now.isoformat().replace("+00:00", "Z")},
        {"event": "watcher.run.completed", "timestamp": now.isoformat().replace("+00:00", "Z")},
    ]
    outbox.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")

    status = get_system_status()
    assert status.events is not None
    assert status.events.panel_runs_total == 2
    assert status.events.panel_runs_24h == 1
    assert status.events.promote_created_total == 1
    assert status.events.promote_created_24h == 1
    assert status.events.promotion_executed_total == 1
    assert status.events.promotion_executed_24h == 1
    assert status.events.watcher_runs_total == 1
    assert status.events.watcher_runs_24h == 1
    assert status.events.source_path == str(outbox)
    assert status.intents.promote_created_total == 1
