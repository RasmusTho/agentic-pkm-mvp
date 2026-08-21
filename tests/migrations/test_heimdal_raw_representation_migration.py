"""Postgres proof for HAR-02's legacy raw-representation backfill (#3848)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_REPRESENTATION_HEAD = "d1e8a0c5f37b"
REPRESENTATION_HEAD = "e7b4c9d2a6f1"
LIVENESS_HEAD = "c5d8a1e4f2b7"
CURRENT_REPRESENTATION_HEAD = "e2f3a4b5c6d7"
_KEY = bytes(range(32))


def _content_identity(plaintext: bytes) -> str:
    return f"sha256:{hashlib.sha256(plaintext).hexdigest()}"


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

    def _create() -> str:
        name = f"scratch_har02_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{name}"')
        created.append(name)
        dsn = _scratch_dsn(admin_dsn, name)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        return dsn

    yield _create

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


def _insert_legacy_record(
    dsn: str,
    *,
    record_id: uuid.UUID,
    plaintext: bytes,
    content_identity: str | None = None,
) -> datetime:
    from app.heimdal.raw_store import encrypt_raw_bytes

    ciphertext, nonce = encrypt_raw_bytes(plaintext, key=_KEY)
    ingested_at = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO heimdal_raw_record (
                id, content_identity, capture_chain, sensor, consent,
                ciphertext, nonce, key_ref, source_path, ingested_at, payload
            ) VALUES (%s, %s, %s::jsonb, %s::jsonb, %s::jsonb,
                      %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                record_id,
                content_identity or _content_identity(plaintext),
                json.dumps(["registered-sensor", "heimdal"]),
                json.dumps({"sensor_id": "registered-sensor"}),
                json.dumps({"grant_ref": "standing-grant"}),
                ciphertext,
                nonce,
                "test-key-v1",
                "source-class-redacted",
                ingested_at,
                json.dumps({}),
            ),
        )
    return ingested_at


def _assert_legacy_shape_and_bytes(
    dsn: str,
    *,
    expected: dict[uuid.UUID, tuple[str, bytes]],
) -> None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'heimdal_raw_record'
            """
        )
        columns = {row[0] for row in cur.fetchall()}
        assert {"ciphertext", "nonce", "key_ref"}.issubset(columns)
        cur.execute("SELECT to_regclass('public.heimdal_raw_representation')")
        assert cur.fetchone() == (None,)
        cur.execute(
            """
            SELECT id, content_identity, ciphertext, nonce, key_ref
            FROM heimdal_raw_record ORDER BY id
            """
        )
        rows = cur.fetchall()
        assert len(rows) == len(expected)
        for record_id, content_identity, ciphertext, nonce, key_ref in rows:
            expected_identity, expected_plaintext = expected[record_id]
            assert content_identity == expected_identity
            assert bytes(ciphertext) and bytes(nonce) and key_ref == "test-key-v1"
            from app.heimdal.raw_store import decrypt_raw_bytes

            assert decrypt_raw_bytes(bytes(ciphertext), bytes(nonce), key=_KEY) == expected_plaintext


def _create_conflicting_partial_registry(
    dsn: str, *, record_id: uuid.UUID, active: bool
) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            """
            CREATE TABLE heimdal_raw_representation (
                id uuid PRIMARY KEY,
                record_id uuid NOT NULL REFERENCES heimdal_raw_record(id) ON DELETE RESTRICT,
                storage_kind text NOT NULL CHECK (storage_kind IN ('postgres_hot')),
                location_ref text NOT NULL UNIQUE CHECK (location_ref LIKE 'heimloc:%'),
                ciphertext bytea,
                nonce bytea,
                key_ref text,
                active boolean NOT NULL DEFAULT false,
                registered_at timestamptz NOT NULL DEFAULT now(),
                sequence bigserial NOT NULL
            )
            """
        )
        # Same deterministic id as the migration, but deliberately different
        # encrypted fields. The preflight must reject both an inactive row and
        # an active-but-complete row rather than silently substituting bytes.
        conn.execute(
            """
            INSERT INTO heimdal_raw_representation (
                id, record_id, storage_kind, location_ref,
                ciphertext, nonce, key_ref, active
            ) VALUES (%s, %s, 'postgres_hot', %s, %s, %s, %s, %s)
            """,
            (
                record_id,
                record_id,
                f"heimloc:{record_id}",
                b"conflict",
                b"conflict",
                "conflict-key",
                active,
            ),
        )


