from __future__ import annotations

import importlib
import os
from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest

from app.db.dsn import resolve_dsn
from app.components.embeddings import get_embedding_client
from app.outbox import events
from app.objects import DomainObject, ObjectStore
from app.stores import get_vector_index, reset_store_backends


def _pg_available() -> bool:
    url = resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")
    try:
        conn = psycopg.connect(url, connect_timeout=1)
        conn.close()
        return True
    except Exception:
        return False


@pytest.mark.pg
def test_indexer_runner_pg_does_not_consume_jsonl_outbox_queue(tmp_path, monkeypatch, capsys) -> None:
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    reset_store_backends()
    monkeypatch.setenv("DATABASE_URL", resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app"))
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    fake_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr(events, "INDEX_OUTBOX_PATH", fake_path, raising=False)

    import app.store.object_store as legacy_object_store

    legacy_object_store._MEMORY_STORE.clear()

    import app.indexer.runner as runner

    importlib.reload(runner)

    store = ObjectStore()
    for i in range(2):
        oid = uuid4()
        store.save_object(
            DomainObject(
                uuid=str(oid),
                kind="note",
                payload={"text": f"payload-{i}", "content": f"payload-{i}"},
                source_ref=f"unit-test:{i}",
                created_at=datetime.now(timezone.utc),
            ),
            emit_outbox=False,
            trace_id="trace-123",
        )
        events.emit_index_embedding_requested({"object_id": oid, "trace_id": "trace-123", "source": "test"})

    runner.main()
    output = capsys.readouterr().out
    assert "JSONL queue consumption disabled" in output

    idx = get_vector_index()
    query = get_embedding_client().embed_text("payload-0")
    hits = idx.search(query, k=2)

    assert not hits

    reset_store_backends()
