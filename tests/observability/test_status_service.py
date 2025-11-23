from datetime import datetime, timezone
from uuid import uuid4

from app.observability.status_service import get_system_status, record_ask_query
from app.stores import get_object_store, reset_store_backends


def test_get_system_status_returns_counts_and_timestamp():
    reset_store_backends()
    store = get_object_store()
    store.put(uuid4(), kind="note", source_ref="vault/path", payload={"title": "Vault note", "origin": "vault"})
    store.put(uuid4(), kind="note", source_ref="ext/path", payload={"title": "Ext", "origin": "external_raw"})

    record_ask_query(50.0)
    status = get_system_status()

    assert status.timestamp <= datetime.now(timezone.utc)
    assert status.sot_version
    names = {s.name: s.object_count for s in status.stores}
    assert names.get("vault", 0) >= 1
    assert names.get("external", 0) >= 1
    assert status.ask.total_queries_24h >= 1
