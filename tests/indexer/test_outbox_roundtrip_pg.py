from __future__ import annotations

import os
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from app.db.dsn import resolve_dsn
from app.outbox import events
from app.objects import DomainObject, ObjectStore


def _pg_available() -> bool:
    url = _pg_base_dsn()
    try:
        conn = psycopg.connect(url, connect_timeout=1)
        conn.close()
        return True
    except Exception:
        return False


def _pg_base_dsn() -> str:
    return resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")


def _dsn_with_search_path(dsn: str, schema: str) -> str:
    parts = urlsplit(dsn)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema},public"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _create_schema(dsn: str, schema: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))


def _drop_schema(dsn: str, schema: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


def _reset_store_backend_cache_only() -> None:
    import app.stores as stores

    stores._LAST_RESOLVED_BACKEND = None
    for cache_name in ("_memory_instances", "_pg_instances"):
        cache = getattr(stores, cache_name, None)
        if cache is not None:
            cache.cache_clear()
    try:
        import app.stores.pg as pg

        pg._TABLES_READY = False
    except Exception:
        pass


def _configure_isolated_pg_test(tmp_path, monkeypatch) -> tuple[str, str]:
    """Bind this test to a disposable schema, never the operator's shared tables."""
    base_dsn = _pg_base_dsn()
    schema = f"pgtest_{uuid4().hex}"
    _create_schema(base_dsn, schema)
    dsn = _dsn_with_search_path(base_dsn, schema)
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("DB_DSN", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_PRIMARY_PROVIDER", "mock")
    monkeypatch.delenv("EMBED_PROFILE", raising=False)
    monkeypatch.setenv("EMBED_DIM", "8")
    fake_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr(events, "INDEX_OUTBOX_PATH", fake_path, raising=False)
    _reset_store_backend_cache_only()
    from app.services.outbox import bootstrap

    bootstrap()
    return base_dsn, schema


def _undelivered_rows_for_object(dsn: str, object_id: str) -> list[tuple[str, str, dict]]:
    """Return ``(id, topic, inner_payload)`` for this object's undelivered rows only.

    ``poll_outbox_one`` returns the oldest *global* undelivered row and a drain
    loop over it would dispatch+ack pre-existing rows from other work on a shared
    or operator DB — destructive and flaky. We instead claim by ``object_id`` so
    the drain touches only rows this test emitted; foreign rows are never
    selected, dispatched, or acked.

    The ``outbox.payload`` column stores the *full* OutboxEvent envelope
    (``write_outbox_event`` persists ``envelope.model_dump_json()``), so the
    event ``object_id`` lives at ``payload->'payload'->>'object_id'`` — NOT at
    the envelope top level. We select on that nested path and return the
    *unwrapped* inner event payload (``envelope['payload']``), matching the shape
    ``poll_outbox_one`` hands the production worker (``event.payload``).
    """
    rows: list[tuple[str, str, dict]] = []
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, topic, payload FROM outbox "
                "WHERE delivered_at IS NULL "
                "AND payload->'payload'->>'object_id' = %s "
                "ORDER BY created_at ASC",
                (str(object_id),),
            )
            for row in cur.fetchall():
                raw = row[2]
                envelope = raw if isinstance(raw, dict) else (raw or {})
                if not isinstance(envelope, dict):
                    envelope = {}
                inner = envelope.get("payload")
                inner_payload = dict(inner) if isinstance(inner, dict) else {}
                # trace_id lives on the envelope, not the inner event payload;
                # carry it through so the dispatched event matches the worker.
                inner_payload.setdefault("trace_id", envelope.get("trace_id"))
                rows.append((str(row[0]), str(row[1]), inner_payload))
    return rows


def _drain_db_outbox_embedding_spine(dsn: str, object_id: str) -> int:
    """Drain ONLY this test's seeded embedding-request rows, leaving others intact.

    Selects undelivered outbox rows scoped to ``object_id`` (never the global
    oldest row), then for each ``INDEX_EMBEDDING_REQUESTED`` row dispatches into
    :func:`app.indexer.consumer.process_event` — the same entrypoint
    ``app.workers.outbox_worker.run`` dispatches to — and acks just that row via
    :func:`ack_outbox`. Foreign rows are never acked or dispatched. Returns
    ``processed_total``: the count of this test's rows processed.
    """
    from app.indexer.consumer import process_event as process_indexer_event
    from app.outbox.events import INDEX_EMBEDDING_REQUESTED
    from app.services.outbox import ack_outbox

    processed_total = 0
    for message_id, topic, payload in _undelivered_rows_for_object(dsn, object_id):
        trace_id = payload.get("trace_id") or "-"
        if topic == INDEX_EMBEDDING_REQUESTED:
            process_indexer_event(
                {
                    "event": INDEX_EMBEDDING_REQUESTED,
                    "payload": payload,
                    "trace_id": trace_id,
                }
            )
        processed_total += 1
        ack_outbox(message_id)
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

    base_dsn, schema = _configure_isolated_pg_test(tmp_path, monkeypatch)
    dsn = os.environ["DATABASE_URL"]
    try:
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

        processed_total = _drain_db_outbox_embedding_spine(dsn, str(oid))

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
    finally:
        _reset_store_backend_cache_only()
        _drop_schema(base_dsn, schema)


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

    base_dsn, schema = _configure_isolated_pg_test(tmp_path, monkeypatch)
    dsn = os.environ["DATABASE_URL"]
    try:
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

        # Drive the REAL production verifier (app.index.doctor.verify_object_embedded),
        # not a self-defined raiser, against the objects-present/no-vector state.
        from app.index.doctor import IndexDriftError, verify_object_embedded

        with pytest.raises(IndexDriftError, match="present in store_objects but has no embedded"):
            verify_object_embedded(str(oid))
        from app.index.doctor import diagnose_index, reset_diagnose_cache

        reset_diagnose_cache()
        diagnosis = diagnose_index()
        assert diagnosis["rebuild_required"] is True
        assert any("store_objects rows have no embedded" in issue for issue in diagnosis["issues"])

        # And once the row IS drained/embedded, the same verifier must pass.
        processed_total = _drain_db_outbox_embedding_spine(dsn, str(oid))
        assert processed_total >= 1
        reset_diagnose_cache()
        verify_object_embedded(str(oid))
    finally:
        _reset_store_backend_cache_only()
        _drop_schema(base_dsn, schema)
