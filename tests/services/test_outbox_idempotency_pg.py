"""KERNEL-02 (#2764) pg integration: the dedup guarantee is the PK, not the client.

Two independent real Postgres connections emitting the same derived key must
collapse to exactly one outbox row via the ``id`` primary key +
``ON CONFLICT (id) DO NOTHING`` — so a future refactor of the insert statement
or the table's key cannot silently drop the enforcement the not-pg fakes
emulate.
"""

from __future__ import annotations

import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg import sql  # noqa: E402

from app.db.dsn import resolve_dsn  # noqa: E402
from app.events.models import new_event  # noqa: E402
from app.events.types import INGEST_OBJECT_CREATED  # noqa: E402
from app.services.outbox import bootstrap, derive_idempotency_key, write_outbox_event  # noqa: E402


def _pg_base_dsn() -> str:
    return resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")


def _pg_available() -> bool:
    try:
        conn = psycopg.connect(_pg_base_dsn(), connect_timeout=1)
        conn.close()
        return True
    except Exception:
        return False


def _dsn_with_search_path(dsn: str, schema: str) -> str:
    parts = urlsplit(dsn)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema},public"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@pytest.mark.pg
def test_same_key_from_two_connections_yields_one_row() -> None:
    if not _pg_available():
        pytest.skip("postgres not available")

    base_dsn = _pg_base_dsn()
    schema = f"pgtest_{uuid4().hex}"
    with psycopg.connect(base_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = _dsn_with_search_path(base_dsn, schema)

    try:
        conn_a = psycopg.connect(dsn, autocommit=True)
        conn_b = psycopg.connect(dsn, autocommit=True)
        try:
            bootstrap(conn_a)

            key = derive_idempotency_key(INGEST_OBJECT_CREATED, "note-uuid-pg", "content-hash-pg")
            event = new_event(
                event_type=INGEST_OBJECT_CREATED,
                payload={"uuid": "note-uuid-pg", "content": "body"},
                trace_id="trace-pg",
            )

            first = write_outbox_event(event, conn_a, idempotency_key=key)
            second = write_outbox_event(event, conn_b, idempotency_key=key)

            assert first == key
            assert second == ""  # ON CONFLICT (id) DO NOTHING at the real PK

            row = conn_a.execute(
                "select count(*) from outbox where id = %s", (key,)
            ).fetchone()
            assert row is not None and int(row[0]) == 1

            # A different derived key from either connection is a genuine row.
            other = derive_idempotency_key(INGEST_OBJECT_CREATED, "note-uuid-pg", "content-hash-pg-2")
            assert write_outbox_event(event, conn_b, idempotency_key=other) == other
            row = conn_b.execute("select count(*) from outbox").fetchone()
            assert row is not None and int(row[0]) == 2
        finally:
            conn_a.close()
            conn_b.close()
    finally:
        with psycopg.connect(base_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
