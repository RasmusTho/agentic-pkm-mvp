"""Store schema parity between Alembic and `_ensure_tables()` (KERNEL-04, #2766).

Audit invariant I-S3: one schema authority per database. The `c2766a04d001`
migration must produce exactly the store-table shape the audited
`_ensure_tables()` bootstrap produced, and re-running migrations on an
existing environment must be a no-op (no data movement).

Spec: docs/RUNTIME_CORRECTNESS_KERNEL/STORE_SCHEMA_IN_MIGRATIONS.md
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[2]

STORE_TABLES = (
    "store_objects",
    "store_vector_index",
    "store_relations",
    "store_relation_memberships",
    "vector_index_meta",
)

# The last schema revision before the store tables became migration-owned.
PRE_STORE_HEAD = "5b8ff54bed0f"


def _admin_dsn() -> str:
    from app.db.dsn import resolve_dsn

    dsn = resolve_dsn()
    if not dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    return dsn


def _scratch_dsn(admin_dsn: str, dbname: str) -> str:
    base, _, _ = admin_dsn.rpartition("/")
    return f"{base}/{dbname}"


@pytest.fixture
def scratch_db_factory(monkeypatch: pytest.MonkeyPatch):
    """Create throwaway databases on the configured Postgres; drop them after."""
    admin_dsn = _admin_dsn()
    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=2)
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")
    probe.close()

    created: list[str] = []

    def _create() -> str:
        name = f"scratch_kernel04_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{name}"')
        created.append(name)
        dsn = _scratch_dsn(admin_dsn, name)
        # The standard harness runs on a pgvector image (docker-compose.yaml:
        # pgvector/pgvector); the pre-existing 202510241200 migration declares
        # `embedding VECTOR` unconditionally, so the extension must exist in
        # the target database before `alembic upgrade`. ENABLE_VECTOR stays at
        # its repo-wide default (unset): no environment sets it, and its
        # ivfflat branch does not run in any real channel.
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        return dsn

    yield _create

    for name in created:
        try:
            with psycopg.connect(admin_dsn, autocommit=True) as conn:
                conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        except Exception:
            pass


def _alembic_upgrade(dsn: str, monkeypatch: pytest.MonkeyPatch, revision: str = "head") -> None:
    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    command.upgrade(cfg, revision)


def _run_ensure_tables(dsn: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.stores.pg as pg_module

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    monkeypatch.setattr(pg_module, "_TABLES_READY", False)
    pg_module._ensure_tables()
    monkeypatch.setattr(pg_module, "_TABLES_READY", False)


def _schema_snapshot(dsn: str) -> dict:
    """Column/PK/CHECK shape of the five store tables, normalized for comparison."""
    snapshot: dict[str, dict] = {}
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            for table in STORE_TABLES:
                cur.execute(
                    """
                    SELECT column_name, data_type, is_nullable,
                           COALESCE(column_default, '') AS column_default
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s
                    ORDER BY column_name
                    """,
                    (table,),
                )
                columns = [tuple(row) for row in cur.fetchall()]
                cur.execute(
                    """
                    SELECT kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                     AND tc.table_schema = kcu.table_schema
                    WHERE tc.table_schema = 'public'
                      AND tc.table_name = %s
                      AND tc.constraint_type = 'PRIMARY KEY'
                    ORDER BY kcu.ordinal_position
                    """,
                    (table,),
                )
                pk = [row[0] for row in cur.fetchall()]
                cur.execute(
                    """
                    SELECT pg_get_constraintdef(oid)
                    FROM pg_constraint
                    WHERE conrelid = %s::regclass AND contype = 'c'
                    ORDER BY 1
                    """,
                    (f"public.{table}",),
                )
                checks = sorted(row[0] for row in cur.fetchall())
                snapshot[table] = {"columns": columns, "pk": pk, "checks": checks}
    return snapshot


def test_fresh_db_parity(scratch_db_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fresh-DB `alembic upgrade head` == the audited `_ensure_tables()` shape."""
    migrated = scratch_db_factory()
    bootstrapped = scratch_db_factory()

    _alembic_upgrade(migrated, monkeypatch)
    _run_ensure_tables(bootstrapped, monkeypatch)

    migrated_shape = _schema_snapshot(migrated)
    bootstrapped_shape = _schema_snapshot(bootstrapped)

    assert migrated_shape == bootstrapped_shape, (
        "Alembic-produced store schema diverges from _ensure_tables() shape:\n"
        f"alembic: {json.dumps(migrated_shape, indent=2, default=str)}\n"
        f"bootstrap: {json.dumps(bootstrapped_shape, indent=2, default=str)}"
    )
    # Every table actually exists (non-empty column sets).
    for table in STORE_TABLES:
        assert migrated_shape[table]["columns"], f"{table} missing after alembic upgrade head"


def test_upgrade_idempotent_on_existing(scratch_db_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Existing environments (pre-KERNEL-04 head + bootstrap-created store tables) no-op."""
    dsn = scratch_db_factory()

    # Simulate an existing environment: schema lineage at the pre-store head,
    # store tables created by the historical create-on-demand bootstrap.
    _alembic_upgrade(dsn, monkeypatch, PRE_STORE_HEAD)
    _run_ensure_tables(dsn, monkeypatch)

    object_id = uuid.uuid4()
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO store_objects (object_id, kind, source_ref, payload) "
            "VALUES (%s, 'note', 'test://existing', '{}'::jsonb)",
            (object_id,),
        )
        conn.execute(
            "INSERT INTO vector_index_meta (id, identity_json) VALUES (1, %s)",
            (json.dumps({"provider": "ollama", "model": "m", "dim": 8, "normalize": True}),),
        )

    before = _schema_snapshot(dsn)
    _alembic_upgrade(dsn, monkeypatch)  # applies only the store-schema revision
    after = _schema_snapshot(dsn)

    assert before == after, "Migration changed an existing environment's store schema"
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT count(*) FROM store_objects WHERE object_id = %s", (object_id,)
        ).fetchone()
        assert row is not None and row[0] == 1, "Migration moved/destroyed existing data"
        meta = conn.execute("SELECT count(*) FROM vector_index_meta WHERE id = 1").fetchone()
        assert meta is not None and meta[0] == 1