def _raw_schema_snapshot(dsn: str) -> dict[str, object]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name, column_name, data_type, is_nullable, COALESCE(column_default, '')
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name IN ('heimdal_raw_record', 'heimdal_raw_representation')
            ORDER BY table_name, ordinal_position
            """
        )
        columns = [tuple(row) for row in cur.fetchall()]
        cur.execute(
            """
            SELECT tablename, indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename IN ('heimdal_raw_record', 'heimdal_raw_representation')
            ORDER BY tablename, indexname
            """
        )
        indexes = [tuple(row) for row in cur.fetchall()]
        cur.execute(
            """
            SELECT conrelid::regclass::text, conname, contype, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid IN (
                'heimdal_raw_record'::regclass,
                'heimdal_raw_representation'::regclass
            )
            ORDER BY conrelid::regclass::text, conname
            """
        )
        constraints = [tuple(row) for row in cur.fetchall()]
        cur.execute(
            """
            SELECT event_object_table, trigger_name, event_manipulation,
                   action_timing, action_statement
            FROM information_schema.triggers
            WHERE trigger_schema = 'public'
              AND event_object_table IN (
                  'heimdal_raw_record', 'heimdal_raw_representation'
              )
            ORDER BY event_object_table, trigger_name, event_manipulation
            """
        )
        triggers = [tuple(row) for row in cur.fetchall()]
        cur.execute(
            """
            SELECT pg_get_functiondef(oid)
            FROM pg_proc
            WHERE proname = 'heimdal_raw_deletion_receipt_reject_mutation'
            ORDER BY oid
            """
        )
        receipt_functions = [tuple(row) for row in cur.fetchall()]
        return {
            "columns": columns,
            "indexes": indexes,
            "constraints": constraints,
            "triggers": triggers,
            "receipt_functions": receipt_functions,
        }


@pytest.mark.parametrize("conflict_active", [False, True], ids=["inactive", "active-mismatch"])
def test_failed_legacy_backfill_is_loud_resumable_and_readable(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch, conflict_active: bool
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, PRE_REPRESENTATION_HEAD)
    record_id = uuid.uuid4()
    ingested_at = _insert_legacy_record(dsn, record_id=record_id, plaintext=b"legacy-hot")

    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
    from app.heimdal.raw_store import RawStoreSchemaMissingError, all_raw_records

    with pytest.raises(RawStoreSchemaMissingError, match="alembic upgrade head"):
        all_raw_records()

    _create_conflicting_partial_registry(
        dsn, record_id=record_id, active=conflict_active
    )
    with pytest.raises(Exception, match="backfill is incomplete"):
        _upgrade(dsn, monkeypatch, REPRESENTATION_HEAD)

    # PostgreSQL rolled back the revision. The legacy encrypted bytes and
    # identity/provenance remain intact and the partial conflict is unchanged.
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT ciphertext, nonce, key_ref, content_identity, consent, ingested_at
            FROM heimdal_raw_record WHERE id = %s
            """,
            (record_id,),
        )
        legacy = cur.fetchone()
        assert legacy is not None
        assert bytes(legacy[0]) and bytes(legacy[1]) and legacy[2] == "test-key-v1"
        assert legacy[3] == _content_identity(b"legacy-hot")
        assert legacy[4]["grant_ref"] == "standing-grant"
        assert legacy[5] == ingested_at
        cur.execute(
            "SELECT ciphertext, nonce, key_ref, active "
            "FROM heimdal_raw_representation WHERE id = %s",
            (record_id,),
        )
        conflict = cur.fetchone()
        assert conflict is not None
        assert bytes(conflict[0]) == b"conflict"
        assert bytes(conflict[1]) == b"conflict"
        assert conflict[2] == "conflict-key"
        assert conflict[3] is conflict_active
        cur.execute(
            "DELETE FROM heimdal_raw_representation WHERE id = %s",
            (record_id,),
        )
        conn.commit()

    _upgrade(dsn, monkeypatch, REPRESENTATION_HEAD)
    _upgrade(dsn, monkeypatch, LIVENESS_HEAD)

    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "authorized-reader")
    from app.heimdal.raw_read_gate import read_raw_record

    result = read_raw_record(
        f"heimraw:{record_id}",
        reader="authorized-reader",
        purpose="legacy migration continuity",
        key=_KEY,
    )
    assert result.plaintext == b"legacy-hot"

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.content_identity, r.consent, r.ingested_at,
                   p.id, p.storage_kind, p.location_ref, p.active
            FROM heimdal_raw_record AS r
            JOIN heimdal_raw_representation AS p ON p.record_id = r.id
            WHERE r.id = %s
            """,
            (record_id,),
        )
        migrated = cur.fetchone()
        assert migrated is not None
        assert migrated[0] == _content_identity(b"legacy-hot")
        assert migrated[1]["grant_ref"] == "standing-grant"
        assert migrated[2] == ingested_at
        assert migrated[3] == record_id
        assert migrated[4] == "postgres_hot"
        assert migrated[5] == f"heimloc:{record_id}"
        assert migrated[6] is True
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'heimdal_raw_record'
            """
        )
        identity_columns = {row[0] for row in cur.fetchall()}
        assert {"ciphertext", "nonce", "key_ref"}.isdisjoint(identity_columns)


