"""Phase A (EMBEDREL-06) — per-vector identity columns and fallback upsert guard.

Covers issue #2442:
- store_vector_index records the full (provider, model, dim, normalize) identity
  for every pg vector upsert.
- existing rows missing provider/normalize are backfilled from vector_index_meta.
- a reconcilable fallback write (same dim, different provider/model/normalize)
  succeeds and records the fallback identity per-row while the primary index
  identity in vector_index_meta stays stable.
- a dim mismatch still fails loud and writes no row (fallback or ordinary).
- ordinary (non-reconcilable) provider/model/normalize drift still fails loud.

These tests require a live Postgres backend; they are skipped under `not pg`.
"""

from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest

from app.components.embeddings import EmbeddingIdentity
from app.db.dsn import resolve_dsn
from app.stores import pg as pg_store

pytestmark = pytest.mark.pg


PRIMARY = EmbeddingIdentity(provider="ollama", model="nomic-embed-text", dim=4, normalize=True)
FALLBACK = EmbeddingIdentity(provider="gemini", model="gemini-embedding-001", dim=4, normalize=True)


def _dsn() -> str:
    return resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")


def _pg_available() -> bool:
    try:
        conn = psycopg.connect(_dsn(), connect_timeout=1)
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _pg_index(monkeypatch):
    if not _pg_available():
        pytest.skip("Postgres backend not available")
    monkeypatch.setenv("DATABASE_URL", _dsn())
    # Force schema (re)creation against this DSN and start from a clean index.
    pg_store._TABLES_READY = False
    pg_store._ensure_tables()
    pg_store.truncate_pg_tables()
    index = pg_store.PgVectorIndex()
    yield index
    pg_store.truncate_pg_tables()


def _row(object_id):
    with psycopg.connect(_dsn(), row_factory=psycopg.rows.dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT provider, model, dim, normalize FROM store_vector_index WHERE object_id = %s",
                (object_id,),
            )
            return cur.fetchone()


def _count(object_id) -> int:
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM store_vector_index WHERE object_id = %s", (object_id,))
            return int(cur.fetchone()[0])


def test_upsert_records_full_identity_columns(_pg_index):
    index = _pg_index
    oid = uuid4()
    index.upsert(
        object_id=oid,
        kind="note",
        source_ref="unit-test",
        payload={"text": "alpha"},
        embedding=[1.0, 0.0, 0.0, 0.0],
        model=PRIMARY.model,
        identity=PRIMARY,
    )
    row = _row(oid)
    assert row is not None
    assert row["provider"] == PRIMARY.provider
    assert row["model"] == PRIMARY.model
    assert row["dim"] == PRIMARY.dim
    assert row["normalize"] == PRIMARY.normalize


def test_identity_columns_backfill_from_index_meta(_pg_index):
    index = _pg_index
    oid = uuid4()
    # Seed a row with the primary identity, then simulate a pre-migration row by
    # nulling its provider/normalize columns (model/dim predate this slice).
    index.upsert(
        object_id=oid,
        kind="note",
        source_ref="unit-test",
        payload={"text": "alpha"},
        embedding=[1.0, 0.0, 0.0, 0.0],
        model=PRIMARY.model,
        identity=PRIMARY,
    )
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE store_vector_index SET provider = NULL, normalize = NULL WHERE object_id = %s",
                (oid,),
            )
        conn.commit()

    before = _row(oid)
    assert before["provider"] is None and before["normalize"] is None
    # dim/model/embedding must be preserved by the backfill.
    assert before["model"] == PRIMARY.model and before["dim"] == PRIMARY.dim

    # Re-run the migration/backfill (idempotent) — provider/normalize fill from meta.
    pg_store._TABLES_READY = False
    pg_store._ensure_tables()

    after = _row(oid)
    assert after["provider"] == PRIMARY.provider
    assert after["normalize"] == PRIMARY.normalize
    assert after["model"] == PRIMARY.model
    assert after["dim"] == PRIMARY.dim
    assert _count(oid) == 1  # object id unchanged, no duplicate row

    # Second backfill run is a no-op (idempotent / safe on already-migrated db).
    pg_store._TABLES_READY = False
    pg_store._ensure_tables()
    assert _row(oid) == after


