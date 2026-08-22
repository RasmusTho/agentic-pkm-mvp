"""Postgres proof for HAR-02's legacy raw-representation backfill (#3848)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_REPRESENTATION_HEAD = "d1e8a0c5f37b"
REPRESENTATION_HEAD = "e7b4c9d2a6f1"
COLD_REPRESENTATION_HEAD = "d1a4b7c9e2f0"
CURRENT_REPRESENTATION_HEAD = "a9d7c5e3b1f0"
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


def _insert_runtime_raw(
    plaintext: bytes,
    *,
    grant_ref: str,
    modality: str | None = None,
):
    from app.heimdal import raw_store

    ciphertext, nonce = raw_store.encrypt_raw_bytes(plaintext, key=_KEY)
    record, created = raw_store.insert_raw_record(
        content_identity=raw_store.compute_raw_content_identity(plaintext),
        capture_chain=["migration-test"],
        sensor={"adapter": "migration-test"},
        consent={"grant_ref": grant_ref},
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="migration-test-key",
        key=_KEY,
        source_path="source-class-redacted",
        payload={"modality": modality} if modality is not None else None,
    )
    assert created
    return record


def _archive_runtime_raw(record, *, archive_root: Path, now: datetime):
    from app.heimdal import local_archive, raw_store
    from app.ops.heimdal_cold_volume import (
        _ARCHIVE_VOLUME_READY_ISSUER,
        _issue_archive_volume_ready,
    )

    archive_ref = "pg-har05-archive"
    proof = _issue_archive_volume_ready(
        archive_ref,
        archive_root,
        _issuer=_ARCHIVE_VOLUME_READY_ISSUER,
    )
    result = local_archive.relocate_raw_record(
        replace(record, ingested_at=now - timedelta(days=8)),
        archive_root=archive_root,
        archive_ref=archive_ref,
        now=now,
        retention_window_days=30,
        key=_KEY,
        volume_ready=lambda: proof,
    )
    active = result.active_representation
    object_path = archive_root / "representations" / f"{active.id}.bin"
    manifest_path = archive_root / "manifests" / f"{active.id}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_owner = {
        "location_ref": active.location_ref,
        "archive_token": raw_store._archive_binding_token(archive_ref),  # noqa: SLF001
        "archive_generation": proof.archive_generation,
        "raw_generation": active.raw_generation,
        "representation_id": active.id,
    }
    assert manifest.get("ownership_state") == "verified"
    assert {key: manifest.get(key) for key in expected_owner} == expected_owner
    assert result.receipt.location_ref == active.location_ref
    assert result.receipt.archive_token == expected_owner["archive_token"]
    assert result.receipt.archive_generation == proof.archive_generation
    assert result.receipt.raw_generation == active.raw_generation
    assert (
        raw_store._cold_object_path(  # noqa: SLF001
            active.location_ref,
            expected_archive_token=active.archive_token,
            expected_archive_generation=active.archive_generation,
            expected_raw_generation=active.raw_generation,
            expected_representation_id=active.id,
        )
        == object_path
    )
    return result


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

            assert (
                decrypt_raw_bytes(bytes(ciphertext), bytes(nonce), key=_KEY) == expected_plaintext
            )


def _create_conflicting_partial_registry(dsn: str, *, record_id: uuid.UUID, active: bool) -> None:
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
              AND table_name IN (
                  'heimdal_raw_record',
                  'heimdal_raw_representation',
                  'heimdal_raw_consent_association'
              )
            ORDER BY table_name, ordinal_position
            """
        )
        columns = [tuple(row) for row in cur.fetchall()]
        cur.execute(
            """
            SELECT tablename, indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename IN (
                  'heimdal_raw_record',
                  'heimdal_raw_representation',
                  'heimdal_raw_consent_association'
              )
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
                'heimdal_raw_representation'::regclass,
                'heimdal_raw_consent_association'::regclass,
                'heimdal_raw_liveness_generation'::regclass
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
                  'heimdal_raw_record',
                  'heimdal_raw_representation',
                  'heimdal_raw_consent_association'
              )
            ORDER BY event_object_table, trigger_name, event_manipulation
            """
        )
        triggers = [tuple(row) for row in cur.fetchall()]
        cur.execute(
            """
            SELECT pg_get_functiondef(t.tgfoid), pg_get_triggerdef(t.oid)
            FROM pg_trigger AS t
            JOIN pg_class AS c ON c.oid = t.tgrelid
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = current_schema()
              AND c.relname = 'heimdal_raw_deletion_receipt'
              AND t.tgname = 'heimdal_raw_deletion_receipt_no_update'
              AND NOT t.tgisinternal
            """
        )
        receipt_functions = [tuple(row) for row in cur.fetchall()]
        cur.execute(
            """
            SELECT pg_get_functiondef(p.oid), pg_get_function_arguments(p.oid),
                   p.provolatile, p.proisstrict
            FROM pg_proc AS p
            JOIN pg_namespace AS n ON n.oid = p.pronamespace
            WHERE n.nspname = 'public'
              AND p.proname = 'heimdal_raw_cleanup_queue_is_subsequence'
              AND p.proargtypes = ARRAY['jsonb'::regtype, 'jsonb'::regtype]::oidvector
            """
        )
        cleanup_queue_helpers = [tuple(row) for row in cur.fetchall()]
        cur.execute(
            """
            SELECT pg_get_functiondef(p.oid)
            FROM pg_proc AS p
            JOIN pg_namespace AS n ON n.oid = p.pronamespace
            WHERE n.nspname = 'public'
              AND p.proname = 'heimdal_raw_representation_reject_mutation'
            """
        )
        representation_functions = [
            " ".join(str(row[0]).split()) for row in cur.fetchall()
        ]
        return {
            "columns": columns,
            "indexes": indexes,
            "constraints": constraints,
            "triggers": triggers,
            "receipt_functions": receipt_functions,
            "cleanup_queue_helpers": cleanup_queue_helpers,
            "representation_functions": representation_functions,
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

    _create_conflicting_partial_registry(dsn, record_id=record_id, active=conflict_active)
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
    _upgrade(dsn, monkeypatch, CURRENT_REPRESENTATION_HEAD)

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
        cur.execute(
            """
            SELECT generation, grant_ref
            FROM heimdal_raw_consent_association
            WHERE record_id = %s
            """,
            (record_id,),
        )
        association = cur.fetchone()
        assert association is not None
        assert association[0] == 1
        assert association[1] == "standing-grant"


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
        conn.execute("SELECT set_config('app.heimdal_retention_bypass', 'true', true)")
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
    _upgrade(dsn, monkeypatch, CURRENT_REPRESENTATION_HEAD)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "authorized-reader")
    from app.heimdal.raw_read_gate import read_raw_record

    assert (
        read_raw_record(
            f"heimraw:{valid_id}",
            reader="authorized-reader",
            purpose="valid legacy replay",
            key=_KEY,
        ).plaintext
        == valid_plaintext
    )
    assert (
        read_raw_record(
            f"heimraw:{mismatched_id}",
            reader="authorized-reader",
            purpose="corrected legacy replay",
            key=_KEY,
        ).plaintext
        == mismatched_plaintext
    )


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
    _upgrade(dsn, monkeypatch, CURRENT_REPRESENTATION_HEAD)
    raw_store._PgRawStore()
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "authorized-reader")
    from app.heimdal.raw_read_gate import read_raw_record

    assert (
        read_raw_record(
            f"heimraw:{record_id}",
            reader="authorized-reader",
            purpose="bootstrap recovery",
            key=_KEY,
        ).plaintext
        == b"legacy-bootstrap"
    )


