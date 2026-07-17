"""YSS-01 schema parity: migration, bootstrap, and existing-resource repair."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[2]
TABLE = "acquisition_source_registry"
PRE_YSS01_HEAD = "e1d2c3b4a5f6"
YSS01_HEAD = "bd79f3044759"


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
def scratch_db_factory() -> object:
    admin_dsn = _admin_dsn()
    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=2)
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")
    probe.close()
    created: list[str] = []

    def _create() -> str:
        name = f"scratch_yss01_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{name}"')
        created.append(name)
        dsn = _scratch_dsn(admin_dsn, name)
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


def _alembic_upgrade(dsn: str, monkeypatch: pytest.MonkeyPatch, revision: str) -> None:
    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    command.upgrade(config, revision)


def _run_bootstrap(dsn: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.knowledge_acquisition import source_registry

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    with psycopg.connect(dsn, autocommit=True) as conn:
        source_registry._bootstrap_pg(conn)


def _schema_snapshot(dsn: str) -> dict[str, object]:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name, data_type, is_nullable, COALESCE(column_default, '')
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY column_name
                """,
                (TABLE,),
            )
            columns = [tuple(row) for row in cur.fetchall()]
            cur.execute(
                """
                SELECT pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conrelid = %s::regclass AND contype IN ('p', 'c')
                ORDER BY 1
                """,
                (f"public.{TABLE}",),
            )
            constraints = [row[0] for row in cur.fetchall()]
            cur.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'public' AND tablename = %s
                ORDER BY indexname
                """,
                (TABLE,),
            )
            indexes = [tuple(row) for row in cur.fetchall()]
    return {"columns": columns, "constraints": constraints, "indexes": indexes}


def test_yss01_migration_bootstrap_parity_and_legacy_repair(
    scratch_db_factory: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bootstrap table and a migrated table have identical enforced shape."""
    create = scratch_db_factory
    assert callable(create)
    migrated = create()
    bootstrapped = create()
    legacy = create()

    _alembic_upgrade(migrated, monkeypatch, YSS01_HEAD)
    _run_bootstrap(bootstrapped, monkeypatch)

    migrated_shape = _schema_snapshot(migrated)
    bootstrapped_shape = _schema_snapshot(bootstrapped)
    assert migrated_shape == bootstrapped_shape, (
        "Alembic-produced YSS-01 schema diverges from bootstrap shape:\n"
        f"alembic: {json.dumps(migrated_shape, indent=2, default=str)}\n"
        f"bootstrap: {json.dumps(bootstrapped_shape, indent=2, default=str)}"
    )

    # Simulate the old bootstrap producer, then ensure the migration upgrades
    # the existing resource rather than silently accepting missing constraints.
    _alembic_upgrade(legacy, monkeypatch, PRE_YSS01_HEAD)
    _run_bootstrap(legacy, monkeypatch)
    with psycopg.connect(legacy, autocommit=True) as conn:
        for constraint in (
            "acquisition_source_registry_kind_chk",
            "acquisition_source_registry_discovery_mode_chk",
            "acquisition_source_registry_priority_chk",
            "acquisition_source_registry_poll_interval_chk",
            "acquisition_source_registry_account_binding_chk",
            "acquisition_source_registry_account_binding_uuid_chk",
        ):
            conn.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT {constraint}")
        conn.execute("DROP INDEX acquisition_source_registry_account_idx")
    _alembic_upgrade(legacy, monkeypatch, YSS01_HEAD)
    assert _schema_snapshot(legacy) == migrated_shape
