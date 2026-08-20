"""PostgreSQL proof for generation-aware Heimdal raw liveness."""

from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_LIVENESS_HEAD = "f8a05a9b0001"
LIVENESS_HEAD = "c5d8a1e4f2b7"
_KEY = bytes(range(32))
_TABLES = (
    "heimdal_raw_liveness_generation",
    "heimdal_raw_deletion_tombstone",
    "heimdal_raw_response_lease",
    "heimdal_raw_retention_claim",
    "heimdal_raw_deletion_receipt",
)


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
def scratch_db_factory():
    admin_dsn = _admin_dsn()
    try:
        with psycopg.connect(admin_dsn, connect_timeout=2):
            pass
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")

    created: list[str] = []

    def create() -> str:
        name = f"scratch_raw_live_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{name}"')
        created.append(name)
        dsn = _scratch_dsn(admin_dsn, name)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        return dsn

    yield create

    for name in created:
        try:
            with psycopg.connect(admin_dsn, autocommit=True) as conn:
                conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        except Exception:
            pass


def _upgrade(dsn: str, monkeypatch: pytest.MonkeyPatch, revision: str) -> None:
    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    command.upgrade(config, revision)


def _insert_raw_sql(
    dsn: str, *, record_id: uuid.UUID, content_identity: str, ingested_at: datetime
) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO heimdal_raw_record (
                id, content_identity, capture_chain, sensor, consent,
                source_path, ingested_at, payload
            ) VALUES (%s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s::jsonb)
            """,
            (
                record_id,
                content_identity,
                json.dumps(["migration-test"]),
                json.dumps({"adapter": "migration-test"}),
                json.dumps({"grant_ref": "migration-test"}),
                "migration-test.raw",
                ingested_at,
                json.dumps({}),
            ),
        )
        conn.execute(
            """
            INSERT INTO heimdal_raw_representation (
                id, record_id, storage_kind, location_ref,
                ciphertext, nonce, key_ref, active, registered_at
            ) VALUES (%s, %s, 'postgres_hot', %s, %s, %s, %s, true, %s)
            """,
            (
                record_id,
                record_id,
                f"heimloc:{record_id}",
                b"ciphertext",
                b"012345678901",
                "migration-test-key",
                ingested_at,
            ),
        )


def _schema_snapshot(dsn: str) -> dict[str, list[tuple[object, ...]]]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name, column_name, data_type, is_nullable,
                   regexp_replace(coalesce(column_default, ''),
                                  '::regclass', '::regclass', 'g')
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = ANY(%s)
            ORDER BY table_name, ordinal_position
            """,
            (list(_TABLES),),
        )
        columns = [tuple(row) for row in cur.fetchall()]
        cur.execute(
            """
            SELECT tablename, indexname,
                   regexp_replace(indexdef, 'public\\.', '', 'g')
            FROM pg_indexes
            WHERE schemaname = 'public' AND tablename = ANY(%s)
            ORDER BY tablename, indexname
            """,
            (list(_TABLES),),
        )
        indexes = [tuple(row) for row in cur.fetchall()]
        cur.execute(
            """
            SELECT conrelid::regclass::text, conname, contype,
                   pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = ANY(%s::regclass[])
            ORDER BY conrelid::regclass::text, conname
            """,
            (list(_TABLES),),
        )
        constraints = [tuple(row) for row in cur.fetchall()]
        cur.execute(
            """
            SELECT event_object_table, trigger_name, event_manipulation,
                   action_timing, action_statement
            FROM information_schema.triggers
            WHERE trigger_schema = 'public' AND event_object_table = ANY(%s)
            ORDER BY event_object_table, trigger_name, event_manipulation
            """,
            (list(_TABLES),),
        )
        triggers = [tuple(row) for row in cur.fetchall()]
    return {
        "columns": columns,
        "indexes": indexes,
        "constraints": constraints,
        "triggers": triggers,
    }


def _runtime(dsn: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)


def _insert_runtime_raw(content: bytes):
    from app.heimdal.raw_store import (
        compute_raw_content_identity,
        encrypt_raw_bytes,
        insert_raw_record,
    )

    ciphertext, nonce = encrypt_raw_bytes(content, key=_KEY)
    return insert_raw_record(
        content_identity=compute_raw_content_identity(content),
        capture_chain=["migration-test"],
        sensor={"adapter": "migration-test"},
        consent={"grant_ref": "migration-test"},
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="migration-test-key",
        key=_KEY,
        source_path="migration-test.raw",
    )[0]


def test_migration_backfills_terminal_and_active_generations(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, PRE_LIVENESS_HEAD)
    content_identity = "sha256:" + "a" * 64
    deleted_id = uuid.uuid4()
    active_id = uuid.uuid4()
    deleted_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
    _insert_raw_sql(
        dsn,
        record_id=active_id,
        content_identity=content_identity,
        ingested_at=deleted_at + timedelta(days=1),
    )
    receipt_id = uuid.uuid4()
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO heimdal_raw_deletion_receipt (
                id, record_id, content_identity, reason,
                retention_window_days, deleted_at, payload
            ) VALUES (%s, %s, %s, 'hard_retention_bound', 1, %s, '{}'::jsonb)
            """,
            (receipt_id, deleted_id, content_identity, deleted_at),
        )

    _upgrade(dsn, monkeypatch, LIVENESS_HEAD)
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT generation, record_id FROM heimdal_raw_liveness_generation
            WHERE content_identity = %s ORDER BY generation
            """,
            (content_identity,),
        )
        assert cur.fetchall() == [(1, deleted_id), (2, active_id)]
        cur.execute(
            """
            SELECT record_id, deletion_receipt_id
            FROM heimdal_raw_deletion_tombstone
            """
        )
        assert cur.fetchall() == [(deleted_id, receipt_id)]

        cur.execute("SELECT set_config('app.heimdal_retention_bypass', 'true', true)")
        with pytest.raises(psycopg.errors.RaiseException):
            cur.execute("DELETE FROM heimdal_raw_record WHERE id = %s", (active_id,))