def test_current_upgrade_refuses_unbound_cold_locations_without_rewriting_them(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, "e2f3a4b5c6d7")
    record_id = uuid.uuid4()
    representation_id = uuid.uuid4()
    old_location_ref = f"heimloc:cold:{representation_id}"

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
                _content_identity(b"unbound-cold-location"),
                json.dumps(["migration-test"]),
                json.dumps({"adapter": "migration-test"}),
                json.dumps({"grant_ref": "migration-test"}),
                "migration-test.raw",
                datetime.now(timezone.utc),
                json.dumps({}),
            ),
        )
        conn.execute(
            """
            INSERT INTO heimdal_raw_representation (
                id, record_id, storage_kind, location_ref,
                ciphertext, nonce, key_ref, active
            ) VALUES (%s, %s, 'encrypted_local_cold', %s, NULL, NULL, NULL, false)
            """,
            (representation_id, record_id, old_location_ref),
        )

    with pytest.raises(
        Exception,
        match="cold representation location lacks producing archive identity",
    ):
        _upgrade(dsn, monkeypatch, CURRENT_REPRESENTATION_HEAD)

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        assert cur.fetchone() == ("e2f3a4b5c6d7",)
        cur.execute(
            "SELECT location_ref FROM heimdal_raw_representation WHERE id = %s",
            (representation_id,),
        )
        assert cur.fetchone() == (old_location_ref,)
        cur.execute(
            """
            SELECT count(*)
            FROM pg_constraint
            WHERE conrelid = 'heimdal_raw_representation'::regclass
              AND conname = 'heimdal_raw_representation_cold_location_bound_check'
            """
        )
        assert cur.fetchone() == (0,)


def test_current_upgrade_refuses_uncorrelated_active_raw_generation(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, "f4b6c8d0e2a1")
    record_id = uuid.uuid4()
    content_identity = _content_identity(b"uncorrelated-active-row")
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO heimdal_raw_record (
                id, content_identity, capture_chain, sensor, consent,
                source_path, ingested_at, payload
            ) VALUES (%s, %s, '[]'::jsonb, '{}'::jsonb, '{}'::jsonb,
                      'source-class-redacted', now(), '{}'::jsonb)
            """,
            (record_id, content_identity),
        )
        conn.execute(
            """
            INSERT INTO heimdal_raw_liveness_generation (
                content_identity, generation, record_id, raw_ref, activated_at
            ) VALUES (%s, 1, %s, %s, now())
            """,
            (content_identity, record_id, f"heimraw:{record_id}"),
        )
        conn.execute(
            """
            INSERT INTO heimdal_raw_representation (
                id, record_id, storage_kind, location_ref,
                ciphertext, nonce, key_ref, active
            ) VALUES (%s, %s, 'postgres_hot', %s, %s, %s, 'test-key', true)
            """,
            (record_id, record_id, f"heimloc:{record_id}", b"ciphertext", b"012345678901"),
        )

    with pytest.raises(Exception, match="lacks durable consent association"):
        _upgrade(dsn, monkeypatch, CURRENT_REPRESENTATION_HEAD)

    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "f4b6c8d0e2a1",
        )
        assert conn.execute(
            "SELECT count(*) FROM heimdal_raw_record WHERE id = %s",
            (record_id,),
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT to_regclass('heimdal_raw_consent_association')"
        ).fetchone() == (None,)


def test_ingress_preflight_refuses_e2_schema_without_archive_binding_constraint(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, "e2f3a4b5c6d7")
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())

    from app.heimdal import ingress_preflight, raw_liveness

    with pytest.raises(
        raw_liveness.RawLivenessSchemaMissingError,
        match="Raw identity/representation schema is not migration-ready",
    ):
        raw_liveness.assert_runtime_schema()

    monkeypatch.setattr(
        ingress_preflight,
        "resolve_active_grant",
        lambda *, scope: {"scope": scope},
    )
    ingress_preflight.reset_ingress_preflight()
    result = ingress_preflight.run_ingress_preflight()

    assert result.raw_store_key_available is True
    assert result.raw_liveness_schema_available is False
    assert result.media_consent_grant_available is True
    assert result.lanes == {
        ingress_preflight.LANE_MEDIA: ingress_preflight.STATE_UNAVAILABLE,
        ingress_preflight.LANE_SCREEN: ingress_preflight.STATE_UNAVAILABLE,
    }
    assert (
        f"{ingress_preflight.DETAIL_RAW_LIVENESS_SCHEMA_UNAVAILABLE}:"
        "RawLivenessSchemaMissingError" in result.detail
    )

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        assert cur.fetchone() == ("e2f3a4b5c6d7",)
        cur.execute("SELECT count(*) FROM heimdal_raw_deletion_receipt")
        assert cur.fetchone() == (0,)
        cur.execute("SELECT count(*) FROM heimdal_raw_deletion_tombstone")
        assert cur.fetchone() == (0,)


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
            "DROP TRIGGER heimdal_raw_representation_no_mutation " "ON heimdal_raw_representation",
            "heimdal_raw_representation_no_mutation",
        ),
        (
            "ALTER TABLE heimdal_raw_representation DROP CONSTRAINT "
            "heimdal_raw_representation_generation_fk",
            "heimdal_raw_representation_generation_fk",
        ),
        (
            "ALTER TABLE heimdal_raw_representation DROP CONSTRAINT "
            "heimdal_raw_representation_cold_location_bound_check",
            "heimdal_raw_representation_cold_location_bound_check",
        ),
    ],
    ids=[
        "one-active-index",
        "identity-trigger",
        "representation-trigger",
        "representation-generation-fk",
        "cold-location-binding-constraint",
    ],
)
def test_test_bootstrap_refuses_malformed_final_schema_without_self_repair(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
    drop_statement: str,
    missing_object: str,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, CURRENT_REPRESENTATION_HEAD)
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
            ) OR EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'heimdal_raw_representation'::regclass
                  AND conname = %s
            )
            """,
            (missing_object, missing_object, missing_object),
        )
        row = cur.fetchone()
        assert row is not None and row[0] is False


@pytest.mark.parametrize(
    ("drop_statement", "missing_object"),
    [
        (
            "DROP INDEX heimdal_raw_consent_association_grant_idx",
            "heimdal_raw_consent_association_grant_idx",
        ),
        (
            "DROP TRIGGER heimdal_raw_consent_association_no_mutation "
            "ON heimdal_raw_consent_association",
            "heimdal_raw_consent_association_no_mutation",
        ),
    ],
    ids=["consent-association-index", "consent-association-trigger"],
)
def test_test_bootstrap_never_repairs_existing_har05_liveness_ddl(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
    drop_statement: str,
    missing_object: str,
) -> None:
    """Existing tables stay Alembic-owned even with fixture autocreate enabled."""
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, CURRENT_REPRESENTATION_HEAD)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(drop_statement)

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    from app.heimdal import raw_liveness, raw_store

    try:
        raw_store._PgRawStore()  # noqa: SLF001
    except (raw_store.RawStoreSchemaMissingError, raw_liveness.RawLivenessSchemaMissingError) as exc:
        assert "alembic upgrade head" in str(exc)

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
        assert cur.fetchone() == (False,)


