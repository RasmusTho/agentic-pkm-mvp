"""YSS-06 scheduler state against the real migration-owned Postgres table.

This suite exists because its absence shipped a P0. Every other scheduler test
runs `not_pg` against `MemorySyncStateStore`, whose genuine string-keyed dicts
make row-shape mistakes structurally unobservable, and `mypy` cannot help
because `app.db.db.conn_rw` is untyped. An earlier revision indexed
`conn_rw`'s `dict_row` results positionally (`row[0]`), so `for_runtime()`
raised `KeyError(0)` on every tick *with the table fully present* — the whole
capability was inert in production and surfaced only as `error: "0"`.

So: construct the production store against real Postgres, and exercise the two
read paths plus the lease semantics the exclusion invariant depends on.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from sqlalchemy.engine import URL

from app.knowledge_acquisition.sync_scheduler import LEASE_KEY, LEASE_TTL_SECONDS
from app.knowledge_acquisition.sync_state import (
    SyncStateSchemaMissingError,
    for_runtime,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
YSS06_HEAD = "c9d0e1f2a3b4"
PRE_YSS06_HEAD = "b7e3c9d5a1f2"

NOW = datetime(2026, 9, 22, 12, 0, 0, tzinfo=timezone.utc)


def _alembic_config() -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    return config


@pytest.fixture
def scratch_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[Config]:
    from app.db.dsn import resolve_dsn

    admin_dsn = resolve_dsn()
    if not admin_dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    try:
        with psycopg.connect(admin_dsn, connect_timeout=2):
            pass
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")

    database_name = f"scratch_yss06_state_{uuid.uuid4().hex[:12]}"
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
        yield _alembic_config()
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')


@pytest.mark.pg
def test_pg_state_store_reads_its_own_rows(scratch_database: Config) -> None:
    # The regression this file exists for: constructing the store runs the
    # schema preflight, and reading a row goes through the other dict_row site.
    command.upgrade(scratch_database, YSS06_HEAD)

    store = for_runtime()  # raised KeyError(0) here before the fix

    assert store.get("absent") is None

    store.set("backoff:inbox", {"consecutive_failures": 3, "last_attempt_at": NOW.isoformat()})
    row = store.get("backoff:inbox")
    assert row is not None
    assert row["consecutive_failures"] == 3
    assert row["last_attempt_at"] == NOW.isoformat()

    store.set("backoff:inbox", {"consecutive_failures": 0})
    replaced = store.get("backoff:inbox")
    assert replaced is not None
    assert replaced["consecutive_failures"] == 0
    assert "last_attempt_at" not in replaced, "set replaces the row rather than merging"


@pytest.mark.pg
def test_pg_lease_excludes_a_second_runner_and_expires(scratch_database: Config) -> None:
    command.upgrade(scratch_database, YSS06_HEAD)
    store = for_runtime()

    first = "host-a:101:aaaaaaaa"
    second = "host-b:202:bbbbbbbb"

    assert store.acquire_lease(
        key=LEASE_KEY, holder=first, ttl_seconds=LEASE_TTL_SECONDS, now=NOW
    ) is True
    assert store.acquire_lease(
        key=LEASE_KEY, holder=second, ttl_seconds=LEASE_TTL_SECONDS, now=NOW
    ) is False, "a live lease must exclude a different runner"

    # The holder may re-acquire: that is what makes a retry and a heartbeat work.
    assert store.acquire_lease(
        key=LEASE_KEY, holder=first, ttl_seconds=LEASE_TTL_SECONDS, now=NOW
    ) is True

    # Releasing is holder-scoped, so a stale runner cannot delete a live lease.
    store.release_lease(key=LEASE_KEY, holder=second)
    assert store.get(LEASE_KEY) is not None, "release by a non-holder must be a no-op"

    # An expired lease is taken over rather than honoured forever.
    later = NOW + timedelta(seconds=LEASE_TTL_SECONDS + 1)
    assert store.acquire_lease(
        key=LEASE_KEY, holder=second, ttl_seconds=LEASE_TTL_SECONDS, now=later
    ) is True

    held = store.get(LEASE_KEY)
    assert held is not None and held["holder"] == second

    store.release_lease(key=LEASE_KEY, holder=second)
    assert store.get(LEASE_KEY) is None


@pytest.mark.pg
def test_pg_schema_preflight_fails_loud_before_the_migration(
    scratch_database: Config,
) -> None:
    # Fail-loud rather than a raw UndefinedTable from inside a later query.
    command.upgrade(scratch_database, PRE_YSS06_HEAD)

    with pytest.raises(SyncStateSchemaMissingError) as excinfo:
        for_runtime()

    assert "alembic upgrade head" in str(excinfo.value)
