"""Fail-loud migration coverage for #3510."""

from __future__ import annotations

import uuid
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.pg
REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_CUTOVER_REVISION = "4d1e0c9a3329"


def _admin_dsn() -> str:
    from app.db.dsn import resolve_dsn

    dsn = resolve_dsn()
    if not dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    return dsn


@pytest.fixture
def scratch_dsn(monkeypatch: pytest.MonkeyPatch):
    admin_dsn = _admin_dsn()
    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=2)
    except Exception as exc:
        pytest.skip(f"Postgres unavailable: {exc}")
    probe.close()
    name = f"scratch_legacy_fk_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = admin_dsn.rpartition("/")
    dsn = f"{base}/{name}"
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    try:
        yield dsn
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _upgrade(revision: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    command.upgrade(cfg, revision)


def test_legacy_objects_fk_migration_fails_loudly_on_unsupported_state(scratch_dsn: str) -> None:
    _upgrade(PRE_CUTOVER_REVISION)
    with psycopg.connect(scratch_dsn) as conn:
        conn.execute(
            "CREATE TABLE unreviewed_consumer ("
            "id uuid PRIMARY KEY, object_id uuid REFERENCES objects(id))"
        )

    with pytest.raises(Exception, match="unaccounted objects FK"):
        _upgrade("head")

    with psycopg.connect(scratch_dsn) as conn:
        row = conn.execute(
            "SELECT confrelid = 'public.objects'::regclass "
            "FROM pg_constraint WHERE conrelid = 'public.unreviewed_consumer'::regclass "
            "AND contype = 'f'"
        ).fetchone()
    assert row == (True,), "failed migration must roll back without partially retargeting constraints"