def test_legacy_content_identity_mismatch_rolls_back_and_corrected_replay_succeeds(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, PRE_REPRESENTATION_HEAD)
    valid_id = uuid.uuid4()
    mismatched_id = uuid.uuid4()
    valid_plaintext = b"valid-legacy-hot"
    mismatched_plaintext = b"mismatched-legacy-hot"
    _insert_legacy_record(dsn, record_id=valid_id, plaintext=valid_plaintext)
    _insert_legacy_record(
        dsn,
        record_id=mismatched_id,
        plaintext=mismatched_plaintext,
        content_identity=_content_identity(b"different-evidence"),
    )
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", bytes(reversed(_KEY)).hex())

    with pytest.raises(Exception, match="identity verification failed"):
        _upgrade(dsn, monkeypatch, REPRESENTATION_HEAD)

    _assert_legacy_shape_and_bytes(
        dsn,
        expected={
            valid_id: (_content_identity(valid_plaintext), valid_plaintext),
            mismatched_id: (_content_identity(b"different-evidence"), mismatched_plaintext),
        },
    )

    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())

    with pytest.raises(Exception, match="identity verification failed"):
        _upgrade(dsn, monkeypatch, REPRESENTATION_HEAD)

    # The preflight runs before any registry DDL or byte move. One invalid row
    # rolls the whole revision back, preserving every legacy row for repair.
    _assert_legacy_shape_and_bytes(
        dsn,
        expected={
            valid_id: (_content_identity(valid_plaintext), valid_plaintext),
            mismatched_id: (_content_identity(b"different-evidence"), mismatched_plaintext),
        },
    )

    with psycopg.connect(dsn) as conn:
        conn.execute(
            "SELECT set_config('app.heimdal_retention_bypass', 'true', true)"
        )
        conn.execute(
            "DELETE FROM heimdal_raw_record WHERE id = %s",
            (mismatched_id,),
        )
    _insert_legacy_record(
        dsn,
        record_id=mismatched_id,
        plaintext=mismatched_plaintext,
    )

    _upgrade(dsn, monkeypatch, REPRESENTATION_HEAD)
    _upgrade(dsn, monkeypatch, LIVENESS_HEAD)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "authorized-reader")
    from app.heimdal.raw_read_gate import read_raw_record

    assert read_raw_record(
        f"heimraw:{valid_id}",
        reader="authorized-reader",
        purpose="valid legacy replay",
        key=_KEY,
    ).plaintext == valid_plaintext
    assert read_raw_record(
        f"heimraw:{mismatched_id}",
        reader="authorized-reader",
        purpose="corrected legacy replay",
        key=_KEY,
    ).plaintext == mismatched_plaintext


