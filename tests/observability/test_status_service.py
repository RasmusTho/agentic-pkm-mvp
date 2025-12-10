from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.observability.ingest_meta import record_ingest_run, reset_ingest_meta
from app.observability.status_service import get_system_status, record_ask_error, record_ask_query, reset_ask_metrics
from app.stores import get_object_store, reset_store_backends


def test_get_system_status_includes_ingest_and_ask_metrics():
    reset_store_backends()
    reset_ingest_meta()
    reset_ask_metrics()
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