def test_autocreate_and_migration_liveness_schemas_match(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrated = scratch_db_factory()
    bootstrapped = scratch_db_factory()
    _upgrade(migrated, monkeypatch, LIVENESS_HEAD)

    monkeypatch.setenv("DATABASE_URL", bootstrapped)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    from app.heimdal import raw_store

    raw_store._PgRawStore()  # noqa: SLF001
    assert _schema_snapshot(bootstrapped) == _schema_snapshot(migrated)


@pytest.mark.parametrize(
    "crash_stage", ["after_deletion_receipt", "after_tombstone", "after_raw_delete"]
)
def test_pg_governed_deletion_rolls_back_every_crash_stage(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
    crash_stage: str,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, LIVENESS_HEAD)
    _runtime(dsn, monkeypatch)
    from app.heimdal import raw_liveness
    from app.heimdal.raw_store import all_raw_records

    record = _insert_runtime_raw(f"pg-crash-{crash_stage}".encode())

    def crash(stage: str) -> None:
        if stage == crash_stage:
            raise RuntimeError(f"injected crash at {stage}")

    monkeypatch.setattr(raw_liveness, "_retention_stage_hook", crash)
    with pytest.raises(RuntimeError, match="injected crash"):
        raw_liveness.governed_delete_raw_record(
            record_id=record.id,
            reason="hard_retention_bound",
            retention_window_days=1,
            deleted_at=datetime.now(timezone.utc) + timedelta(days=2),
        )
    assert [item.id for item in all_raw_records()] == [record.id]
    assert raw_liveness.all_deletion_receipts() == []
    assert raw_liveness.all_deletion_tombstones() == []


def test_pg_response_lease_and_deletion_share_transaction_fence(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, LIVENESS_HEAD)
    _runtime(dsn, monkeypatch)
    from app.heimdal import raw_liveness
    from app.heimdal.raw_read_gate import raw_ref_for
    from app.heimdal.raw_store import all_raw_records

    record = _insert_runtime_raw(b"pg-response-fence")
    retention_time = datetime.now(timezone.utc) + timedelta(days=2)
    lease_appended = threading.Event()
    release_response = threading.Event()
    deletion_at_fence = threading.Event()

    def response_hook(stage: str) -> None:
        assert stage == "after_lease_append"
        lease_appended.set()
        assert release_response.wait(timeout=10)

    monkeypatch.setattr(raw_liveness, "_response_lease_stage_hook", response_hook)
    monkeypatch.setattr(
        raw_liveness,
        "_retention_fence_hook",
        lambda _record_id: deletion_at_fence.set(),
    )

    def issue_lease():
        return raw_liveness.issue_response_lease(
            raw_ref=raw_ref_for(record),
            content_identity=record.content_identity,
            now=retention_time,
        )

    def delete():
        return raw_liveness.governed_delete_raw_record(
            record_id=record.id,
            reason="hard_retention_bound",
            retention_window_days=1,
            deleted_at=retention_time,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        lease_future = executor.submit(issue_lease)
        assert lease_appended.wait(timeout=10)
        delete_future = executor.submit(delete)
        assert deletion_at_fence.wait(timeout=10)
        assert not delete_future.done()
        release_response.set()
        lease = lease_future.result(timeout=10)
        deletion = delete_future.result(timeout=10)

    assert deletion.outcome == "lease_valid"
    assert [item.id for item in all_raw_records()] == [record.id]
    assert raw_liveness.all_deletion_receipts() == []

    deleted = raw_liveness.governed_delete_raw_record(
        record_id=record.id,
        reason="hard_retention_bound",
        retention_window_days=1,
        deleted_at=lease.expires_at + timedelta(microseconds=1),
    )
    assert deleted.outcome == "deleted"
    assert all_raw_records() == []
    assert len(raw_liveness.all_deletion_receipts()) == 1
    assert len(raw_liveness.all_deletion_tombstones()) == 1


def test_pg_missing_raw_without_tombstone_is_unavailable(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, LIVENESS_HEAD)
    _runtime(dsn, monkeypatch)
    from app.heimdal import raw_liveness
    from app.heimdal.raw_read_gate import raw_ref_for

    record = _insert_runtime_raw(b"pg-untombstoned-absence")
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("ALTER TABLE heimdal_raw_representation DISABLE TRIGGER USER")
        conn.execute("ALTER TABLE heimdal_raw_record DISABLE TRIGGER USER")
        conn.execute(
            "DELETE FROM heimdal_raw_representation WHERE record_id = %s", (record.id,)
        )
        conn.execute("DELETE FROM heimdal_raw_record WHERE id = %s", (record.id,))
        conn.execute("ALTER TABLE heimdal_raw_record ENABLE TRIGGER USER")
        conn.execute("ALTER TABLE heimdal_raw_representation ENABLE TRIGGER USER")

    with pytest.raises(raw_liveness.RawLivenessUnavailableError):
        raw_liveness.issue_response_lease(
            raw_ref=raw_ref_for(record), content_identity=record.content_identity
        )
    assert raw_liveness.all_deletion_tombstones() == []
