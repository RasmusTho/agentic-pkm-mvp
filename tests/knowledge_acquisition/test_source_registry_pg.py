"""YSS-01 (#3916): source registry service-layer contract, Postgres backend.

Exercises the SAME service-layer contract suite as
`tests/knowledge_acquisition/test_source_registry.py` (memory backend)
against the real Postgres-backed `SourceRegistry`, via the shared assertions
in `_source_registry_contract.py` -- proving the integrity rules hold
identically on both backends (AC8: "the pg backend passes the same
service-layer suite").

Marked `pg`: excluded by the default `-m "not pg"` suite; does not run
locally without a real Postgres. The exact AC target creates an isolated
database, upgrades it through Alembic with schema autocreate disabled, runs
the shared service contract, and proves the migration's forward-only
downgrade raises.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from sqlalchemy.engine import URL

from app.knowledge_acquisition.source_registry import SourceRegistry
from tests.knowledge_acquisition._source_registry_contract import ALL_CONTRACT_ASSERTIONS

REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_YSS01_HEAD = "e1d2c3b4a5f6"
YSS01_HEAD = "bd79f3044759"


def _alembic_config() -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    return config


@pytest.fixture
def migrated_registry_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[Config]:
    """Yield an Alembic-migrated isolated database and drop it afterwards."""
    from app.db.dsn import resolve_dsn

    admin_dsn = resolve_dsn()
    if not admin_dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    try:
        with psycopg.connect(admin_dsn, connect_timeout=2):
            pass
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")

    database_name = f"scratch_yss01_contract_{uuid.uuid4().hex[:12]}"
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
        config = _alembic_config()
        command.upgrade(config, YSS01_HEAD)
        yield config
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')


def _make_pg_registry() -> SourceRegistry:
    return SourceRegistry.for_runtime()


@pytest.mark.pg
def test_pg_backend_contract(migrated_registry_database: Config) -> None:
    for assertion in ALL_CONTRACT_ASSERTIONS:
        assertion(_make_pg_registry)

    with pytest.raises(RuntimeError, match="forward-only"):
        command.downgrade(migrated_registry_database, PRE_YSS01_HEAD)
