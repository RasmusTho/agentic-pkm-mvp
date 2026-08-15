"""PostgreSQL isolation proof for MVR-05A3 (#4577)."""

from __future__ import annotations

import uuid

import psycopg
import pytest

from tests.migrations.test_multi_vault_ingest_projection_keys import (
    INGEST_HEAD,
    _upgrade,
    scratch_db_factory,  # noqa: F401 - pytest fixture export
)

pytestmark = pytest.mark.pg


@pytest.fixture
def migrated_store_dsn(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    factory = request.getfixturevalue("scratch_db_factory")
    dsn = factory()
    _upgrade(dsn, monkeypatch, INGEST_HEAD)
    return dsn


def test_duplicate_uuid_is_namespaced_by_binding_in_ingest_projections(
    migrated_store_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    object_id = uuid.uuid4()
    set_id = uuid.uuid4()
    rows = [("binding-a", object_id), ("binding-b", object_id)]
    with psycopg.connect(migrated_store_dsn) as conn:
        conn.execute("INSERT INTO sets (id, name) VALUES (%s, 'shared-isolation-set')", (set_id,))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO store_objects "
                "(vault_binding_id, object_id, kind, payload) "
                "VALUES (%s, %s, 'note', '{}'::jsonb)",
                rows,
            )
            cur.executemany(
                "INSERT INTO store_vector_index "
                "(vault_binding_id, object_id, kind, payload, embedding, dim, model) "
                "VALUES (%s, %s, 'note', '{}'::jsonb, ARRAY[1.0]::double precision[], 1, 'm')",
                rows,
            )
            cur.executemany(
                "INSERT INTO store_relations "
                "(vault_binding_id, src_id, dst_id, rel) VALUES (%s, %s, %s, 'self')",
                [(binding, oid, oid) for binding, oid in rows],
            )
            cur.executemany(
                "INSERT INTO store_relation_memberships "
                "(vault_binding_id, src_id, rel, value) VALUES (%s, %s, 'tag', 'shared')",
                rows,
            )
            cur.executemany(
                "INSERT INTO vector_index_meta (vault_binding_id, id, identity_json) "
                "VALUES (%s, 1, '{}')",
                [(binding,) for binding, _ in rows],
            )
            for binding, oid in rows:
                chunk_id = uuid.uuid4()
                cur.execute(
                    "INSERT INTO chunks "
                    "(id, vault_binding_id, object_id, idx, offset_start, offset_end, text) "
                    "VALUES (%s, %s, %s, 0, 0, 1, 'x')",
                    (chunk_id, binding, oid),
                )
                cur.execute(
                    "INSERT INTO embeddings "
                    "(id, vault_binding_id, object_id, chunk_id, provider, dim, embedding) "
                    "VALUES (%s, %s, %s, %s, 'mock', 1, '[1]'::vector)",
                    (uuid.uuid4(), binding, oid, chunk_id),
                )
                cur.execute(
                    "INSERT INTO relations "
                    "(id, vault_binding_id, src_id, dst_id, type) "
                    "VALUES (%s, %s, %s, %s, 'self')",
                    (uuid.uuid4(), binding, oid, oid),
                )
                cur.execute(
                    "INSERT INTO membership "
                    "(id, vault_binding_id, object_id, set_id) VALUES (%s, %s, %s, %s)",
                    (uuid.uuid4(), binding, oid, set_id),
                )

        # Ingest projections have independent provenance even for the same UUID.
        for table in (
            "store_objects",
            "store_vector_index",
            "store_relations",
            "store_relation_memberships",
            "vector_index_meta",
            "chunks",
            "embeddings",
            "relations",
            "membership",
        ):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (2,), table

        unique_keys = conn.execute(
            """
            SELECT array_agg(a.attname ORDER BY k.ordinality)
              FROM pg_index i
              JOIN unnest(i.indkey::smallint[]) WITH ORDINALITY k(attnum, ordinality) ON true
              JOIN pg_attribute a
                ON a.attrelid = i.indrelid AND a.attnum = k.attnum
             WHERE i.indrelid = 'public.store_objects'::regclass AND i.indisunique
             GROUP BY i.indexrelid
            """
        ).fetchall()
    assert ["object_id"] not in [list(row[0]) for row in unique_keys]
    assert ["vault_binding_id", "object_id"] in [list(row[0]) for row in unique_keys]

    from app.stores import pg

    monkeypatch.setattr(pg, "_TABLES_READY", False)
    pg.truncate_pg_tables(vault_binding_id="binding-b")
    with psycopg.connect(migrated_store_dsn) as conn:
        for table in (
            "store_objects",
            "store_vector_index",
            "store_relations",
            "store_relation_memberships",
            "vector_index_meta",
            "chunks",
            "embeddings",
            "relations",
            "membership",
        ):
            assert conn.execute(
                f"SELECT count(*) FROM {table} WHERE vault_binding_id='binding-a'"
            ).fetchone() == (1,), table
            assert conn.execute(
                f"SELECT count(*) FROM {table} WHERE vault_binding_id='binding-b'"
            ).fetchone() == (0,), table


def test_atomic_create_once_conflict_identity_is_binding_scoped(
    migrated_store_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A winner in one binding cannot suppress the same UUID in another."""
    import app.stores.pg as pg_store

    monkeypatch.setattr(pg_store, "_TABLES_READY", False)
    object_id = uuid.uuid4()
    binding_a = pg_store.PgObjectStore(vault_binding_id="binding-a")
    binding_b = pg_store.PgObjectStore(vault_binding_id="binding-b")

    assert binding_a.put_if_absent(
        object_id,
        kind="immutable",
        source_ref="test:first-a",
        payload={"winner": "a"},
    )
    assert not binding_a.put_if_absent(
        object_id,
        kind="immutable",
        source_ref="test:second-a",
        payload={"winner": "wrong"},
    )
    assert binding_b.put_if_absent(
        object_id,
        kind="immutable",
        source_ref="test:first-b",
        payload={"winner": "b"},
    )

    assert binding_a.get(object_id)["payload"] == {"winner": "a"}
    assert binding_b.get(object_id)["payload"] == {"winner": "b"}
    with psycopg.connect(migrated_store_dsn) as conn:
        assert conn.execute(
            "SELECT count(*) FROM store_objects WHERE object_id = %s", (object_id,)
        ).fetchone() == (2,)
