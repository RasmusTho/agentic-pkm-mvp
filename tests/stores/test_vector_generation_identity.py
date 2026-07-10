"""ADR-0059 D2 (#3403) — PgVectorIndex.generation() becomes identity-aware.

Covers issue #3403 (first pickup under parent hub #3402): a repin that
rewrites ``vector_index_meta.identity_json`` WITHOUT touching any
``store_vector_index`` row must still move the generation token, so the
serving-path cache revalidates on identity change (previously masked by the
read-path re-embed that a sibling issue removes). Also guards against
regressing the existing upsert/purge semantics (#2981).

These tests require a live Postgres backend; they are skipped under `not pg`.
"""

from __future__ import annotations

import json
import os
from uuid import uuid4

import psycopg
import pytest

from app.components.embeddings import EmbeddingIdentity
from app.db.dsn import resolve_dsn
from app.stores import pg as pg_store

pytestmark = pytest.mark.pg


PRIMARY = EmbeddingIdentity(provider="ollama", model="nomic-embed-text", dim=4, normalize=True)


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
    pg_store._TABLES_READY = False
    pg_store._ensure_tables()
    pg_store.truncate_pg_tables()
    index = pg_store.PgVectorIndex()
    yield index
    pg_store.truncate_pg_tables()


def _rewrite_identity_only(new_identity: EmbeddingIdentity) -> None:
    """Simulate an ADR-0052 repin: rewrite the stored identity row directly
    WITHOUT touching any store_vector_index row (no upsert, no purge)."""
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE vector_index_meta
                SET identity_json = %s, updated_at = now()
                WHERE id = 1
                """,
                (json.dumps({
                    "provider": new_identity.provider,
                    "model": new_identity.model,
                    "dim": new_identity.dim,
                    "normalize": new_identity.normalize,
                }),),
            )
        conn.commit()


def test_generation_moves_on_identity_change_without_row_rewrites(_pg_index):
    """A repin of vector_index_meta.identity_json without any row rewrite
    still changes generation() (ADR-0059 D2)."""
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
    before = index.generation()

    # Same dim (repin must preserve dim by construction elsewhere; the token
    # test only cares that identity_json changed), different provider/model —
    # no upsert, no purge, no row touched.
    repinned = EmbeddingIdentity(provider="gemini", model="gemini-embedding-001", dim=4, normalize=True)
    _rewrite_identity_only(repinned)

    after = index.generation()
    assert after != before, (
        "generation() must change when vector_index_meta.identity_json changes, "
        "even with zero store_vector_index row rewrites (ADR-0059 D2)"
    )

    # The row-derived component (count/max(updated_at)) is untouched by the
    # repin — only the identity-hash component moved.
    before_count_latest = before.split(":", 1)[1]
    after_count_latest = after.split(":", 1)[1]
    assert before_count_latest == after_count_latest, (
        "the repin touched no store_vector_index row, so the count/updated_at "
        "component of the token must be unchanged; only the identity-hash "
        "leading component should differ"
    )


def test_generation_stable_when_identity_json_text_unchanged(_pg_index):
    """Rewriting identity_json to the SAME value must not move the token
    (no false-positive invalidation from an idempotent identity write)."""
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
    before = index.generation()
    _rewrite_identity_only(PRIMARY)
    after = index.generation()
    assert after == before


def test_generation_moves_on_upsert_and_purge(_pg_index):
    """Regression guard: identity-aware generation() must not weaken the
    existing #2981 semantics — upsert and purge still move the token."""
    index = _pg_index
    oid = uuid4()
    g0 = index.generation()

    index.upsert(
        object_id=oid,
        kind="note",
        source_ref="unit-test",
        payload={"text": "alpha"},
        embedding=[1.0, 0.0, 0.0, 0.0],
        model=PRIMARY.model,
        identity=PRIMARY,
    )
    g1 = index.generation()
    assert g1 != g0, "upsert must change generation()"

    index.purge_vectors(oid, view="note")
    g2 = index.generation()
    assert g2 != g1, "purge must change generation()"


def test_generation_empty_identity_component_when_no_identity_row(_pg_index):
    """No vector_index_meta row yet (fresh index, no upsert ever run): the
    identity component is the empty-string hash, not an error."""
    index = _pg_index
    g = index.generation()
    assert g, "generation() must return a token even with no identity row"
    identity_component = g.split(":", 1)[0]
    assert identity_component, "identity component must be present (hash of empty string), not blank"
