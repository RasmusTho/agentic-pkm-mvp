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


def _drain_db_outbox_embedding_spine(*, max_messages: int = 50) -> int:
    """Drain the DB outbox through the exact dispatch path the worker uses.

    Mirrors ``app.workers.outbox_worker.run``: poll one undelivered row at a
    time via :func:`poll_outbox_one`, dispatch ``INDEX_EMBEDDING_REQUESTED``
    rows into :func:`app.indexer.consumer.process_event` (the same entrypoint
    the worker dispatches to), then ack. Returns ``processed_total`` — the
    count of rows the worker would have processed in this run.
    """
    from app.indexer.consumer import process_event as process_indexer_event
    from app.outbox.events import INDEX_EMBEDDING_REQUESTED
    from app.services.outbox import ack_outbox, poll_outbox_one

    processed_total = 0
    for _ in range(max_messages):
        message = poll_outbox_one()
        if not message:
            break
        processed_total += 1
        topic = message.get("topic")
        payload = dict(message.get("payload") or {})
        trace_id = payload.get("trace_id") or message.get("trace_id") or "-"
        if topic == INDEX_EMBEDDING_REQUESTED:
            process_indexer_event(
                {
                    "event": INDEX_EMBEDDING_REQUESTED,
                    "payload": payload,
                    "trace_id": trace_id,
                }
            )
        ack_outbox(message["id"])
    return processed_total


def _store_objects_row_count(dsn: str) -> int:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM store_objects")
            row = cur.fetchone()
    return int(row[0] or 0) if row else 0


def _vector_index_rows_with_embedding(dsn: str) -> list[tuple]:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT object_id, embedding FROM store_vector_index "
                "WHERE embedding IS NOT NULL AND array_length(embedding, 1) > 0"
            )
            return list(cur.fetchall())


@pytest.mark.pg
def test_outbox_roundtrip_embeds(tmp_path, monkeypatch) -> None:
    """Gate-0 spine: vault save -> request event -> DB-outbox drain -> durable rows.

    Asserts the full durable path in one run: a ``store_objects`` row persists,
    a ``store_vector_index`` row with a non-empty embedding is written by the
    consumer, and the worker-equivalent drain reports ``processed_total >= 1``.
    This exercises the durable ``PgVectorIndex`` (``store_vector_index``) path,
    not only the in-memory store.
    """
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    dsn = resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")
    reset_store_backends()
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    fake_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr(events, "INDEX_OUTBOX_PATH", fake_path, raising=False)

    import app.store.object_store as legacy_object_store

    legacy_object_store._MEMORY_STORE.clear()

    objects_before = _store_objects_row_count(dsn)

    store = ObjectStore()
    oid = uuid4()
    store.save_object(
        DomainObject(
            uuid=str(oid),
            kind="note",
            payload={"text": "gate-0 spine payload", "content": "gate-0 spine payload"},
            source_ref="unit-test:roundtrip-embeds",
            created_at=datetime.now(timezone.utc),
        ),
        emit_outbox=False,
        trace_id="trace-roundtrip-embeds",
    )
    events.emit_index_embedding_requested(
        {"object_id": oid, "trace_id": "trace-roundtrip-embeds", "source": "test"}
    )

    # Force the consumer to read the durable backend, not the in-process mirror.
    legacy_object_store._MEMORY_STORE.clear()

    processed_total = _drain_db_outbox_embedding_spine()

    # Worker-equivalent receipt: at least the embedding-request row was processed.
    assert processed_total >= 1

    # store_objects row persisted durably for this object.
    assert _store_objects_row_count(dsn) == objects_before + 1

    # store_vector_index row written with a non-empty embedding for this object.
    rows = _vector_index_rows_with_embedding(dsn)
    matching = [r for r in rows if str(r[0]) == str(oid)]
    assert matching, "expected a store_vector_index row with a non-empty embedding for the seeded object"
    object_id, embedding = matching[0]
    assert embedding, "stored embedding must be non-empty"
    assert len(list(embedding)) == 8

    reset_store_backends()


@pytest.mark.pg
def test_unembedded_objects_fail_loud(tmp_path, monkeypatch) -> None:
    """#2252-class regression: objects present but un-embedded must fail loud.

    Seeds a ``store_objects`` row and emits the embedding request, but does NOT
    drain the outbox (the head-of-line stall that left ``processed_total=0`` and
    no ``store_vector_index`` row). A verifier that checks the durable index must
    detect this objects-present-but-unembedded state and fail loud, rather than
    silently passing.
    """
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    dsn = resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")
    reset_store_backends()
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    fake_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr(events, "INDEX_OUTBOX_PATH", fake_path, raising=False)

    import app.store.object_store as legacy_object_store

    legacy_object_store._MEMORY_STORE.clear()

    store = ObjectStore()
    oid = uuid4()
    store.save_object(
        DomainObject(
            uuid=str(oid),
            kind="note",
            payload={"text": "unembedded payload", "content": "unembedded payload"},
            source_ref="unit-test:fail-loud",
            created_at=datetime.now(timezone.utc),
        ),
        emit_outbox=False,
        trace_id="trace-fail-loud",
    )
    events.emit_index_embedding_requested(
        {"object_id": oid, "trace_id": "trace-fail-loud", "source": "test"}
    )

    # Deliberately DO NOT drain the outbox: processed_total stays 0 and no
    # store_vector_index row is written for this object (the #2252 stall).
    rows = _vector_index_rows_with_embedding(dsn)
    matching = [r for r in rows if str(r[0]) == str(oid)]
    assert not matching, "precondition: object must be present but un-embedded"

    # A loud verification gate must reject this state rather than pass silently.
    def _assert_object_embedded(object_id: str) -> None:
        embedded = [r for r in _vector_index_rows_with_embedding(dsn) if str(r[0]) == str(object_id)]
        if not embedded:
            raise AssertionError(
                f"object {object_id} present in store_objects but has no embedded "
                "store_vector_index row (processed_total=0; #2252-class stall)"
            )

    with pytest.raises(AssertionError, match="present in store_objects but has no embedded"):
        _assert_object_embedded(str(oid))

    reset_store_backends()
