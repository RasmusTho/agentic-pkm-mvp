"""YSS-03 durable quota accounting against the migration-owned Postgres row."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from sqlalchemy.engine import URL

from app.knowledge_acquisition.youtube_api_client import YouTubeQuotaStore

REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_YSS03_HEAD = "c8d9e0f1a2b3"
YSS03_HEAD = "d9e0f1a2b3c4"


def _alembic_config() -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    return config


@pytest.fixture
def migrated_quota_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[Config]:
    from app.db.dsn import resolve_dsn

    admin_dsn = resolve_dsn()
    if not admin_dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    try:
        with psycopg.connect(admin_dsn, connect_timeout=2):
            pass
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")

    database_name = f"scratch_yss03_quota_{uuid.uuid4().hex[:12]}"
    scratch_params = conninfo_to_dict(admin_dsn)
    scratch_params["dbname"] = database_name
    scratch_conninfo = make_conninfo(**scratch_params)
    scratch_url = URL.create(
        "postgresql",
        username=scratch_params.get("user"),
        password=scratch_params.get("password"),
        host=scratch_params.get("host"),
        port=int(scratch_params["port"]) if scratch_params.get("port") else None,
        database=database_name,
    ).render_as_string(hide_password=False)

    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{database_name}"')
    try:
        with psycopg.connect(scratch_conninfo, autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        monkeypatch.setenv("DATABASE_URL", scratch_url)
        monkeypatch.delenv("DB_DSN", raising=False)
        monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
        monkeypatch.delenv("STORE_BACKEND", raising=False)
        config = _alembic_config()
        command.upgrade(config, YSS03_HEAD)
        yield config
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')


@pytest.mark.pg
def test_pg_quota_counter_is_durable_atomic_and_forward_only(
    migrated_quota_database: Config,
) -> None:
    clock = lambda: datetime(2026, 7, 19, 23, 59, tzinfo=timezone.utc)
    first = YouTubeQuotaStore.for_runtime(clock=clock)
    assert first.status(10) == {"spent_today": 0, "budget": 10, "exhausted": False}
    first.increment()
    first.increment()

    second = YouTubeQuotaStore.for_runtime(clock=clock)
    assert second.status(10) == {"spent_today": 2, "budget": 10, "exhausted": False}
    second.mark_exhausted()
    assert first.status(10) == {"spent_today": 2, "budget": 10, "exhausted": True}

    with pytest.raises(RuntimeError, match="forward-only"):
        command.downgrade(migrated_quota_database, PRE_YSS03_HEAD)
