"""Real-Postgres proof for Heimdal migration-owned trigger seams (#4598)."""

from __future__ import annotations

import os
import secrets
import uuid
from pathlib import Path
from typing import Iterator

import pytest

from app.heimdal import (
    consent_ledger,
    media_receipts,
    observation_log,
    raw_liveness,
    raw_read_gate,
    raw_store,
)

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[2]
SEAMS = (
    consent_ledger,
    media_receipts,
    observation_log,
    raw_read_gate,
    raw_liveness,
    raw_store,
)
TABLE_KEYS = {
    "heimdal_consent_grant": "id",
    "heimdal_media_receipt": "receipt_id",
    "heimdal_observation_log": "id",
    "heimdal_raw_read_receipt": "id",
    "heimdal_raw_deletion_receipt": "id",
    "heimdal_raw_record": "id",
}


def _configured_admin_dsn() -> str:
    from app.db.dsn import resolve_dsn

    dsn = resolve_dsn()
    if dsn:
        return dsn
    message = (
        "real-PG trigger-ownership proof unavailable: configure an explicit "
        "non-production DATABASE_URL/DB_DSN"
    )
    if os.getenv("REQUIRE_REAL_PG_TRIGGER_PROOF") == "1":
        pytest.fail(message)
    pytest.skip(message)


