"""Assert-only `_ensure_tables()` outside tests (KERNEL-04, #2766).

A Postgres-backed runtime with a missing store table must fail loud with a
"run migrations" hint at the production call sites (`PgObjectStore` /
`PgVectorIndex` construction) instead of creating schema imperatively.

Spec: docs/RUNTIME_CORRECTNESS_KERNEL/STORE_SCHEMA_IN_MIGRATIONS.md
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest

from app.db.errors import StoreSchemaMissingError

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def scratch_db(monkeypatch: pytest.MonkeyPatch):
    """A throwaway database at `alembic upgrade head`, wired into DATABASE_URL."""
    from app.db.dsn import resolve_dsn

    admin_dsn = resolve_dsn()
    if not admin_dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=2)
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")
    probe.close()

    name = f"scratch_assertonly_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = admin_dsn.rpartition("/")
    dsn = f"{base}/{name}"

    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    # See tests/migrations/test_store_schema_parity.py: the 202510241200
    # migration declares `embedding VECTOR`, so the pgvector extension must
    # exist in the scratch database (standard harness = pgvector image).
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    command.upgrade(cfg, "head")

    yield dsn

    try:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    except Exception:
        pass


def _fresh_pg_module(monkeypatch: pytest.MonkeyPatch):
    import app.stores.pg as pg_module

    monkeypatch.setattr(pg_module, "_TABLES_READY", False)
    return pg_module


def test_missing_table_raises(scratch_db, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing store table + no autocreate opt-in => StoreSchemaMissingError with hint.

    The dedicated type matters: the outbox worker classifies it transient
    (boot-ordering), so it must be exactly what the preflight raises.
    """
    pg_module = _fresh_pg_module(monkeypatch)
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)

    with psycopg.connect(scratch_db, autocommit=True) as conn:
        conn.execute("DROP TABLE store_vector_index")

    with pytest.raises(StoreSchemaMissingError, match="alembic upgrade head"):
        pg_module.PgObjectStore()

    monkeypatch.setattr(pg_module, "_TABLES_READY", False)
    with pytest.raises(StoreSchemaMissingError, match="alembic upgrade head"):
        pg_module.PgVectorIndex()


def test_missing_identity_column_raises(scratch_db, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing store_vector_index identity column also fails loud with the hint."""
    pg_module = _fresh_pg_module(monkeypatch)
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)

    with psycopg.connect(scratch_db, autocommit=True) as conn:
        conn.execute("ALTER TABLE store_vector_index DROP COLUMN provider")

    with pytest.raises(StoreSchemaMissingError, match="alembic upgrade head"):
        pg_module.PgObjectStore()


def test_transactional_object_write_preflights_partial_schema(
    scratch_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The filesystem producer must fail before writing against a partial store schema."""
    from app.objects import DomainObject, save_object_in_transaction

    pg_module = _fresh_pg_module(monkeypatch)
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
    object_id = uuid.uuid4()
    with psycopg.connect(scratch_db) as conn:
        conn.execute("ALTER TABLE store_vector_index DROP COLUMN provider")
        with pytest.raises(StoreSchemaMissingError, match="alembic upgrade head"):
            save_object_in_transaction(
                conn,
                DomainObject(
                    uuid=object_id,
                    kind="note",
                    payload={"content": "must not persist"},
                    source_ref="vault://partial.md",
                    created_at=datetime.now(timezone.utc),
                ),
            )
        conn.rollback()
        row = conn.execute(
            "SELECT 1 FROM store_objects WHERE object_id = %s", (object_id,)
        ).fetchone()
        assert row is None
    assert pg_module._TABLES_READY is False


def test_migrated_schema_passes_assert_only(scratch_db, monkeypatch: pytest.MonkeyPatch) -> None:
    """With the migration applied, assert-only construction succeeds without autocreate."""
    pg_module = _fresh_pg_module(monkeypatch)
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)

    store = pg_module.PgObjectStore()
    assert store is not None
    monkeypatch.setattr(pg_module, "_TABLES_READY", False)
    index = pg_module.PgVectorIndex()
    assert index is not None


def test_null_dim_row_repaired_and_queryable(scratch_db, monkeypatch: pytest.MonkeyPatch) -> None:
    """The assert-only preflight keeps the old boot path's dim data repair.

    Legacy environments hold rows written before the `dim` column existed
    (added as a nullable ALTER). `PgVectorIndex.search` filters
    `WHERE dim = %s`, so without the boot-time
    `UPDATE ... SET dim = array_length(embedding, 1) WHERE dim IS NULL`
    repair a NULL-dim row silently vanishes from retrieval (I-S3 class).
    """
    from app.components.embeddings import EmbeddingIdentity

    pg_module = _fresh_pg_module(monkeypatch)
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)

    identity = EmbeddingIdentity(provider="ollama", model="m", dim=4, normalize=True)
    object_id = uuid.uuid4()
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        # Simulate the legacy shape: dim nullable (as an ALTER-added column),
        # one row written before dim existed.
        conn.execute("ALTER TABLE store_vector_index ALTER COLUMN dim DROP NOT NULL")
        conn.execute(
            "INSERT INTO vector_index_meta (id, identity_json) VALUES (1, %s)",
            (json.dumps({"provider": "ollama", "model": "m", "dim": 4, "normalize": True}),),
        )
        conn.execute(
            """
            INSERT INTO store_vector_index
                (object_id, kind, source_ref, payload, embedding, dim, model)
            VALUES (%s, 'note', 'test://legacy', '{}'::jsonb, %s, NULL, 'm')
            """,
            (object_id, [1.0, 0.0, 0.0, 0.0]),
        )

    index = pg_module.PgVectorIndex()  # preflight runs the data repair

    with psycopg.connect(scratch_db) as conn:
        row = conn.execute(
            "SELECT dim FROM store_vector_index WHERE object_id = %s", (object_id,)
        ).fetchone()
        assert row is not None and row[0] == 4, "preflight did not backfill NULL dim"

    hits = index.search([1.0, 0.0, 0.0, 0.0], k=5, identity=identity)
    assert [hit.object_id for hit in hits] == [
        object_id
    ], "NULL-dim row not queryable after preflight repair"
