"""Assert-only `_ensure_tables()` outside tests (KERNEL-04, #2766).

A Postgres-backed runtime with a missing store table must fail loud with a
"run migrations" hint at the production call sites (`PgObjectStore` /
`PgVectorIndex` construction) instead of creating schema imperatively.

Spec: docs/RUNTIME_CORRECTNESS_KERNEL/STORE_SCHEMA_IN_MIGRATIONS.md
"""

from __future__ import annotations

import uuid
from pathlib import Path

import psycopg
import pytest

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
    """Missing store table + no autocreate opt-in => RuntimeError with migration hint."""
    pg_module = _fresh_pg_module(monkeypatch)
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)

    with psycopg.connect(scratch_db, autocommit=True) as conn:
        conn.execute("DROP TABLE store_vector_index")

    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        pg_module.PgObjectStore()

    monkeypatch.setattr(pg_module, "_TABLES_READY", False)
    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        pg_module.PgVectorIndex()


def test_missing_identity_column_raises(scratch_db, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing store_vector_index identity column also fails loud with the hint."""
    pg_module = _fresh_pg_module(monkeypatch)
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)

    with psycopg.connect(scratch_db, autocommit=True) as conn:
        conn.execute("ALTER TABLE store_vector_index DROP COLUMN provider")

    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        pg_module.PgObjectStore()


def test_migrated_schema_passes_assert_only(scratch_db, monkeypatch: pytest.MonkeyPatch) -> None:
    """With the migration applied, assert-only construction succeeds without autocreate."""
    pg_module = _fresh_pg_module(monkeypatch)
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)

    store = pg_module.PgObjectStore()
    assert store is not None
    monkeypatch.setattr(pg_module, "_TABLES_READY", False)
    index = pg_module.PgVectorIndex()
    assert index is not None
