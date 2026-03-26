from __future__ import annotations

import uuid

import pytest

from app.db.dsn import resolve_dsn
from app.observability.status_service import get_store_status
from app.stores import get_object_store, reset_store_backends
from app.stores.pg import pg_available


@pytest.mark.pg
def test_status_counts_pg_objects(monkeypatch) -> None:
    if not pg_available():
        pytest.skip("Postgres backend not available")

    monkeypatch.setenv("DATABASE_URL", resolve_dsn() or "postgresql://app:app@127.0.0.1:15432/app")
    monkeypatch.setenv("STORE_BACKEND", "pg")
    reset_store_backends()
    store = get_object_store()

    object_id = uuid.uuid4()
    store.put(
        object_id,
        kind="note",
        source_ref="unit-test://warm",
        payload={"text": "Alpha warm content", "origin": "vault"},
    )

    statuses = get_store_status()
    vault_status = next((s for s in statuses if s.name == "vault"), None)
    assert vault_status is not None
    assert vault_status.object_count >= 1

    reset_store_backends()