@pytest.fixture
def migrated_scratch_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, str]]:
    psycopg = pytest.importorskip("psycopg")
    from alembic import command
    from alembic.config import Config

    admin_dsn = _configured_admin_dsn()
    database_name = f"scratch_trigger_owner_{secrets.token_hex(6)}"
    role_name = f"trigger_reader_{secrets.token_hex(6)}"
    base, separator, _database = admin_dsn.rpartition("/")
    if not separator:
        pytest.fail("real-PG proof requires a database-qualified non-production DSN")
    scratch_dsn = f"{base}/{database_name}"
    try:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{database_name}"')
            conn.execute(f'CREATE ROLE "{role_name}" NOLOGIN')
        monkeypatch.setenv("DATABASE_URL", scratch_dsn)
        monkeypatch.delenv("DB_DSN", raising=False)
        config = Config(str(REPO_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
        command.upgrade(config, "head")
        with psycopg.connect(scratch_dsn, autocommit=True) as conn:
            conn.execute(f'GRANT USAGE ON SCHEMA public TO "{role_name}"')
            conn.execute(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{role_name}"'
            )
            conn.execute(
                f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role_name}"'
            )
            conn.execute(f'GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO "{role_name}"')
        yield scratch_dsn, role_name
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
            conn.execute(f'DROP ROLE IF EXISTS "{role_name}"')


def _catalog_snapshot(conn: object) -> list[tuple[object, ...]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.relname, t.tgname, t.oid, p.proname, p.oid, t.tgtype,
               t.tgenabled, t.tgattr::text, t.tgqual, p.prosrc
        FROM pg_trigger AS t
        JOIN pg_class AS c ON c.oid = t.tgrelid
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        JOIN pg_proc AS p ON p.oid = t.tgfoid
        WHERE n.nspname = 'public'
          AND c.relname = ANY(%s)
          AND NOT t.tgisinternal
        ORDER BY c.relname, t.tgname
        """,
        (list(TABLE_KEYS),),
    )
    return list(cur.fetchall())


def _insert_enforcement_rows(conn: object) -> dict[str, object]:
    values: dict[str, object] = {}
    cur = conn.cursor()
    cur.execute("SELECT id FROM heimdal_consent_grant ORDER BY sequence LIMIT 1")
    values["heimdal_consent_grant"] = cur.fetchone()[0]

    values["heimdal_media_receipt"] = f"receipt-{uuid.uuid4()}"
    cur.execute(
        """INSERT INTO heimdal_media_receipt
           (receipt_id, capture_id, content_sha256, raw_ref, kind, lane)
           VALUES (%s, %s, %s, %s, 'audio', 'test')""",
        (values["heimdal_media_receipt"], str(uuid.uuid4()), "a" * 64, "raw:test"),
    )
    for table in ("heimdal_observation_log", "heimdal_raw_read_receipt"):
        values[table] = uuid.uuid4()
    cur.execute(
        "INSERT INTO heimdal_observation_log (id, topic, payload) VALUES (%s, 'test', '{}'::jsonb)",
        (values["heimdal_observation_log"],),
    )
    cur.execute(
        """INSERT INTO heimdal_raw_read_receipt
           (id, raw_ref, content_identity, reader, purpose, payload)
           VALUES (%s, 'raw:test', %s, 'test', 'proof', '{}'::jsonb)""",
        (values["heimdal_raw_read_receipt"], "b" * 64),
    )
    values["heimdal_raw_record"] = uuid.uuid4()
    cur.execute(
        """INSERT INTO heimdal_raw_record
           (id, content_identity, capture_chain, sensor, consent, source_path, payload)
           VALUES (%s, %s, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '/proof', '{}'::jsonb)""",
        (values["heimdal_raw_record"], "c" * 64),
    )
    values["heimdal_raw_deletion_receipt"] = uuid.uuid4()
    cur.execute(
        """INSERT INTO heimdal_raw_deletion_receipt
           (id, record_id, content_identity, reason, retention_window_days, payload)
           VALUES (%s, %s, %s, 'proof', 1, '{}'::jsonb)""",
        (values["heimdal_raw_deletion_receipt"], uuid.uuid4(), "d" * 64),
    )
    return values


def test_real_pg_seams_issue_zero_ddl_and_append_only_has_no_window(
    migrated_scratch_db: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restricted production seams stay read-only and live triggers reject mutations."""

    psycopg = pytest.importorskip("psycopg")
    scratch_dsn, role_name = migrated_scratch_db
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    with psycopg.connect(scratch_dsn, autocommit=True) as admin:
        before = _catalog_snapshot(admin)
        with psycopg.connect(scratch_dsn, autocommit=True) as runtime:
            runtime.execute(f'SET ROLE "{role_name}"')
            for seam in SEAMS:
                seam._bootstrap_pg(runtime)
        after = _catalog_snapshot(admin)
        assert after == before

        rows = _insert_enforcement_rows(admin)
        with psycopg.connect(scratch_dsn, autocommit=True) as runtime:
            runtime.execute(f'SET ROLE "{role_name}"')
            for table, key_column in TABLE_KEYS.items():
                with pytest.raises(Exception, match="append-only"):
                    runtime.execute(
                        f"UPDATE {table} SET {key_column} = {key_column} WHERE {key_column} = %s",
                        (rows[table],),
                    )
                with pytest.raises(Exception, match="append-only"):
                    runtime.execute(
                        f"DELETE FROM {table} WHERE {key_column} = %s",
                        (rows[table],),
                    )


def test_real_pg_catalog_drift_fails_closed_without_runtime_repair(
    migrated_scratch_db: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disabled migration trigger is detected and remains disabled."""

    psycopg = pytest.importorskip("psycopg")
    scratch_dsn, role_name = migrated_scratch_db
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    with psycopg.connect(scratch_dsn, autocommit=True) as admin:
        admin.execute(
            "ALTER TABLE heimdal_observation_log DISABLE TRIGGER heimdal_observation_log_no_update"
        )
        with psycopg.connect(scratch_dsn, autocommit=True) as runtime:
            runtime.execute(f'SET ROLE "{role_name}"')
            with pytest.raises(
                observation_log.ObservationLogSchemaMissingError,
                match="Alembic-owned definition",
            ):
                observation_log._bootstrap_pg(runtime)
        row = admin.execute(
            """SELECT tgenabled FROM pg_trigger
               WHERE tgrelid = 'heimdal_observation_log'::regclass
                 AND tgname = 'heimdal_observation_log_no_update'"""
        ).fetchone()
        assert row == ("D",)
