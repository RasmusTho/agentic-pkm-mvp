"""PostgreSQL isolation proof for MVR-05A3 (#4577)."""

from __future__ import annotations

import uuid
from pathlib import Path

import psycopg
import pytest


pytestmark = pytest.mark.pg
REPO_ROOT = Path(__file__).resolve().parents[2]


def _admin_dsn() -> str:
    from app.db.dsn import resolve_dsn

    dsn = resolve_dsn()
    if not dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    return dsn


@pytest.fixture
def migrated_store_dsn(monkeypatch: pytest.MonkeyPatch):
    admin_dsn = _admin_dsn()
    name = f"scratch_mvr05a3_isolation_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = admin_dsn.rpartition("/")
    dsn = f"{base}/{name}"
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(REPO_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
        command.upgrade(cfg, "head")
        yield dsn
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_duplicate_uuid_is_namespaced_by_binding_in_store_projections(
    migrated_store_dsn: str,
) -> None:
    object_id = uuid.uuid4()
    rows = [("binding-a", object_id), ("binding-b", object_id)]
    with psycopg.connect(migrated_store_dsn) as conn:
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

        for table in (
            "store_objects",
            "store_vector_index",
            "store_relations",
            "store_relation_memberships",
            "vector_index_meta",
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