def test_reconcilable_fallback_identity_write_preserves_primary_identity(_pg_index):
    index = pg_store.PgVectorIndex()
    primary_oid = uuid4()
    fallback_oid = uuid4()
    # Establish the primary index identity.
    index.upsert(
        object_id=primary_oid,
        kind="note",
        source_ref="unit-test",
        payload={"text": "primary"},
        embedding=[1.0, 0.0, 0.0, 0.0],
        model=PRIMARY.model,
        identity=PRIMARY,
    )
    # A reconcilable fallback write under a different provider/model succeeds.
    index.upsert(
        object_id=fallback_oid,
        kind="note",
        source_ref="unit-test",
        payload={"text": "fallback"},
        embedding=[0.0, 1.0, 0.0, 0.0],
        model=FALLBACK.model,
        identity=FALLBACK,
        reconcilable_fallback=True,
    )

    fallback_row = _row(fallback_oid)
    assert fallback_row["provider"] == FALLBACK.provider
    assert fallback_row["model"] == FALLBACK.model
    assert fallback_row["dim"] == FALLBACK.dim
    assert fallback_row["normalize"] == FALLBACK.normalize

    # Primary row identity is unchanged.
    primary_row = _row(primary_oid)
    assert primary_row["provider"] == PRIMARY.provider
    assert primary_row["model"] == PRIMARY.model

    # The index-level (primary) identity in vector_index_meta is still PRIMARY.
    stored_primary = index.get_identity()
    assert stored_primary == PRIMARY


def test_dimension_mismatch_still_refuses_fallback_write(_pg_index):
    index = pg_store.PgVectorIndex()
    primary_oid = uuid4()
    index.upsert(
        object_id=primary_oid,
        kind="note",
        source_ref="unit-test",
        payload={"text": "primary"},
        embedding=[1.0, 0.0, 0.0, 0.0],
        model=PRIMARY.model,
        identity=PRIMARY,
    )

    wrong_dim = EmbeddingIdentity(provider="gemini", model="gemini-embedding-001", dim=3, normalize=True)
    fallback_oid = uuid4()
    # Even flagged reconcilable, a dim mismatch must fail loud and write nothing.
    with pytest.raises((ValueError, RuntimeError)):
        index.upsert(
            object_id=fallback_oid,
            kind="note",
            source_ref="unit-test",
            payload={"text": "fallback"},
            embedding=[0.0, 1.0, 0.0],
            model=wrong_dim.model,
            identity=wrong_dim,
            reconcilable_fallback=True,
        )
    assert _count(fallback_oid) == 0

    # An ordinary (non-fallback) dim mismatch also fails and writes nothing.
    ordinary_oid = uuid4()
    with pytest.raises((ValueError, RuntimeError)):
        index.upsert(
            object_id=ordinary_oid,
            kind="note",
            source_ref="unit-test",
            payload={"text": "ordinary"},
            embedding=[0.0, 1.0, 0.0],
            model=wrong_dim.model,
            identity=wrong_dim,
        )
    assert _count(ordinary_oid) == 0


def test_non_reconcilable_identity_drift_still_fails(_pg_index):
    index = pg_store.PgVectorIndex()
    primary_oid = uuid4()
    index.upsert(
        object_id=primary_oid,
        kind="note",
        source_ref="unit-test",
        payload={"text": "primary"},
        embedding=[1.0, 0.0, 0.0, 0.0],
        model=PRIMARY.model,
        identity=PRIMARY,
    )

    drift_oid = uuid4()
    # Same dim, different provider/model, but NOT flagged reconcilable → fail loud.
    with pytest.raises(RuntimeError):
        index.upsert(
            object_id=drift_oid,
            kind="note",
            source_ref="unit-test",
            payload={"text": "drift"},
            embedding=[0.0, 1.0, 0.0, 0.0],
            model=FALLBACK.model,
            identity=FALLBACK,
        )
    assert _count(drift_oid) == 0
