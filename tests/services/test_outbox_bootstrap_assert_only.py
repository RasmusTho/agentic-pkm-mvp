"""Assert-only `bootstrap()` outside tests (KERNEL-05, #2850).

A Postgres-backed runtime with a missing outbox table must fail loud with a
"run migrations" hint at worker boot instead of creating schema imperatively,
and the previously silent `except Exception: pass` around `ensure_schema`
must be gone.

Spec: docs/RUNTIME_CORRECTNESS_KERNEL/STORE_SCHEMA_IN_MIGRATIONS.md (pattern
precedent this follows, KERNEL-04 #2766).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import psycopg
import pytest

from app.db.errors import OutboxSchemaMissingError

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

    name = f"scratch_outbox_assertonly_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = admin_dsn.rpartition("/")
    dsn = f"{base}/{name}"

    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    # See tests/migrations/test_outbox_schema_parity.py: an earlier migration
    # declares `embedding VECTOR`, so pgvector must exist in the scratch DB.
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


def test_missing_table_raises(scratch_db, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing outbox table + no autocreate opt-in => OutboxSchemaMissingError with hint.

    The dedicated type matters: the outbox worker's dispatch classifier treats
    any exception carrying ``is_transient = True`` as boot-ordering (crash-retry,
    never dead-letter) via the same generic marker check KERNEL-04 established
    for ``StoreSchemaMissingError`` — no worker-side change needed.
    """
    from app.services import outbox as outbox_module

    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)

    with psycopg.connect(scratch_db, autocommit=True) as conn:
        conn.execute("DROP TABLE outbox")

    monkeypatch.setenv("DATABASE_URL", scratch_db)
    monkeypatch.delenv("DB_DSN", raising=False)

    with pytest.raises(OutboxSchemaMissingError, match="alembic upgrade head"):
        outbox_module.bootstrap()


def test_missing_column_raises(scratch_db, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing outbox column also fails loud with the migration hint."""
    from app.services import outbox as outbox_module

    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)

    with psycopg.connect(scratch_db, autocommit=True) as conn:
        conn.execute("ALTER TABLE outbox DROP COLUMN attempts")

    monkeypatch.setenv("DATABASE_URL", scratch_db)
    monkeypatch.delenv("DB_DSN", raising=False)

    with pytest.raises(OutboxSchemaMissingError, match="alembic upgrade head"):
        outbox_module.bootstrap()


def test_migrated_schema_passes_assert_only(scratch_db, monkeypatch: pytest.MonkeyPatch) -> None:
    """With the migration applied, assert-only bootstrap succeeds without autocreate."""
    from app.services import outbox as outbox_module

    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
    monkeypatch.setenv("DATABASE_URL", scratch_db)
    monkeypatch.delenv("DB_DSN", raising=False)

    outbox_module.bootstrap()  # must not raise


def test_is_transient_marker_classifies_boot_ordering() -> None:
    """OutboxSchemaMissingError carries the generic is_transient marker.

    Asserted directly against the error type (no worker import needed here;
    tests/workers/test_outbox_worker.py already covers the worker's generic
    marker-based classification for StoreSchemaMissingError using the same
    protocol).
    """
    exc = OutboxSchemaMissingError("Missing table 'outbox' in the configured Postgres.")
    assert getattr(exc, "is_transient", None) is True