def test_test_bootstrap_refuses_weakened_cold_location_constraint_semantics(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, CURRENT_REPRESENTATION_HEAD)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            """
            ALTER TABLE heimdal_raw_representation
            DROP CONSTRAINT heimdal_raw_representation_cold_location_bound_check;
            ALTER TABLE heimdal_raw_representation
            ADD CONSTRAINT heimdal_raw_representation_cold_location_bound_check
            CHECK (
                storage_kind <> 'encrypted_local_cold'
                OR location_ref LIKE 'heimloc:cold:%'
            )
            """
        )

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    from app.heimdal import raw_store

    with pytest.raises(raw_store.RawStoreSchemaMissingError, match="alembic upgrade head"):
        raw_store._PgRawStore()

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'heimdal_raw_representation'::regclass
              AND conname = 'heimdal_raw_representation_cold_location_bound_check'
            """
        )
        row = cur.fetchone()
        assert row is not None and "~~ 'heimloc:cold:%'" in str(row[0])


def test_pg_representation_activation_and_all_copy_erasure_are_transactional(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, CURRENT_REPRESENTATION_HEAD)
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
                ciphertext, nonce, key_ref, raw_generation,
                archive_token, archive_generation, active
            ) VALUES (
                %s, %s, 'postgres_hot', %s, %s, %s, %s,
                (SELECT generation FROM heimdal_raw_liveness_generation WHERE record_id = %s),
                NULL, NULL, false
            )
            """,
            (
                corrupt_id,
                record.id,
                f"heimloc:{corrupt_id}",
                bad_ciphertext,
                bad_nonce,
                "test-key-v1",
                record.id,
            ),
        )
    with pytest.raises(RawRepresentationIdentityMismatchError):
        activate_raw_representation(record.id, corrupt_id, key=_KEY)
    representations = all_raw_representations(record.id)
    assert next(item for item in representations if item.id == representation_id).active is True
    assert next(item for item in representations if item.id == corrupt_id).active is False
    assert all_raw_read_receipts() == []

    assert (
        read_raw_record(
            raw_ref,
            reader="authorized-reader",
            purpose="Postgres active representation",
            key=_KEY,
        ).plaintext
        == b"pg-active-copy"
    )
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


