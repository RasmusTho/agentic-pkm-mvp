"""EMBEDREL-06 AC 1 — per-vector full embedding-identity provenance.

Every stored vector must record its full ``(provider, model, dim, normalize)``
embedding identity, not just ``model``/``dim``. The per-row ``provider`` and
``normalize`` columns are the prerequisite for mixed-identity detection and
reconcile convergence (CTI-1).

Requires a live Postgres backend; skipped when unavailable.
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
FALLBACK = EmbeddingIdentity(provider="gemini", model="gemini-embedding-001", dim=4, normalize=False)


def _dsn() -> str:
    return resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")


def _pg_available() -> bool:
    try:
        conn = psycopg.connect(_dsn(), connect_timeout=1)
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture()
def pg_index(monkeypatch):
    if not _pg_available():
        pytest.skip("Postgres backend not available")
    monkeypatch.setenv("DATABASE_URL", _dsn())
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


def test_vector_records_full_identity(pg_index):
    """A pg vector upsert persists all four identity fields per row."""
    index = pg_index
    oid = uuid4()
    index.upsert(
        object_id=oid,
        kind="note",
        source_ref="tests/identity-provenance",
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

    # A reconcilable fallback write records the *fallback* identity per row (distinct
    # provider AND normalize), proving the columns carry the full tuple, not just model.
    fallback_oid = uuid4()
    index.upsert(
        object_id=fallback_oid,
        kind="note",
        source_ref="tests/identity-provenance",
        payload={"text": "beta"},
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
