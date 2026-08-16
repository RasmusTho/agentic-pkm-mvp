from __future__ import annotations

import uuid

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from app.instance.binding_ids import (
    COMPATIBILITY_BINDING_ID,
    OUTBOX_QUARANTINE_BINDING_ID,
)

pytestmark = pytest.mark.pg

PRE_OUTBOX_BINDING_HEAD = "f5a05a5b0001"
OUTBOX_BINDING_HEAD = "f6a05a7b0001"


def _upgrade(dsn: str, monkeypatch: pytest.MonkeyPatch, revision: str) -> None:
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("DB_DSN", dsn)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", dsn)
    command.upgrade(config, revision)


@pytest.fixture
def scratch_db(monkeypatch: pytest.MonkeyPatch):
    from app.db.dsn import resolve_dsn

    admin_dsn = resolve_dsn()
    name = f"scratch_mvr05a7_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = admin_dsn.rpartition("/")
    dsn = f"{base}/{name}"
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    try:
        yield dsn
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_legacy_rows_keep_their_keys_and_classify_or_quarantine(
    scratch_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _upgrade(scratch_db, monkeypatch, PRE_OUTBOX_BINDING_HEAD)
    pending_id = uuid.uuid4()
    delivered_id = uuid.uuid4()
    with psycopg.connect(scratch_db) as conn:
        conn.execute(
            "INSERT INTO outbox (id, topic, payload) VALUES (%s, 'pending', '{}'::jsonb)",
            (pending_id,),
        )
        conn.execute(
            "INSERT INTO outbox (id, topic, payload, delivered_at) "
            "VALUES (%s, 'delivered', '{}'::jsonb, now())",
            (delivered_id,),
        )

    _upgrade(scratch_db, monkeypatch, OUTBOX_BINDING_HEAD)

    with psycopg.connect(scratch_db) as conn:
        rows = conn.execute(
            "SELECT id, legacy_key, vault_binding_id, delivered_at IS NOT NULL "
            "FROM outbox ORDER BY topic"
        ).fetchall()
    assert rows == [
        (delivered_id, delivered_id, COMPATIBILITY_BINDING_ID, True),
        (pending_id, pending_id, COMPATIBILITY_BINDING_ID, False),
    ]
    assert OUTBOX_QUARANTINE_BINDING_ID != COMPATIBILITY_BINDING_ID


def test_partially_upgraded_unprovable_row_is_quarantined(
    scratch_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _upgrade(scratch_db, monkeypatch, PRE_OUTBOX_BINDING_HEAD)
    scoped_id = uuid.uuid4()
    legacy_id = uuid.uuid4()
    with psycopg.connect(scratch_db) as conn:
        conn.execute("ALTER TABLE outbox ADD COLUMN legacy_key uuid")
        conn.execute("ALTER TABLE outbox ADD COLUMN vault_binding_id text")
        conn.execute(
            "INSERT INTO outbox (id, legacy_key, topic, payload) "
            "VALUES (%s, %s, 'partial', '{}'::jsonb)",
            (scoped_id, legacy_id),
        )

    _upgrade(scratch_db, monkeypatch, OUTBOX_BINDING_HEAD)

    with psycopg.connect(scratch_db) as conn:
        row = conn.execute(
            "SELECT id, legacy_key, vault_binding_id FROM outbox WHERE id = %s", (scoped_id,)
        ).fetchone()
    assert row == (scoped_id, legacy_id, OUTBOX_QUARANTINE_BINDING_ID)