def test_test_bootstrap_refuses_legacy_shape_until_alembic_migrates_it(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, PRE_REPRESENTATION_HEAD)
    record_id = uuid.uuid4()
    _insert_legacy_record(dsn, record_id=record_id, plaintext=b"legacy-bootstrap")

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    from app.heimdal import raw_store

    with pytest.raises(raw_store.RawStoreSchemaMissingError, match="alembic upgrade head"):
        raw_store._PgRawStore()

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT ciphertext, nonce, key_ref FROM heimdal_raw_record WHERE id = %s",
            (record_id,),
        )
        legacy = cur.fetchone()
        assert legacy is not None and bytes(legacy[0]) and bytes(legacy[1])
        assert legacy[2] == "test-key-v1"

    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())
    _upgrade(dsn, monkeypatch, REPRESENTATION_HEAD)
    _upgrade(dsn, monkeypatch, LIVENESS_HEAD)
    raw_store._PgRawStore()
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "authorized-reader")
    from app.heimdal.raw_read_gate import read_raw_record

    assert read_raw_record(
        f"heimraw:{record_id}",
        reader="authorized-reader",
        purpose="bootstrap recovery",
        key=_KEY,
    ).plaintext == b"legacy-bootstrap"


@pytest.mark.parametrize(
    ("drop_statement", "missing_object"),
    [
        (
            "DROP INDEX heimdal_raw_representation_one_active_uq",
            "heimdal_raw_representation_one_active_uq",
        ),
        (
            "DROP TRIGGER heimdal_raw_record_no_update ON heimdal_raw_record",
            "heimdal_raw_record_no_update",
        ),
        (
            "DROP TRIGGER heimdal_raw_representation_no_mutation "
            "ON heimdal_raw_representation",
            "heimdal_raw_representation_no_mutation",
        ),
    ],
    ids=["one-active-index", "identity-trigger", "representation-trigger"],
)
def test_test_bootstrap_refuses_malformed_final_schema_without_self_repair(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
    drop_statement: str,
    missing_object: str,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, LIVENESS_HEAD)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(drop_statement)

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    from app.heimdal import raw_store

    with pytest.raises(raw_store.RawStoreSchemaMissingError, match="alembic upgrade head"):
        raw_store._PgRawStore()

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = current_schema() AND indexname = %s
            ) OR EXISTS (
                SELECT 1 FROM information_schema.triggers
                WHERE trigger_schema = current_schema() AND trigger_name = %s
            )
            """,
            (missing_object, missing_object),
        )
        row = cur.fetchone()
        assert row is not None and row[0] is False


def test_pg_representation_activation_and_all_copy_erasure_are_transactional(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, LIVENESS_HEAD)
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "authorized-reader")

    from app.heimdal.raw_read_gate import (
        all_raw_read_receipts,
        raw_ref_for,
        read_raw_record,
    )
    from app.heimdal.raw_store import (
        RawRepresentationDeletionError,
        RawRepresentationIdentityMismatchError,
        activate_raw_representation,
        all_raw_records,
        all_raw_representations,
        compute_raw_content_identity,
        encrypt_raw_bytes,
        insert_raw_record,
        register_raw_representation,
    )
    from app.heimdal.retention import all_deletion_receipts, enforce_hard_retention_bound
    from app.heimdal.settings_notes import (
        DEFAULT_SETTINGS_DIR,
        SETTINGS,
        SettingsNote,
        write_settings_note,
    )
    from app.write_guard import WriteGuard

    plaintext = b"pg-active-copy"
    original_ciphertext, original_nonce = encrypt_raw_bytes(plaintext, key=_KEY)
    record, created = insert_raw_record(
        content_identity=compute_raw_content_identity(plaintext),
        capture_chain=["registered-sensor", "heimdal"],
        sensor={"sensor_id": "registered-sensor"},
        consent={"grant_ref": "standing-grant"},
        ciphertext=original_ciphertext,
        nonce=original_nonce,
        key_ref="test-key-v1",
        key=_KEY,
        source_path="source-class-redacted",
    )
    assert created
    raw_ref = raw_ref_for(record)

    bad_ciphertext, bad_nonce = encrypt_raw_bytes(b"different-plaintext", key=_KEY)
    representation_id = str(uuid.uuid4())
    with pytest.raises(RawRepresentationIdentityMismatchError):
        register_raw_representation(
            record_id=record.id,
            ciphertext=bad_ciphertext,
            nonce=bad_nonce,
            key_ref="test-key-v1",
            key=_KEY,
            representation_id=representation_id,
            activate=True,
        )
    assert len(all_raw_representations(record.id)) == 1
    assert all_raw_representations(record.id)[0].active is True
    assert all_raw_read_receipts() == []

    replacement_ciphertext, replacement_nonce = encrypt_raw_bytes(plaintext, key=_KEY)
    replacement, replacement_created = register_raw_representation(
        record_id=record.id,
        ciphertext=replacement_ciphertext,
        nonce=replacement_nonce,
        key_ref="test-key-v1",
        key=_KEY,
        representation_id=representation_id,
        activate=True,
    )
    assert replacement_created and replacement.active
    replay, replay_created = register_raw_representation(
        record_id=record.id,
        ciphertext=replacement_ciphertext,
        nonce=replacement_nonce,
        key_ref="test-key-v1",
        key=_KEY,
        representation_id=representation_id,
        activate=True,
    )
    assert replay_created is False and replay.active

    corrupt_id = str(uuid.uuid4())
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO heimdal_raw_representation (
                id, record_id, storage_kind, location_ref,
                ciphertext, nonce, key_ref, active
            ) VALUES (%s, %s, 'postgres_hot', %s, %s, %s, %s, false)
            """,
            (
                corrupt_id,
                record.id,
                f"heimloc:{corrupt_id}",
                bad_ciphertext,
                bad_nonce,
                "test-key-v1",
            ),
        )
    with pytest.raises(RawRepresentationIdentityMismatchError):
        activate_raw_representation(record.id, corrupt_id, key=_KEY)
    representations = all_raw_representations(record.id)
    assert next(item for item in representations if item.id == representation_id).active is True
    assert next(item for item in representations if item.id == corrupt_id).active is False
    assert all_raw_read_receipts() == []

    assert read_raw_record(
        raw_ref,
        reader="authorized-reader",
        purpose="Postgres active representation",
        key=_KEY,
    ).plaintext == b"pg-active-copy"
    assert len(all_raw_read_receipts()) == 1
    assert sum(item.active for item in all_raw_representations(record.id)) == 1

    root = tmp_path / "vault"
    root.mkdir()
    write_settings_note(
        root,
        SettingsNote(spec=SETTINGS, values={"retention_window_days": 1}),
        settings_dir=DEFAULT_SETTINGS_DIR,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            """
            CREATE OR REPLACE FUNCTION har02_test_reject_representation_delete()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'injected HAR-02 representation deletion failure';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        conn.execute(
            """
            CREATE TRIGGER aa_har02_test_reject_representation_delete
            BEFORE DELETE ON heimdal_raw_representation
            FOR EACH ROW EXECUTE FUNCTION har02_test_reject_representation_delete()
            """
        )

    enforcement_time = datetime.now(timezone.utc) + timedelta(days=2)
    with pytest.raises(RawRepresentationDeletionError):
        enforce_hard_retention_bound(
            vault_root=root,
            now=enforcement_time,
            record_last_enforced=False,
        )
    assert len(all_raw_representations(record.id)) == 3
    assert [item.id for item in all_raw_records()] == [record.id]
    assert all_deletion_receipts() == []

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            "DROP TRIGGER aa_har02_test_reject_representation_delete "
            "ON heimdal_raw_representation"
        )
        conn.execute("DROP FUNCTION har02_test_reject_representation_delete()")

    result = enforce_hard_retention_bound(
        vault_root=root,
        now=enforcement_time,
        record_last_enforced=False,
    )
    assert result.deleted_count == 1
    assert all_raw_representations(record.id) == []
    assert all_raw_records() == []
    assert [receipt.record_id for receipt in all_deletion_receipts()] == [record.id]


def test_test_bootstrap_and_migration_shapes_converge(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrated = scratch_db_factory()
    bootstrapped = scratch_db_factory()
    _upgrade(migrated, monkeypatch, PRE_REPRESENTATION_HEAD)
    _insert_legacy_record(migrated, record_id=uuid.uuid4(), plaintext=b"shape-proof")
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())
    _upgrade(migrated, monkeypatch, CURRENT_REPRESENTATION_HEAD)

    monkeypatch.setenv("DATABASE_URL", bootstrapped)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    from app.heimdal import raw_store

    raw_store._PgRawStore()
    assert _raw_schema_snapshot(bootstrapped) == _raw_schema_snapshot(migrated)
