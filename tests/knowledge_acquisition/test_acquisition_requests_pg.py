"""YSS-04 (#3919): acquisition queue service contract, Postgres backend.

Exercises the SAME service-layer contract suite as the memory backend
(`_acquisition_requests_contract.py`, driven for memory by
`test_acquisition_requests.py`) against the real Postgres-backed
`AcquisitionRequests`, proving the queue semantics hold identically on both
backends (AC7) and that the forward-only migration `b5c6d7e8f9a0` creates the
schema the store's fail-loud preflight expects.

Marked `pg`: excluded by the default `-m "not pg"` suite. Mirrors
`test_source_registry_pg.py` / `test_youtube_account_binding_pg.py` — an
isolated database, upgraded through Alembic with schema autocreate disabled
(the migration, not the store bootstrap, owns the schema), then the shared
contract, then the forward-only downgrade assertion.
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

from app.knowledge_acquisition.acquisition_requests import AcquisitionRequests
from tests.knowledge_acquisition._acquisition_requests_contract import ALL_CONTRACT_ASSERTIONS

REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_YSS04_HEAD = "a2f1c3e4d5b6"
YSS04_HEAD = "b5c6d7e8f9a0"


def _alembic_config() -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    return config


@pytest.fixture
def migrated_queue_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[Config]:
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

    database_name = f"scratch_yss04_queue_{uuid.uuid4().hex[:12]}"
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
        command.upgrade(config, YSS04_HEAD)
        yield config
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')


@pytest.mark.pg
def test_pg_backend_contract(migrated_queue_database: Config) -> None:
    for assertion in ALL_CONTRACT_ASSERTIONS:
        assertion(lambda: AcquisitionRequests.for_runtime())

    # The migration is forward-only (reversibility marker; downgrade raises).
    with pytest.raises(RuntimeError, match="forward-only"):
        command.downgrade(migrated_queue_database, PRE_YSS04_HEAD)