def test_pre_cleanup_reconciliation_schema_refuses_erasure_before_transition(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, PRE_REPRESENTATION_HEAD)
    record_id = uuid.uuid4()
    _insert_legacy_record(
        dsn,
        record_id=record_id,
        plaintext=b"pre-reconciliation-erasure-refusal",
    )
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())
    _upgrade(dsn, monkeypatch, COLD_REPRESENTATION_HEAD)
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)

    from app.heimdal import raw_liveness, raw_store

    # Keep the historical d1 boundary explicit without asking the current
    # schema assertion to accept it. At this exact head the legacy append-only
    # receipt trigger is valid, while the guarded cleanup transition is not.
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT pg_get_functiondef(t.tgfoid), pg_get_triggerdef(t.oid)
            FROM pg_trigger AS t
            JOIN pg_class AS c ON c.oid = t.tgrelid
            WHERE c.relname = 'heimdal_raw_deletion_receipt'
              AND t.tgname = 'heimdal_raw_deletion_receipt_no_update'
              AND NOT t.tgisinternal
            """
        )
        historical_trigger = cur.fetchone()
        assert historical_trigger is not None
        assert raw_liveness._receipt_trigger_is_legacy_migration_ready(  # noqa: SLF001
            str(historical_trigger[0]), str(historical_trigger[1])
        )
        assert not raw_liveness._receipt_trigger_is_migration_ready(  # noqa: SLF001
            str(historical_trigger[0]), str(historical_trigger[1])
        )

    # The current runtime checks the complete current schema first and must
    # refuse this historical database before it can begin an erase transition.
    with pytest.raises(
        raw_store.RawStoreSchemaMissingError,
        match="columns do not match the location-aware schema",
    ):
        raw_liveness.governed_delete_raw_record(
            record_id=str(record_id),
            reason="hard_retention_bound",
            retention_window_days=30,
            deleted_at=datetime.now(timezone.utc),
        )

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM heimdal_raw_record WHERE id = %s", (record_id,))
        assert cur.fetchone() == (1,)
        cur.execute("SELECT count(*) FROM heimdal_raw_deletion_receipt")
        assert cur.fetchone() == (0,)
        cur.execute("SELECT count(*) FROM heimdal_raw_deletion_tombstone")
        assert cur.fetchone() == (0,)


def test_pg_relocation_reservation_fences_retention_and_crash_cleanup(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, CURRENT_REPRESENTATION_HEAD)
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())

    from app.heimdal import local_archive, raw_liveness, raw_store
    from app.ops.heimdal_cold_volume import (
        _ARCHIVE_VOLUME_READY_ISSUER,
        _issue_archive_volume_ready,
    )

    plaintext = b"pg-relocation-retention-race"
    ciphertext, nonce = raw_store.encrypt_raw_bytes(plaintext, key=_KEY)
    record, created = raw_store.insert_raw_record(
        content_identity=raw_store.compute_raw_content_identity(plaintext),
        capture_chain=["migration-test"],
        sensor={"adapter": "migration-test"},
        consent={"grant_ref": "migration-test"},
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="migration-test-key",
        key=_KEY,
        source_path="migration-test.raw",
    )
    assert created
    now = datetime.now(timezone.utc)
    eligible = replace(record, ingested_at=now - timedelta(days=8))
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    archive_ref = "pg-test-archive"
    proof = _issue_archive_volume_ready(
        archive_ref,
        archive_root,
        _issuer=_ARCHIVE_VOLUME_READY_ISSUER,
    )
    reservation_seen = threading.Event()
    object_written = threading.Event()
    release_relocation = threading.Event()
    retention_at_fence = threading.Event()

    def crash_after_object(stage: str) -> None:
        if stage == "after_reservation":
            pending = [
                item
                for item in raw_store.all_raw_representations(record.id)
                if item.storage_kind == "encrypted_local_cold" and not item.active
            ]
            assert len(pending) == 1
            assert list((archive_root / "representations").glob("*.bin")) == []
            reservation_seen.set()
        if stage == "after_object_write":
            object_written.set()
            assert release_relocation.wait(timeout=10)
            raise KeyboardInterrupt("simulated relocation process loss")

    monkeypatch.setattr(local_archive, "_relocation_stage_hook", crash_after_object)
    monkeypatch.setattr(
        raw_liveness,
        "_retention_fence_hook",
        lambda _record_id: retention_at_fence.set(),
    )

    def relocate_then_crash() -> str:
        try:
            local_archive.relocate_raw_record(
                eligible,
                archive_root=archive_root,
                archive_ref=archive_ref,
                now=now,
                retention_window_days=30,
                key=_KEY,
                volume_ready=lambda: proof,
            )
        except KeyboardInterrupt:
            return "crashed"
        raise AssertionError("relocation unexpectedly completed")

    def delete_after_fence():
        return raw_liveness.governed_delete_raw_record(
            record_id=record.id,
            reason="hard_retention_bound",
            retention_window_days=30,
            deleted_at=now,
        )

    raw_store.revoke_cold_archive_binding()
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            relocation = executor.submit(relocate_then_crash)
            assert reservation_seen.wait(timeout=10)
            assert object_written.wait(timeout=10)
            deletion = executor.submit(delete_after_fence)
            assert retention_at_fence.wait(timeout=10)
            assert not deletion.done()
            assert len(list((archive_root / "representations").glob("*.bin"))) == 1
            release_relocation.set()
            assert relocation.result(timeout=10) == "crashed"
            assert deletion.result(timeout=10).outcome == "deleted"

        assert raw_store.all_raw_records() == []
        assert raw_store.all_raw_representations(record.id) == []
        assert raw_liveness.all_deletion_receipts()[0].payload["cold_cleanup_location_refs"] == []
        assert list((archive_root / "representations").glob("*.bin")) == []
        assert list((archive_root / "manifests").glob("*.json")) == []
    finally:
        raw_store.revoke_cold_archive_binding()


def test_pg_archive_lock_keeps_cleanup_retryable_if_db_fence_is_lost(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, CURRENT_REPRESENTATION_HEAD)
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())

    from app.heimdal import local_archive, raw_liveness, raw_store
    from app.ops.heimdal_cold_volume import (
        _ARCHIVE_VOLUME_READY_ISSUER,
        _issue_archive_volume_ready,
    )

    plaintext = b"pg-relocation-fence-loss"
    ciphertext, nonce = raw_store.encrypt_raw_bytes(plaintext, key=_KEY)
    record, created = raw_store.insert_raw_record(
        content_identity=raw_store.compute_raw_content_identity(plaintext),
        capture_chain=["migration-test"],
        sensor={"adapter": "migration-test"},
        consent={"grant_ref": "migration-test"},
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="migration-test-key",
        key=_KEY,
        source_path="migration-test.raw",
    )
    assert created
    now = datetime.now(timezone.utc)
    eligible = replace(record, ingested_at=now - timedelta(days=8))
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    archive_ref = "pg-test-archive"
    proof = _issue_archive_volume_ready(
        archive_ref,
        archive_root,
        _issuer=_ARCHIVE_VOLUME_READY_ISSUER,
    )
    object_written = threading.Event()
    release_relocation = threading.Event()

    def pause_after_object(stage: str) -> None:
        if stage == "after_object_write":
            object_written.set()
            assert release_relocation.wait(timeout=10)

    # Model a dropped PG fence connection while the producer process remains
    # alive. The verified archive lock must still stop cleanup from declaring a
    # missing object terminal before that writer has quiesced.
    monkeypatch.setattr(local_archive, "_relocation_stage_hook", pause_after_object)
    durable_checkpoint = raw_liveness._checkpoint_raw_mutation_authority  # noqa: SLF001

    def checkpoint_then_lose_db_fence(authority: object) -> None:
        durable_checkpoint(authority)
        cursor = raw_liveness.pg_cursor_for_raw_mutation(
            authority,
            record_id=record.id,
            content_identity=record.content_identity,
        )
        cursor.execute(
            "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
            (record.content_identity,),
        )
        assert cursor.fetchone() == (True,)
        cursor.connection.commit()

    monkeypatch.setattr(
        raw_liveness,
        "_checkpoint_raw_mutation_authority",
        checkpoint_then_lose_db_fence,
    )

    def relocate_after_fence_loss() -> str:
        try:
            local_archive.relocate_raw_record(
                eligible,
                archive_root=archive_root,
                archive_ref=archive_ref,
                now=now,
                retention_window_days=30,
                key=_KEY,
                volume_ready=lambda: proof,
            )
        except local_archive.ArchiveDegradedError:
            return "degraded"
        raise AssertionError("relocation unexpectedly completed after authority deletion")

    def delete_during_external_write():
        return raw_liveness.governed_delete_raw_record(
            record_id=record.id,
            reason="hard_retention_bound",
            retention_window_days=30,
            deleted_at=now,
        )

    raw_store.revoke_cold_archive_binding()
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            relocation = executor.submit(relocate_after_fence_loss)
            assert object_written.wait(timeout=10)
            deletion = executor.submit(delete_during_external_write)
            with pytest.raises(raw_store.RawRepresentationDeletionError):
                deletion.result(timeout=10)

            assert raw_store.all_raw_records() == []
            pending = raw_liveness.all_deletion_receipts()
            assert len(pending) == 1
            assert pending[0].payload["cold_cleanup_location_refs"]
            release_relocation.set()
            assert relocation.result(timeout=10) == "degraded"

        reconciled = raw_liveness.governed_delete_raw_record(
            record_id=record.id,
            reason="hard_retention_bound",
            retention_window_days=30,
            deleted_at=now,
        )
        assert reconciled.outcome == "already_erased"
        assert raw_liveness.all_deletion_receipts()[0].payload["cold_cleanup_location_refs"] == []
        assert list((archive_root / "representations").glob("*.bin")) == []
        assert list((archive_root / "manifests").glob("*.json")) == []
    finally:
        release_relocation.set()
        raw_store.revoke_cold_archive_binding()


def test_pg_cleanup_refuses_a_different_verified_archive_after_rebind(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, CURRENT_REPRESENTATION_HEAD)
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())

    from app.heimdal import local_archive, raw_liveness, raw_store
    from app.ops.heimdal_cold_volume import (
        _ARCHIVE_VOLUME_READY_ISSUER,
        _issue_archive_volume_ready,
    )

    plaintext = b"pg-archive-bound-cleanup"
    ciphertext, nonce = raw_store.encrypt_raw_bytes(plaintext, key=_KEY)
    record, created = raw_store.insert_raw_record(
        content_identity=raw_store.compute_raw_content_identity(plaintext),
        capture_chain=["migration-test"],
        sensor={"adapter": "migration-test"},
        consent={"grant_ref": "migration-test"},
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="migration-test-key",
        key=_KEY,
        source_path="migration-test.raw",
    )
    assert created
    now = datetime.now(timezone.utc)
    eligible = replace(record, ingested_at=now - timedelta(days=8))
    original_root = tmp_path / "original-archive"
    replacement_root = tmp_path / "replacement-archive"
    original_root.mkdir()
    replacement_root.mkdir()
    original_ref = "pg-shared-archive-identity"
    replacement_ref = original_ref
    original_proof = _issue_archive_volume_ready(
        original_ref,
        original_root,
        _issuer=_ARCHIVE_VOLUME_READY_ISSUER,
    )
    replacement_proof = _issue_archive_volume_ready(
        replacement_ref,
        replacement_root,
        _issuer=_ARCHIVE_VOLUME_READY_ISSUER,
    )

    raw_store.revoke_cold_archive_binding()
    try:
        result = local_archive.relocate_raw_record(
            eligible,
            archive_root=original_root,
            archive_ref=original_ref,
            now=now,
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: original_proof,
        )
        location_ref = result.active_representation.location_ref
        original_generation = result.active_representation.archive_generation
        assert original_generation is not None
        original_object = (
            original_root / "representations" / f"{result.active_representation.id}.bin"
        )

        def rebind_after_authority(stage: str) -> None:
            if stage == "after_raw_delete":
                raw_store.configure_cold_archive_root(
                    replacement_root,
                    verified_volume=replacement_proof,
                    expected_archive_ref=replacement_ref,
                )

        monkeypatch.setattr(raw_liveness, "_retention_stage_hook", rebind_after_authority)
        with pytest.raises(raw_store.RawRepresentationDeletionError, match="binding"):
            raw_liveness.governed_delete_raw_record(
                record_id=record.id,
                reason="hard_retention_bound",
                retention_window_days=30,
                deleted_at=now,
            )

        assert raw_store.all_raw_records() == []
        receipt = raw_liveness.all_deletion_receipts()[0]
        assert receipt.payload["cold_cleanup_location_refs"] == [location_ref]
        assert original_object.exists()
        assert raw_store._cold_object_path(  # noqa: SLF001
            location_ref,
            expected_archive_generation=original_generation,
        ) is None

        monkeypatch.setattr(raw_liveness, "_retention_stage_hook", lambda _stage: None)
        raw_store.configure_cold_archive_root(
            original_root,
            verified_volume=original_proof,
            expected_archive_ref=original_ref,
        )
        retried = raw_liveness.governed_delete_raw_record(
            record_id=record.id,
            reason="hard_retention_bound",
            retention_window_days=30,
            deleted_at=now,
        )

        assert retried.outcome == "already_erased"
        receipt = raw_liveness.all_deletion_receipts()[0]
        assert receipt.payload["cold_cleanup_location_refs"] == []
        assert not original_object.exists()
    finally:
        raw_store.revoke_cold_archive_binding()


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
    bootstrapped_shape = _raw_schema_snapshot(bootstrapped)
    migrated_shape = _raw_schema_snapshot(migrated)
    assert {
        key: value
        for key, value in bootstrapped_shape.items()
        if key != "representation_functions"
    } == {
        key: value
        for key, value in migrated_shape.items()
        if key != "representation_functions"
    }
    receipt_functions = bootstrapped_shape["receipt_functions"]
    assert any(
        "TG_OP = 'UPDATE'" in function_def
        and "current_setting('app.heimdal_retention_reconcile', true) = 'true'" in function_def
        and "RETURN NEW" in function_def
        and "RAISE EXCEPTION" in function_def
        and "BEFORE DELETE OR UPDATE" in trigger_def
        for function_def, trigger_def in receipt_functions
    )
    constraints = bootstrapped_shape["constraints"]
    assert any(
        name == "heimdal_raw_representation_cold_owner_check"
        and "location_ref" in definition
        and "archive_token" in definition
        and "::text" in definition
        for _table, name, _kind, definition in constraints
    )
    for representation_functions in (
        bootstrapped_shape["representation_functions"],
        migrated_shape["representation_functions"],
    ):
        assert len(representation_functions) == 1
        representation_guard = representation_functions[0].lower()
        assert (
            "new.raw_generation is distinct from authority_generation"
            in representation_guard
        )
        assert "cold_cleanup_location_refs" in representation_guard
        assert "new.location_ref" in representation_guard
        assert "pending governed cleanup" in representation_guard


def test_pg_screen_retention_lease_then_postcommit_cleanup_restart_converges_metadata_only(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, CURRENT_REPRESENTATION_HEAD)
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())

    from app.heimdal import raw_liveness, raw_store, retention
    from app.heimdal.raw_read_gate import raw_ref_for
    from app.heimdal.settings_notes import (
        SETTINGS,
        SettingsNote,
        read_settings_note,
        write_settings_note,
    )
    from app.ops.heimdal_cold_volume import (
        _ARCHIVE_VOLUME_READY_ISSUER,
        _issue_archive_volume_ready,
    )
    from app.write_guard import WriteGuard

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    write_settings_note(
        vault_root,
        SettingsNote(
            spec=SETTINGS,
            values={
                "retention_window_days": 30,
                "screen_frame_retention_minutes": 1,
            },
        ),
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    now = datetime.now(timezone.utc) + timedelta(days=2)
    leased = _insert_runtime_raw(
        b"pg-screen-live-lease",
        grant_ref="grant-pg-screen-live",
        modality="screen",
    )
    lease = raw_liveness.issue_response_lease(
        raw_ref=raw_ref_for(leased),
        content_identity=leased.content_identity,
        now=now,
    )

    with pytest.raises(retention.RetentionErasurePendingError, match="drain|lease"):
        retention.enforce_screen_frame_retention(vault_root=vault_root, now=now)
    assert raw_store.resolve_active_raw_record(leased.id) is not None
    assert raw_liveness.all_deletion_receipts() == []
    settings = read_settings_note(vault_root, SETTINGS)
    assert settings is not None and "last_enforced_at" not in settings.values

    drained_at = lease.expires_at + timedelta(microseconds=1)
    assert retention.enforce_screen_frame_retention(
        vault_root=vault_root,
        now=drained_at,
    ).deleted_count == 1

    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    archived_record = _insert_runtime_raw(
        b"pg-screen-post-commit-retry",
        grant_ref="grant-pg-screen-cold",
        modality="screen",
    )
    archive_time = drained_at + timedelta(minutes=2)
    _archive_runtime_raw(archived_record, archive_root=archive_root, now=archive_time)
    raw_store.revoke_cold_archive_binding()
    monkeypatch.setattr(
        raw_store,
        "_resolve_cold_ciphertext",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("screen metadata discovery materialized cold ciphertext")
        ),
    )

    fresh_store = raw_store._PgRawStore()  # noqa: SLF001
    selected = fresh_store.retention_metadata_before(
        archive_time - timedelta(minutes=1),
        modality="screen",
    )
    assert [item.record_id for item in selected] == [archived_record.id]
    with pytest.raises(raw_store.RawRepresentationDeletionError, match="binding"):
        retention.enforce_screen_frame_retention(
            vault_root=vault_root,
            now=archive_time,
        )

    assert raw_store.resolve_active_raw_record(archived_record.id) is None
    pending = next(
        receipt
        for receipt in raw_liveness.all_deletion_receipts()
        if receipt.record_id == archived_record.id
    )
    assert pending.reason == retention.REASON_SCREEN_FRAME_RETENTION_BUFFER
    assert pending.payload["cold_cleanup_location_refs"]

    restarted_store = raw_store._PgRawStore()  # noqa: SLF001
    assert restarted_store.retention_metadata_before(
        archive_time - timedelta(minutes=1),
        modality="screen",
    ) == []
    with pytest.raises(raw_store.RawRepresentationDeletionError, match="binding"):
        retention.enforce_screen_frame_retention(
            vault_root=vault_root,
            now=archive_time,
        )

    proof = _issue_archive_volume_ready(
        "pg-har05-archive",
        archive_root,
        _issuer=_ARCHIVE_VOLUME_READY_ISSUER,
    )
    raw_store.configure_cold_archive_root(
        archive_root,
        verified_volume=proof,
        expected_archive_ref="pg-har05-archive",
    )
    converged = retention.enforce_screen_frame_retention(
        vault_root=vault_root,
        now=archive_time,
    )
    assert converged.deleted_count == 0
    pending = next(
        receipt
        for receipt in raw_liveness.all_deletion_receipts()
        if receipt.record_id == archived_record.id
    )
    assert pending.payload["cold_cleanup_location_refs"] == []
    settings = read_settings_note(vault_root, SETTINGS)
    assert settings is not None and "last_enforced_at" not in settings.values


def test_pg_pending_cleanup_serializes_same_archive_generation_alias_relocation(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, CURRENT_REPRESENTATION_HEAD)
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())

    from app.heimdal import raw_liveness, raw_store, retention
    from app.ops.heimdal_cold_volume import (
        _ARCHIVE_VOLUME_READY_ISSUER,
        _issue_archive_volume_ready,
    )

    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    plaintext = b"pg-same-archive-new-raw-generation"
    original = _insert_runtime_raw(plaintext, grant_ref="grant-pg-generation-one")
    archived_original = _archive_runtime_raw(original, archive_root=archive_root, now=now)
    old_representation = archived_original.active_representation
    old_object = archive_root / "representations" / f"{old_representation.id}.bin"
    old_manifest = archive_root / "manifests" / f"{old_representation.id}.json"
    original_manifest = old_manifest.read_text(encoding="utf-8")
    original_delete = raw_store._delete_cold_object_path  # noqa: SLF001
    monkeypatch.setattr(
        raw_store,
        "_delete_cold_object_path",
        lambda _path: (_ for _ in ()).throw(
            raw_store.RawRepresentationDeletionError("leave generation N pending")
        ),
    )
    with pytest.raises(raw_store.RawRepresentationDeletionError):
        raw_liveness.governed_delete_raw_record(
            record_id=original.id,
            reason=retention.REASON_HARD_RETENTION_BOUND,
            retention_window_days=30,
            deleted_at=now,
        )

    newer = _insert_runtime_raw(plaintext, grant_ref="grant-pg-generation-two")
    archived_newer = _archive_runtime_raw(newer, archive_root=archive_root, now=now)
    new_representation = archived_newer.active_representation
    assert new_representation.raw_generation == old_representation.raw_generation + 1
    assert new_representation.archive_generation == old_representation.archive_generation
    new_object = archive_root / "representations" / f"{new_representation.id}.bin"
    new_bytes = new_object.read_bytes()

    aliased_manifest = json.loads(original_manifest)
    aliased_manifest["raw_generation"] = new_representation.raw_generation
    old_manifest.write_text(json.dumps(aliased_manifest, sort_keys=True) + "\n", encoding="utf-8")
    monkeypatch.setattr(raw_store, "_delete_cold_object_path", original_delete)
    with pytest.raises(
        raw_store.RawRepresentationDeletionError,
        match="generation|manifest|ownership",
    ):
        raw_liveness.governed_delete_raw_record(
            record_id=original.id,
            reason=retention.REASON_HARD_RETENTION_BOUND,
            retention_window_days=30,
            deleted_at=now,
        )
    assert old_object.exists()
    assert new_object.read_bytes() == new_bytes
    old_manifest.write_text(original_manifest, encoding="utf-8")

    proof = _issue_archive_volume_ready(
        "pg-har05-archive",
        archive_root,
        _issuer=_ARCHIVE_VOLUME_READY_ISSUER,
    )
    interleaving: list[str] = []

    def attempt_alias_while_cleanup_owns_archive(stage: str, object_path: Path) -> None:
        if stage != "before_unlink" or object_path != old_object or interleaving:
            return
        with pytest.raises(
            raw_store.RawRepresentationDeletionError,
            match="pending governed cleanup",
        ):
            raw_store.register_cold_location(
                old_representation.location_ref,
                old_object,
                verified_volume=proof,
                raw_generation=new_representation.raw_generation,
                representation_id=old_representation.id,
            )
        interleaving.append(stage)

    monkeypatch.setattr(raw_store, "_cold_delete_stage_hook", attempt_alias_while_cleanup_owns_archive)
    retried = raw_liveness.governed_delete_raw_record(
        record_id=original.id,
        reason=retention.REASON_HARD_RETENTION_BOUND,
        retention_window_days=30,
        deleted_at=now,
    )
    assert retried.outcome == "already_erased"
    assert interleaving == ["before_unlink"]
    assert not old_object.exists()
    assert new_object.read_bytes() == new_bytes
    newer_representations = raw_store.all_raw_representations(newer.id)
    assert any(
        representation.active and representation.id == new_representation.id
        for representation in newer_representations
    )


@pytest.mark.parametrize("matching_grant", ["grant-pg-a", "grant-pg-b"])
def test_pg_multigrant_pending_cleanup_filters_exact_lineage_and_keyless_legacy(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    matching_grant: str,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, CURRENT_REPRESENTATION_HEAD)
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())

    from app.heimdal import raw_liveness, raw_store, retention

    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    plaintext = f"pg-multigrant-{matching_grant}".encode()
    first = _insert_runtime_raw(plaintext, grant_ref="grant-pg-a")
    replay_ciphertext, replay_nonce = raw_store.encrypt_raw_bytes(plaintext, key=_KEY)
    replay, created = raw_store.insert_raw_record(
        content_identity=raw_store.compute_raw_content_identity(plaintext),
        capture_chain=["migration-test"],
        sensor={"adapter": "migration-test"},
        consent={"grant_ref": "grant-pg-b"},
        ciphertext=replay_ciphertext,
        nonce=replay_nonce,
        key_ref="migration-test-key",
        key=_KEY,
        source_path="source-class-redacted",
    )
    assert created is False and replay.id == first.id
    _archive_runtime_raw(first, archive_root=archive_root, now=now)
    original_delete = raw_store._delete_cold_object_path  # noqa: SLF001
    monkeypatch.setattr(
        raw_store,
        "_delete_cold_object_path",
        lambda _path: (_ for _ in ()).throw(
            raw_store.RawRepresentationDeletionError("A+B cleanup remains pending")
        ),
    )
    with pytest.raises(raw_store.RawRepresentationDeletionError):
        raw_liveness.governed_delete_raw_record(
            record_id=first.id,
            reason=retention.REASON_HARD_RETENTION_BOUND,
            retention_window_days=30,
            deleted_at=now,
        )
    current = next(
        receipt for receipt in raw_liveness.all_deletion_receipts() if receipt.record_id == first.id
    )
    assert raw_liveness.CONSENT_GRANT_DIGEST_PAYLOAD_KEY not in current.payload
    assert set(current.payload[raw_liveness.CONSENT_GRANT_DIGESTS_PAYLOAD_KEY]) == {
        raw_liveness.consent_grant_digest("grant-pg-a"),
        raw_liveness.consent_grant_digest("grant-pg-b"),
    }

    assert retention.enforce_consent_revocation(
        grant_ref="grant-pg-c",
        revoked_at=now,
    ).deleted_count == 0
    current = next(
        receipt for receipt in raw_liveness.all_deletion_receipts() if receipt.record_id == first.id
    )
    assert current.payload["cold_cleanup_location_refs"]

    monkeypatch.setattr(raw_store, "_delete_cold_object_path", original_delete)
    assert retention.enforce_consent_revocation(
        grant_ref=matching_grant,
        revoked_at=now,
    ).deleted_count == 0
    current = next(
        receipt for receipt in raw_liveness.all_deletion_receipts() if receipt.record_id == first.id
    )
    assert current.payload["cold_cleanup_location_refs"] == []

    legacy = _insert_runtime_raw(
        f"pg-keyless-legacy-{matching_grant}".encode(),
        grant_ref="grant-pg-historical-row",
    )
    _archive_runtime_raw(legacy, archive_root=archive_root, now=now)
    monkeypatch.setattr(
        raw_store,
        "_delete_cold_object_path",
        lambda _path: (_ for _ in ()).throw(
            raw_store.RawRepresentationDeletionError("true legacy cleanup remains pending")
        ),
    )
    with pytest.raises(raw_store.RawRepresentationDeletionError):
        raw_liveness.governed_delete_raw_record(
            record_id=legacy.id,
            reason=retention.REASON_HARD_RETENTION_BOUND,
            retention_window_days=30,
            deleted_at=now,
        )
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            "ALTER TABLE heimdal_raw_deletion_receipt DISABLE TRIGGER "
            "heimdal_raw_deletion_receipt_no_update"
        )
        try:
            conn.execute(
                "UPDATE heimdal_raw_deletion_receipt "
                "SET payload = payload - %s - %s WHERE record_id = %s",
                (
                    raw_liveness.CONSENT_GRANT_DIGEST_PAYLOAD_KEY,
                    raw_liveness.CONSENT_GRANT_DIGESTS_PAYLOAD_KEY,
                    legacy.id,
                ),
            )
        finally:
            conn.execute(
                "ALTER TABLE heimdal_raw_deletion_receipt ENABLE TRIGGER "
                "heimdal_raw_deletion_receipt_no_update"
            )
    legacy_receipt = next(
        receipt for receipt in raw_liveness.all_deletion_receipts() if receipt.record_id == legacy.id
    )
    assert raw_liveness.CONSENT_GRANT_DIGEST_PAYLOAD_KEY not in legacy_receipt.payload
    assert raw_liveness.CONSENT_GRANT_DIGESTS_PAYLOAD_KEY not in legacy_receipt.payload
    with pytest.raises(raw_store.RawRepresentationDeletionError, match="true legacy"):
        retention.enforce_consent_revocation(
            grant_ref="grant-pg-legacy-trigger",
            revoked_at=now,
        )
    monkeypatch.setattr(raw_store, "_delete_cold_object_path", original_delete)
    assert retention.enforce_consent_revocation(
        grant_ref="grant-pg-legacy-trigger",
        revoked_at=now,
    ).deleted_count == 0
    legacy_receipt = next(
        receipt for receipt in raw_liveness.all_deletion_receipts() if receipt.record_id == legacy.id
    )
    assert legacy_receipt.payload["cold_cleanup_location_refs"] == []


def test_pg_consent_fence_and_revocation_projection_cover_both_race_orderings(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, CURRENT_REPRESENTATION_HEAD)
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())

    from app.heimdal import consent_ledger, raw_liveness, raw_store
    from app.heimdal.raw_read_gate import raw_ref_for

    grant_ref = "grant-pg-har05-race"
    consent_ledger.grant_consent(
        grant_ref=grant_ref,
        basis="session_optin",
        scope="session:pg-har05-race",
        granted_by="operator",
    )
    insert_fenced = threading.Event()
    release_insert = threading.Event()

    def insert_under_grant():
        plaintext = b"pg-insert-before-revocation"
        ciphertext, nonce = raw_store.encrypt_raw_bytes(plaintext, key=_KEY)
        with consent_ledger.consent_raw_admission(grant_ref):
            insert_fenced.set()
            assert release_insert.wait(timeout=10)
            record, created = raw_store.insert_raw_record(
                content_identity=raw_store.compute_raw_content_identity(plaintext),
                capture_chain=["migration-test"],
                sensor={"adapter": "migration-test"},
                consent={"grant_ref": grant_ref},
                ciphertext=ciphertext,
                nonce=nonce,
                key_ref="migration-test-key",
                key=_KEY,
                source_path="source-class-redacted",
            )
        assert created
        return record

    with ThreadPoolExecutor(max_workers=2) as executor:
        insertion = executor.submit(insert_under_grant)
        assert insert_fenced.wait(timeout=10)
        revocation = executor.submit(
            consent_ledger.revoke_consent,
            grant_ref=grant_ref,
            revoked_by="operator",
        )
        assert not revocation.done()
        release_insert.set()
        record = insertion.result(timeout=10)
        revocation.result(timeout=10)

    assert raw_store.resolve_active_raw_record(record.id) is None
    projection = raw_liveness.project_with_response_leases(
        [(raw_ref_for(record), record.content_identity)]
    )
    assert projection[raw_ref_for(record)].outcome == "erased"

    with pytest.raises(consent_ledger.ConsentRefusedError):
        with consent_ledger.consent_raw_admission(grant_ref):
            raise AssertionError("revoked grant reached raw insertion")


@pytest.mark.parametrize("revoked_grant", ["grant-pg-a", "grant-pg-b"])
def test_pg_identical_bytes_preserve_all_grants_and_either_revocation_erases(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
    revoked_grant: str,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, CURRENT_REPRESENTATION_HEAD)
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())

    from app.heimdal import raw_liveness, raw_store, retention

    plaintext = b"pg-identical-evidence-under-two-grants"
    first = _insert_runtime_raw(plaintext, grant_ref="grant-pg-a")
    ciphertext, nonce = raw_store.encrypt_raw_bytes(plaintext, key=_KEY)
    replay, created = raw_store.insert_raw_record(
        content_identity=raw_store.compute_raw_content_identity(plaintext),
        capture_chain=["migration-test"],
        sensor={"adapter": "migration-test"},
        consent={"grant_ref": "grant-pg-b"},
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="migration-test-key",
        key=_KEY,
        source_path="source-class-redacted",
    )

    assert created is False and replay.id == first.id
    assert raw_store.raw_record_ids_by_consent_grant("grant-pg-a") == [first.id]
    assert raw_store.raw_record_ids_by_consent_grant("grant-pg-b") == [first.id]
    erased = retention.enforce_consent_revocation(
        grant_ref=revoked_grant,
        revoked_at=datetime.now(timezone.utc),
    )

    assert erased.deleted_count == 1
    assert raw_store.resolve_active_raw_record(first.id) is None
    assert set(
        erased.deletions[0].payload[raw_liveness.CONSENT_GRANT_DIGESTS_PAYLOAD_KEY]
    ) == {
        raw_liveness.consent_grant_digest("grant-pg-a"),
        raw_liveness.consent_grant_digest("grant-pg-b"),
    }
    with psycopg.connect(dsn) as conn:
        assert conn.execute(
            "SELECT count(*) FROM heimdal_raw_consent_association WHERE record_id = %s",
            (first.id,),
        ).fetchone() == (0,)


def test_pg_retirement_claim_refuses_read_registration_and_activation(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, CURRENT_REPRESENTATION_HEAD)
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "pg-retirement-reader")

    from app.heimdal import raw_liveness, raw_read_gate, raw_store, retention

    record = _insert_runtime_raw(b"pg-retirement-fence", grant_ref="grant-pg-retiring")
    now = datetime.now(timezone.utc)
    raw_liveness.issue_response_lease(
        raw_ref=raw_read_gate.raw_ref_for(record),
        content_identity=record.content_identity,
        now=now,
    )
    assert raw_liveness.governed_delete_raw_record(
        record_id=record.id,
        reason=retention.REASON_HARD_RETENTION_BOUND,
        retention_window_days=30,
        deleted_at=now,
    ).outcome == "lease_valid"

    with pytest.raises(raw_read_gate.RawReadRefusedError, match="retiring"):
        raw_read_gate.read_raw_record(
            raw_read_gate.raw_ref_for(record),
            reader="pg-retirement-reader",
            purpose="must refuse after claim",
            key=_KEY,
        )
    ciphertext, nonce = raw_store.encrypt_raw_bytes(b"pg-retirement-fence", key=_KEY)
    with pytest.raises(raw_liveness.RawLivenessUnavailableError, match="retiring"):
        raw_store.register_raw_representation(
            record_id=record.id,
            ciphertext=ciphertext,
            nonce=nonce,
            key_ref="migration-test-key",
            key=_KEY,
        )
    with pytest.raises(raw_liveness.RawLivenessUnavailableError, match="retiring"):
        raw_store.activate_raw_representation(record.id, record.id, key=_KEY)


def test_pg_durable_revocation_row_replays_after_propagation_crash(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, CURRENT_REPRESENTATION_HEAD)
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())

    from app.heimdal import consent_ledger, raw_liveness, raw_store, retention

    grant_ref = "grant-pg-crash-replay"
    consent_ledger.grant_consent(
        grant_ref=grant_ref,
        basis="session_optin",
        scope="session:pg-crash-replay",
        granted_by="operator",
    )
    record = _insert_runtime_raw(b"pg-revocation-crash", grant_ref=grant_ref)
    original_enforce = retention.enforce_consent_revocation
    monkeypatch.setattr(
        retention,
        "enforce_consent_revocation",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("process lost after revocation commit")),
    )

    with pytest.raises(RuntimeError, match="process lost after revocation commit"):
        consent_ledger.revoke_consent(grant_ref=grant_ref, revoked_by="operator")
    assert raw_store.resolve_active_raw_record(record.id) is not None
    assert grant_ref in consent_ledger.list_revoked_grant_refs()

    monkeypatch.setattr(retention, "enforce_consent_revocation", original_enforce)
    monkeypatch.setattr(retention, "_resolve_retention_window_days", lambda *_args, **_kwargs: 30)
    result = retention.enforce_hard_retention_bound(
        vault_root=tmp_path,
        now=datetime.now(timezone.utc),
        record_last_enforced=False,
    )

    assert result.deleted_count == 0
    assert raw_store.resolve_active_raw_record(record.id) is None
    receipt = raw_liveness.all_deletion_receipts()[0]
    assert receipt.reason == retention.REASON_CONSENT_REVOKED
    assert receipt.payload[raw_liveness.CONSENT_GRANT_DIGEST_PAYLOAD_KEY] == (
        raw_liveness.consent_grant_digest(grant_ref)
    )


def test_pg_revocation_cleanup_correlation_handles_other_grants_and_legacy_rows(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, CURRENT_REPRESENTATION_HEAD)
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())

    from app.heimdal import consent_ledger, raw_liveness, raw_store, retention

    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    original_delete = raw_store._delete_cold_object_path  # noqa: SLF001
    monkeypatch.setattr(
        raw_store,
        "_delete_cold_object_path",
        lambda _path: (_ for _ in ()).throw(
            raw_store.RawRepresentationDeletionError("cold unavailable")
        ),
    )

    unrelated = _insert_runtime_raw(b"pg-unrelated-pending", grant_ref="grant-pg-other")
    _archive_runtime_raw(unrelated, archive_root=archive_root, now=now)
    with pytest.raises(raw_store.RawRepresentationDeletionError):
        raw_liveness.governed_delete_raw_record(
            record_id=unrelated.id,
            reason=retention.REASON_HARD_RETENTION_BOUND,
            retention_window_days=30,
            deleted_at=now,
        )

    target_ref = "grant-pg-isolated-target"
    consent_ledger.grant_consent(
        grant_ref=target_ref,
        basis="session_optin",
        scope="session:pg-isolated-target",
        granted_by="operator",
    )
    target = _insert_runtime_raw(b"pg-target-hot", grant_ref=target_ref)
    consent_ledger.revoke_consent(grant_ref=target_ref, revoked_by="operator")
    assert raw_store.resolve_active_raw_record(target.id) is None
    assert raw_liveness.all_deletion_receipts()[0].payload["cold_cleanup_location_refs"]

    monkeypatch.setattr(raw_store, "_delete_cold_object_path", original_delete)
    raw_liveness.governed_delete_raw_record(
        record_id=unrelated.id,
        reason=retention.REASON_HARD_RETENTION_BOUND,
        retention_window_days=30,
        deleted_at=now,
    )

    historical = _insert_runtime_raw(
        b"pg-historical-pending", grant_ref="grant-pg-historical-row"
    )
    _archive_runtime_raw(historical, archive_root=archive_root, now=now)
    monkeypatch.setattr(
        raw_store,
        "_delete_cold_object_path",
        lambda _path: (_ for _ in ()).throw(
            raw_store.RawRepresentationDeletionError("historical cold unavailable")
        ),
    )
    with pytest.raises(raw_store.RawRepresentationDeletionError):
        raw_liveness.governed_delete_raw_record(
            record_id=historical.id,
            reason=retention.REASON_HARD_RETENTION_BOUND,
            retention_window_days=30,
            deleted_at=now,
        )
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            "ALTER TABLE heimdal_raw_deletion_receipt DISABLE TRIGGER "
            "heimdal_raw_deletion_receipt_no_update"
        )
        try:
            conn.execute(
                "UPDATE heimdal_raw_deletion_receipt "
                "SET payload = payload - %s - %s WHERE record_id = %s",
                (
                    raw_liveness.CONSENT_GRANT_DIGEST_PAYLOAD_KEY,
                    raw_liveness.CONSENT_GRANT_DIGESTS_PAYLOAD_KEY,
                    historical.id,
                ),
            )
        finally:
            conn.execute(
                "ALTER TABLE heimdal_raw_deletion_receipt ENABLE TRIGGER "
                "heimdal_raw_deletion_receipt_no_update"
            )

    legacy_trigger_ref = "grant-pg-legacy-trigger"
    consent_ledger.grant_consent(
        grant_ref=legacy_trigger_ref,
        basis="session_optin",
        scope="session:pg-legacy-trigger",
        granted_by="operator",
    )
    with pytest.raises(raw_store.RawRepresentationDeletionError):
        consent_ledger.revoke_consent(
            grant_ref=legacy_trigger_ref,
            revoked_by="operator",
        )

    monkeypatch.setattr(raw_store, "_delete_cold_object_path", original_delete)
    assert consent_ledger.reconcile_revoked_consent_erasure() == 2
    historical_receipt = next(
        receipt
        for receipt in raw_liveness.all_deletion_receipts()
        if receipt.record_id == historical.id
    )
    assert historical_receipt.payload["cold_cleanup_location_refs"] == []


def test_pg_scheduled_cleanup_failure_is_loud_and_retryable(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, CURRENT_REPRESENTATION_HEAD)
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())

    from app.heimdal import raw_liveness, raw_store, retention

    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    record = _insert_runtime_raw(b"pg-scheduled-retry", grant_ref="grant-pg-scheduled")
    _archive_runtime_raw(record, archive_root=archive_root, now=now)
    original_delete = raw_store._delete_cold_object_path  # noqa: SLF001
    monkeypatch.setattr(
        raw_store,
        "_delete_cold_object_path",
        lambda _path: (_ for _ in ()).throw(
            raw_store.RawRepresentationDeletionError("scheduled cold unavailable")
        ),
    )
    with pytest.raises(raw_store.RawRepresentationDeletionError):
        raw_liveness.governed_delete_raw_record(
            record_id=record.id,
            reason=retention.REASON_HARD_RETENTION_BOUND,
            retention_window_days=30,
            deleted_at=now,
        )
    monkeypatch.setattr(retention, "_resolve_retention_window_days", lambda *_args, **_kwargs: 30)
    with pytest.raises(raw_store.RawRepresentationDeletionError):
        retention.enforce_hard_retention_bound(
            vault_root=tmp_path,
            now=now,
            record_last_enforced=False,
        )
    assert raw_liveness.all_deletion_receipts()[0].payload["cold_cleanup_location_refs"]

    monkeypatch.setattr(raw_store, "_delete_cold_object_path", original_delete)
    retention.enforce_hard_retention_bound(
        vault_root=tmp_path,
        now=now,
        record_last_enforced=False,
    )
    assert raw_liveness.all_deletion_receipts()[0].payload[
        "cold_cleanup_location_refs"
    ] == []


def test_pg_archived_read_and_deletion_share_exact_representation_fence(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, CURRENT_REPRESENTATION_HEAD)
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "pg-har05-reader")

    from app.heimdal import raw_liveness, raw_store, retention
    from app.heimdal import raw_read_gate

    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    plaintext = b"pg-cold-read-fence"
    record = _insert_runtime_raw(plaintext, grant_ref="grant-pg-read-fence")
    archived = _archive_runtime_raw(record, archive_root=archive_root, now=now)
    read_fenced = threading.Event()
    release_read = threading.Event()
    deletion_waiting = threading.Event()

    def pause_read(stage: str) -> None:
        assert stage == "after_active_representation_resolution"
        read_fenced.set()
        assert release_read.wait(timeout=10)

    monkeypatch.setattr(raw_read_gate, "_raw_read_stage_hook", pause_read)
    monkeypatch.setattr(
        raw_liveness,
        "_retention_fence_hook",
        lambda _record_id: deletion_waiting.set(),
    )

    def read():
        return raw_read_gate.read_raw_record(
            raw_read_gate.raw_ref_for(record),
            reader="pg-har05-reader",
            purpose="restore_drill",
            key=_KEY,
        )

    def delete():
        return raw_liveness.governed_delete_raw_record(
            record_id=record.id,
            reason=retention.REASON_HARD_RETENTION_BOUND,
            retention_window_days=30,
            deleted_at=now,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        read_future = executor.submit(read)
        if not read_fenced.wait(timeout=10):
            # Surface a fail-closed pre-fence read error instead of hiding it
            # behind an event timeout; a genuinely live read remains bounded.
            read_future.result(timeout=0)
            raise AssertionError("archived read did not reach the representation fence")
        delete_future = executor.submit(delete)
        assert deletion_waiting.wait(timeout=10)
        assert not delete_future.done()
        release_read.set()
        gated = read_future.result(timeout=10)
        deletion = delete_future.result(timeout=10)

    assert gated.plaintext == plaintext
    assert gated.storage_kind == "encrypted_local_cold"
    assert gated.representation_id == archived.active_representation.id
    assert gated.receipt.content_identity == record.content_identity
    assert deletion.outcome == "deleted"
    assert raw_store.resolve_active_raw_record(record.id) is None
    assert list((archive_root / "representations").glob("*.bin")) == []
    assert list((archive_root / "manifests").glob("*.json")) == []
