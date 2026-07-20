"""YSS-02 (#3917): account-binding registry service contract, Postgres backend.

Exercises the SAME service-layer contract as the memory backend (which
``tests/knowledge_acquisition/test_youtube_oauth.py`` drives implicitly) against
the real Postgres-backed ``AccountBindingStore``, proving the integrity rules
hold identically on both backends and that the forward-only migration
``e1f2a3b4c5d6`` creates the generation-CAS schema the store's fail-loud
preflight expects. It also proves that an already-stamped pre-repair database
is upgraded without losing existing bindings.

Marked ``pg``: excluded by the default ``-m "not pg"`` suite; does not run
locally without a real Postgres. Mirrors ``test_source_registry_pg.py`` -- an
isolated database, upgraded through Alembic with schema autocreate disabled (so
the migration, not the store's bootstrap, owns the schema), then the contract,
then the forward-only downgrade assertion.
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

from app.knowledge_acquisition.youtube_account_binding import (
    AccountBindingGenerationConflictError,
    AccountBindingSchemaMissingError,
    AccountBindingStore,
    AccountBindingValidationError,
    DuplicateAccountBindingError,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_BINDING_GENERATION_HEAD = "d9e0f1a2b3c4"
BINDING_GENERATION_HEAD = "e1f2a3b4c5d6"

# Synthetic ids only (INV-YSS-9).
CHANNEL_A = "UC__test__acct_binding_pg_a"
CHANNEL_B = "UC__test__acct_binding_pg_b"
SCOPE = "https://www.googleapis.com/auth/youtube.readonly"


def _alembic_config() -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    return config


@pytest.fixture
def scratch_binding_database(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[Config, str]]:
    """Yield an isolated empty database and drop it afterwards."""
    from app.db.dsn import resolve_dsn

    admin_dsn = resolve_dsn()
    if not admin_dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    try:
        with psycopg.connect(admin_dsn, connect_timeout=2):
            pass
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")

    database_name = f"scratch_yss02_binding_{uuid.uuid4().hex[:12]}"
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
        yield config, scratch_conninfo
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')


@pytest.fixture
def migrated_binding_database(
    scratch_binding_database: tuple[Config, str],
) -> Config:
    """Yield an isolated database migrated through the generation-CAS head."""
    config, _scratch_conninfo = scratch_binding_database
    command.upgrade(config, BINDING_GENERATION_HEAD)
    return config


@pytest.mark.pg
def test_pg_backend_contract(migrated_binding_database: Config) -> None:
    store = AccountBindingStore.for_runtime()

    created = store.create(
        provider_channel_id=CHANNEL_A, display_label="Chan A", scopes=[SCOPE]
    )
    assert created.state == "connected"
    assert created.reason_code is None
    assert created.scopes == (SCOPE,)
    assert created.binding_generation == 1

    # Round-trips out of Postgres unchanged.
    fetched = store.get(created.account_binding_id)
    assert fetched is not None
    assert fetched.provider_channel_id == CHANNEL_A
    assert store.get_by_channel_id(CHANNEL_A).account_binding_id == created.account_binding_id

    # Degrade → reason set; reconnect → reason cleared.
    degraded = store.set_state(
        created.account_binding_id,
        state="degraded",
        reason_code="auth_revoked",
        expected_binding_generation=created.binding_generation,
    )
    assert degraded.state == "degraded"
    assert degraded.reason_code == "auth_revoked"
    assert degraded.binding_generation == 2
    reconnected = store.set_state(
        created.account_binding_id,
        state="connected",
        reason_code=None,
        expected_binding_generation=degraded.binding_generation,
    )
    assert reconnected.state == "connected"
    assert reconnected.reason_code is None
    assert reconnected.binding_generation == 3

    # A stale compare-and-set cannot overwrite or otherwise mutate the winner.
    with pytest.raises(AccountBindingGenerationConflictError):
        store.set_state(
            created.account_binding_id,
            state="degraded",
            reason_code="auth_revoked",
            expected_binding_generation=degraded.binding_generation,
        )
    assert store.get(created.account_binding_id) == reconnected

    # One binding per channel (unique index).
    with pytest.raises(DuplicateAccountBindingError):
        store.create(provider_channel_id=CHANNEL_A, display_label="dup", scopes=[SCOPE])

    # A connected binding may not carry a reason code (service + DB check).
    with pytest.raises(AccountBindingValidationError):
        store.set_state(created.account_binding_id, state="connected", reason_code="auth_revoked")

    # A second, distinct channel is fine.
    other = store.create(provider_channel_id=CHANNEL_B, display_label="Chan B", scopes=[SCOPE])
    assert {b.account_binding_id for b in store.list_all()} == {
        created.account_binding_id,
        other.account_binding_id,
    }

    # Delete removes exactly one row.
    assert store.delete(created.account_binding_id) is True
    assert store.get(created.account_binding_id) is None
    assert store.delete(created.account_binding_id) is False

    # The migration is forward-only.
    with pytest.raises(RuntimeError, match="forward-only"):
        command.downgrade(migrated_binding_database, PRE_BINDING_GENERATION_HEAD)


@pytest.mark.pg
def test_existing_resource_upgrade_backfills_generation_and_restores_schema(
    scratch_binding_database: tuple[Config, str],
) -> None:
    config, scratch_conninfo = scratch_binding_database
    command.upgrade(config, PRE_BINDING_GENERATION_HEAD)

    pre_repair_store = AccountBindingStore.for_runtime()
    existing = pre_repair_store.create(
        provider_channel_id=CHANNEL_A,
        display_label="Existing Chan",
        scopes=[SCOPE],
    )
    assert existing.binding_generation == 1

    # Model an existing DB stamped past the original YSS-02 migration before
    # binding_generation became a runtime invariant.
    with psycopg.connect(scratch_conninfo) as conn:
        conn.execute(
            "ALTER TABLE youtube_account_binding "
            "DROP CONSTRAINT IF EXISTS youtube_account_binding_generation_chk"
        )
        conn.execute(
            "ALTER TABLE youtube_account_binding "
            "DROP COLUMN IF EXISTS binding_generation"
        )

    with pytest.raises(AccountBindingSchemaMissingError, match="binding_generation"):
        AccountBindingStore.for_runtime()

    command.upgrade(config, BINDING_GENERATION_HEAD)

    upgraded_store = AccountBindingStore.for_runtime()
    upgraded = upgraded_store.get(existing.account_binding_id)
    assert upgraded is not None
    assert upgraded.provider_channel_id == CHANNEL_A
    assert upgraded.binding_generation == 1

    with psycopg.connect(scratch_conninfo) as conn:
        column_shape = conn.execute(
            "SELECT data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = current_schema() "
            "AND table_name = 'youtube_account_binding' "
            "AND column_name = 'binding_generation'"
        ).fetchone()
        constraint = conn.execute(
            "SELECT pg_get_constraintdef(oid) "
            "FROM pg_constraint "
            "WHERE conname = 'youtube_account_binding_generation_chk' "
            "AND conrelid = 'youtube_account_binding'::regclass"
        ).fetchone()

    assert column_shape == ("bigint", "NO")
    assert constraint is not None
    assert "binding_generation >= 1" in constraint[0]
