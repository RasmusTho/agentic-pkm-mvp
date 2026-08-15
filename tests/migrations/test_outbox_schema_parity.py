"""Outbox schema parity between Alembic and `bootstrap()` (KERNEL-05, #2850).

Follow-up to KERNEL-04 (#2766): the same create-on-boot class existed for the
DB outbox (`app/services/outbox.py::bootstrap()`), including a nested
`except Exception: pass` around `ensure_schema` (silent-failure seam on the
canonical queue). This test asserts the current outbox migration produces
exactly the table shape the audited `bootstrap()` produces, and that upgrading
an existing environment preserves its rows while installing binding metadata.

Spec: docs/RUNTIME_CORRECTNESS_KERNEL/STORE_SCHEMA_IN_MIGRATIONS.md (pattern
precedent); docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: I-S3
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[2]

# The head revision before the outbox table became migration-owned.
PRE_OUTBOX_HEAD = "699c97b7c007"

# The current outbox-schema-owning revision this test asserts parity against.
# Pinned explicitly (not "head") so unrelated later DDL cannot move the target.
OUTBOX_SCHEMA_HEAD = "f6a05a7b0001"


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
        name = f"scratch_kernel05_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{name}"')
        created.append(name)
        dsn = _scratch_dsn(admin_dsn, name)
        # The standard harness runs on a pgvector image (docker-compose.yaml:
        # pgvector/pgvector); an earlier migration declares `embedding VECTOR`
        # unconditionally, so the extension must exist before `alembic upgrade`
        # (mirrors tests/migrations/test_store_schema_parity.py).
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


def _run_bootstrap(dsn: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import outbox as outbox_module

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    outbox_module.bootstrap()


def _create_authoritative_outbox(dsn: str) -> None:
    """Install only the outbox shape owned by Alembic revision f3a1c9d2e4b7."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            """
            CREATE TABLE outbox (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                topic TEXT NOT NULL,
                payload JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                delivered_at TIMESTAMPTZ,
                attempts INT NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute("CREATE INDEX outbox_created_idx ON outbox (created_at)")
        conn.execute("CREATE INDEX outbox_delivered_idx ON outbox (delivered_at)")


def _schema_snapshot(dsn: str) -> dict:
    """Column/PK/index shape of the outbox table, normalized for comparison."""
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name, data_type, is_nullable,
                       COALESCE(column_default, '') AS column_default
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'outbox'
                ORDER BY column_name
                """
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
                  AND tc.table_name = 'outbox'
                  AND tc.constraint_type = 'PRIMARY KEY'
                ORDER BY kcu.ordinal_position
                """
            )
            pk = [row[0] for row in cur.fetchall()]
            cur.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'public' AND tablename = 'outbox'
                ORDER BY indexname
                """
            )
            indexes = [tuple(row) for row in cur.fetchall()]
    return {"columns": columns, "pk": pk, "indexes": indexes}


def test_fresh_db_parity(scratch_db_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fresh-DB `alembic upgrade <OUTBOX_SCHEMA_HEAD>` == the audited `bootstrap()` shape."""
    migrated = scratch_db_factory()
    bootstrapped = scratch_db_factory()

    _alembic_upgrade(migrated, monkeypatch, OUTBOX_SCHEMA_HEAD)
    _run_bootstrap(bootstrapped, monkeypatch)

    migrated_shape = _schema_snapshot(migrated)
    bootstrapped_shape = _schema_snapshot(bootstrapped)

    assert migrated_shape == bootstrapped_shape, (
        "Alembic-produced outbox schema diverges from bootstrap() shape:\n"
        f"alembic: {json.dumps(migrated_shape, indent=2, default=str)}\n"
        f"bootstrap: {json.dumps(bootstrapped_shape, indent=2, default=str)}"
    )
    assert migrated_shape["columns"], "outbox table missing after alembic upgrade"


def test_outbox_declares_the_binding_and_legacy_key_columns_in_both_shapes(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrated = scratch_db_factory()
    bootstrapped = scratch_db_factory()
    _alembic_upgrade(migrated, monkeypatch, OUTBOX_SCHEMA_HEAD)
    _run_bootstrap(bootstrapped, monkeypatch)

    for shape in (_schema_snapshot(migrated), _schema_snapshot(bootstrapped)):
        columns = {row[0]: row for row in shape["columns"]}
        assert columns["vault_binding_id"][1:3] == ("text", "NO")
        assert columns["legacy_key"][1:3] == ("uuid", "YES")


def test_upgrade_preserves_existing_rows_and_installs_binding_metadata(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing scalar rows survive and become explicit compatibility history."""
    dsn = scratch_db_factory()

    # Simulate an existing environment: schema lineage at the pre-outbox head,
    # outbox table created by the historical create-on-demand bootstrap.
    _alembic_upgrade(dsn, monkeypatch, PRE_OUTBOX_HEAD)
    _run_bootstrap(dsn, monkeypatch)

    row_id = uuid.uuid4()
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO outbox (id, topic, payload) VALUES (%s, %s, %s::jsonb)",
            (row_id, "test.topic", "{}"),
        )

    _alembic_upgrade(dsn, monkeypatch, OUTBOX_SCHEMA_HEAD)
    after = _schema_snapshot(dsn)

    columns = {row[0]: row for row in after["columns"]}
    assert columns["vault_binding_id"][1:3] == ("text", "NO")
    assert columns["legacy_key"][1:3] == ("uuid", "YES")
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT id, legacy_key, vault_binding_id FROM outbox WHERE id = %s", (row_id,)
        ).fetchone()
        assert row == (row_id, row_id, "legacy-compatibility-binding")
