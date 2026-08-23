"""Heimdal raw-evidence store v0 (#3025, Epic #3019 slice A6) + gated read
path (#3027, Epic #3019 slice A7).

Covers the store's own contract independent of the capture adapter that
calls it (`tests/heimdal/test_capture_adapter.py` exercises the adapter's
behavioral ACs through this store as its durable write target):

- append-only enforcement (HEIM-1), mirroring the identical test pattern in
  `test_consent_ledger.py` / `test_observation_log.py`;
- encryption round-trip (AES-256-GCM) and tamper detection;
- idempotent insert by ``content_identity``;
- provenance fields are required and rejected when missing (defense in
  depth beyond the capture adapter's own validation).

The section below (`--- Gated read path (A7, HEIM-5) ---`) covers the
allowlist + receipt gate in `app.heimdal.raw_read_gate` over this same
store: refused-without-allowlist, receipt-on-success, receipt append-only,
and `raw_ref` opacity (the underlying `source_path` never surfaces through
the gated read call).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets

import pytest

from app.heimdal import raw_liveness, raw_read_gate, raw_store
from app.heimdal.raw_read_gate import (
    RawReadAllowlistMissingError,
    RawReadRefusedError,
    all_raw_read_receipts,
    raw_ref_for,
    read_raw_record,
    reset_memory_raw_read_receipts,
    resolve_read_allowlist,
)
from app.heimdal.raw_store import (
    RawStoreKeyMissingError,
    all_raw_records,
    compute_raw_content_identity,
    decrypt_raw_bytes,
    encrypt_raw_bytes,
    get_raw_record_by_content_identity,
    insert_raw_record,
    reset_memory_raw_store,
    resolve_raw_store_key,
)

pytestmark = pytest.mark.not_pg

_TEST_KEY = bytes.fromhex(secrets.token_hex(32))


@pytest.fixture(autouse=True)
def _reset_raw_store(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    # Mirror tests/conftest.py::force_memory_store_for_non_pg: only non-pg
    # tests force the in-process memory backend. pg-marked tests must exercise
    # the real Postgres backend so their inserted rows actually persist and the
    # subsequent UPDATE/DELETE can trigger the append-only guard (HEIM-1);
    # forcing memory here would make insert_raw_record write a memory-only row
    # whose id matches zero Postgres rows, turning the trigger assertion into a
    # vacuous no-op.
    if request.node.get_closest_marker("pg") is None:
        monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_memory_raw_store()
    reset_memory_raw_read_receipts()
    yield
    reset_memory_raw_store()
    reset_memory_raw_read_receipts()


@pytest.fixture
def pg_raw_store_database(monkeypatch: pytest.MonkeyPatch):
    """Give direct PG store tests a fresh migration-equivalent producer shape."""

    psycopg = pytest.importorskip("psycopg")
    from app.db.dsn import resolve_dsn

    admin_dsn = resolve_dsn()
    if not admin_dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    database_name = f"scratch_raw_store_{secrets.token_hex(6)}"
    base, separator, _database = admin_dsn.rpartition("/")
    if not separator:
        pytest.fail("direct PG raw-store tests require a database-qualified DSN")
    scratch_dsn = f"{base}/{database_name}"
    try:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{database_name}"')
        with psycopg.connect(scratch_dsn, autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        monkeypatch.setenv("DATABASE_URL", scratch_dsn)
        monkeypatch.delenv("DB_DSN", raising=False)
        monkeypatch.setenv("STORE_BACKEND", "pg")
        monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
        yield scratch_dsn
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')


def _consent_block(grant_ref: str = "grant-test") -> dict:
    return {
        "basis": "self_record",
        "granted_by": "operator",
        "granted_at": "2026-07-06T00:00:00Z",
        "third_party": "none",
        "grant_ref": grant_ref,
    }


def _sensor_block() -> dict:
    return {"adapter": "test_adapter", "version": "v1", "device": "test-device"}


# --- Encryption round-trip -------------------------------------------------


def test_encrypt_decrypt_round_trip() -> None:
    plaintext = b"raw voice memo bytes"
    ciphertext, nonce = encrypt_raw_bytes(plaintext, key=_TEST_KEY)

    assert ciphertext != plaintext
    assert decrypt_raw_bytes(ciphertext, nonce, key=_TEST_KEY) == plaintext


def test_decrypt_with_wrong_key_raises() -> None:
    plaintext = b"raw voice memo bytes"
    ciphertext, nonce = encrypt_raw_bytes(plaintext, key=_TEST_KEY)
    wrong_key = bytes.fromhex(secrets.token_hex(32))

    with pytest.raises(Exception):
        decrypt_raw_bytes(ciphertext, nonce, key=wrong_key)


def test_decrypt_tampered_ciphertext_raises() -> None:
    plaintext = b"raw voice memo bytes"
    ciphertext, nonce = encrypt_raw_bytes(plaintext, key=_TEST_KEY)
    tampered = bytes([ciphertext[0] ^ 0xFF]) + ciphertext[1:]

    with pytest.raises(Exception):
        decrypt_raw_bytes(tampered, nonce, key=_TEST_KEY)


def test_resolve_raw_store_key_missing_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEIMDAL_RAW_STORE_KEY", raising=False)
    with pytest.raises(RawStoreKeyMissingError):
        resolve_raw_store_key()


def test_resolve_raw_store_key_wrong_length_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", "abcd")
    with pytest.raises(RawStoreKeyMissingError):
        resolve_raw_store_key()


def test_resolve_raw_store_key_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    hex_key = secrets.token_hex(32)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", hex_key)
    assert resolve_raw_store_key() == bytes.fromhex(hex_key)


# --- insert_raw_record: provenance-in-same-write (KERNEL-06) --------------


def test_insert_raw_record_stamps_provenance_in_one_call() -> None:
    plaintext = b"bytes"
    ciphertext, nonce = encrypt_raw_bytes(plaintext, key=_TEST_KEY)
    identity = compute_raw_content_identity(plaintext)
    record, created = insert_raw_record(
        content_identity=identity,
        capture_chain=["ios_voice_memos", "icloud_drive", "folder_watch"],
        sensor=_sensor_block(),
        consent=_consent_block(),
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="v1-process-key",
        key=_TEST_KEY,
        source_path="/tmp/memo.m4a",
    )

    assert created is True
    assert record.content_identity == identity
    assert record.capture_chain == ["ios_voice_memos", "icloud_drive", "folder_watch"]
    assert record.sensor == _sensor_block()
    assert record.consent["grant_ref"] == "grant-test"


@pytest.mark.parametrize(
    "field,value",
    [
        ("capture_chain", []),
        ("sensor", {}),
        ("consent", {}),
        ("consent", {"basis": "self_record"}),  # missing grant_ref
    ],
)
def test_insert_raw_record_requires_provenance_fields(field: str, value: object) -> None:
    ciphertext, nonce = encrypt_raw_bytes(b"bytes", key=_TEST_KEY)
    kwargs = dict(
        content_identity=compute_raw_content_identity(b"bytes"),
        capture_chain=["ios_voice_memos", "icloud_drive", "folder_watch"],
        sensor=_sensor_block(),
        consent=_consent_block(),
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="v1-process-key",
        key=_TEST_KEY,
        source_path="/tmp/memo.m4a",
    )
    kwargs[field] = value

    with pytest.raises(ValueError):
        insert_raw_record(**kwargs)


# --- Idempotency by content_identity ---------------------------------------


def test_insert_raw_record_idempotent_by_content_identity() -> None:
    ciphertext, nonce = encrypt_raw_bytes(b"bytes", key=_TEST_KEY)
    kwargs = dict(
        content_identity=compute_raw_content_identity(b"bytes"),
        capture_chain=["ios_voice_memos", "icloud_drive", "folder_watch"],
        sensor=_sensor_block(),
        consent=_consent_block(),
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="v1-process-key",
        key=_TEST_KEY,
        source_path="/tmp/memo.m4a",
    )

    first, first_created = insert_raw_record(**kwargs)
    second, second_created = insert_raw_record(**kwargs)

    assert first_created is True
    assert second_created is False
    assert first.id == second.id
    assert len(all_raw_records()) == 1


def test_get_raw_record_by_content_identity() -> None:
    plaintext = b"bytes"
    ciphertext, nonce = encrypt_raw_bytes(plaintext, key=_TEST_KEY)
    identity = compute_raw_content_identity(plaintext)
    record, _ = insert_raw_record(
        content_identity=identity,
        capture_chain=["ios_voice_memos", "icloud_drive", "folder_watch"],
        sensor=_sensor_block(),
        consent=_consent_block(),
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="v1-process-key",
        key=_TEST_KEY,
        source_path="/tmp/memo.m4a",
    )

    found = get_raw_record_by_content_identity(identity)
    assert found is not None
    assert found.id == record.id
    assert get_raw_record_by_content_identity("no-such-hash") is None


# --- Append-only structural guarantee (HEIM-1) ------------------------------


def test_no_mutation_method_exported() -> None:
    """HEIM-1: raw_store exports no mutation surface.

    Governed retention deletion is authority-owned by ``raw_liveness`` so no
    caller can remove raw state without the shared fence and tombstone commit.
    """
    public_names = {name for name in dir(raw_store) if not name.startswith("_")}
    updating_names = {name for name in public_names if "update" in name}
    deleting_names = {name for name in public_names if "delete" in name}
    assert updating_names == set(), f"unexpected update surface exported: {updating_names}"
    assert deleting_names == set(), (
        f"unexpected delete surface exported: {deleting_names}"
    )


def test_no_mutation_method_on_resolved_backend() -> None:
    """The resolved backend itself exposes no generic `update`; `hard_delete`
    is the one named, governed D-RETENTION exception (not a generic
    `delete`), matching `raw_store.hard_delete_raw_record` above."""
    backend = raw_store._backend()
    assert not hasattr(backend, "update")
    assert not hasattr(backend, "delete")
    assert hasattr(backend, "hard_delete")


@pytest.mark.pg
def test_append_only_enforced_pg(pg_raw_store_database: str) -> None:
    """Real Postgres trigger rejects UPDATE/DELETE against heimdal_raw_record (HEIM-1)."""
    pytest.importorskip("psycopg")

    plaintext = f"bytes-{secrets.token_hex(8)}".encode()
    ciphertext, nonce = encrypt_raw_bytes(plaintext, key=_TEST_KEY)
    record, _ = insert_raw_record(
        content_identity=compute_raw_content_identity(plaintext),
        capture_chain=["ios_voice_memos", "icloud_drive", "folder_watch"],
        sensor=_sensor_block(),
        consent=_consent_block(),
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="v1-process-key",
        key=_TEST_KEY,
        source_path="/tmp/memo.m4a",
    )

    conn = raw_store._pg_connect()
    try:
        cur = conn.cursor()
        with pytest.raises(Exception) as excinfo:
            cur.execute(
                f"UPDATE {raw_store._TABLE} SET source_path = 'tampered' WHERE id = %s",
                (record.id,),
            )
        assert "append-only" in str(excinfo.value).lower() or "HEIM-1" in str(excinfo.value)

        with pytest.raises(Exception) as excinfo_del:
            cur.execute(f"DELETE FROM {raw_store._TABLE} WHERE id = %s", (record.id,))
        assert "append-only" in str(excinfo_del.value).lower() or "HEIM-1" in str(excinfo_del.value)
    finally:
        conn.close()


@pytest.mark.pg
def test_archive_relocation_lease_serializes_postgres_scheduler_sessions(
    pg_raw_store_database: str,
) -> None:
    """Two independently scheduled HAR-04 passes cannot overlap on one DB."""
    pytest.importorskip("psycopg")

    with raw_store.archive_relocation_lease():
        with pytest.raises(raw_store.RawArchiveRelocationLeaseUnavailableError):
            with raw_store.archive_relocation_lease():
                pytest.fail("a second PostgreSQL session acquired the HAR-04 run lease")

    # Closing the owning connection is the crash-safe release operation.
    with raw_store.archive_relocation_lease():
        pass


@pytest.mark.pg
def test_pg_legacy_cleanup_evidence_unknown_or_type_confused_never_erases(
    pg_raw_store_database: str,
) -> None:
    pytest.importorskip("psycopg")
    plaintext = f"pg-legacy-cleanup-{secrets.token_hex(8)}".encode()
    ciphertext, nonce = encrypt_raw_bytes(plaintext, key=_TEST_KEY)
    record, created = insert_raw_record(
        content_identity=compute_raw_content_identity(plaintext),
        capture_chain=["pg-legacy-cleanup"],
        sensor=_sensor_block(),
        consent=_consent_block(),
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="v1-process-key",
        key=_TEST_KEY,
        source_path="pg-legacy-cleanup.raw",
    )
    assert created
    deleted_at = datetime.now(timezone.utc)
    raw_liveness.governed_delete_raw_record(
        record_id=record.id,
        reason="test-cleanup",
        retention_window_days=30,
        deleted_at=deleted_at,
    )

    conn = raw_liveness._pg_connect(autocommit=False)  # noqa: SLF001
    try:
        cur = conn.cursor()
        cur.execute("ALTER TABLE heimdal_raw_deletion_receipt DISABLE TRIGGER USER")
        cur.execute(
            "UPDATE heimdal_raw_deletion_receipt "
            "SET payload = payload - 'cold_cleanup_location_refs' "
            "WHERE record_id = %s",
            (record.id,),
        )
        cur.execute("ALTER TABLE heimdal_raw_deletion_receipt ENABLE TRIGGER USER")
        conn.commit()
    finally:
        conn.close()

    projection = raw_liveness.project_with_response_leases(
        [(raw_ref_for(record), record.content_identity)],
        now=deleted_at,
    )
    assert projection[raw_ref_for(record)].outcome == "erasure_pending"
    with pytest.raises(
        raw_liveness.RawLivenessUnavailableError,
        match="cleanup queue evidence",
    ):
        raw_liveness.governed_delete_raw_record(
            record_id=record.id,
            reason="test-cleanup",
            retention_window_days=30,
            deleted_at=deleted_at,
        )

    representation_id = "33333333-3333-4333-8333-333333333333"
    archive_token = "a" * 64
    location_ref = f"heimloc:cold:{archive_token}:{representation_id}"
    conn = raw_liveness._pg_connect(autocommit=False)  # noqa: SLF001
    try:
        cur = conn.cursor()
        cur.execute("ALTER TABLE heimdal_raw_deletion_receipt DISABLE TRIGGER USER")
        cur.execute(
            "UPDATE heimdal_raw_deletion_receipt SET payload = jsonb_build_object("
            "'cold_cleanup_location_refs', jsonb_build_array(%s::text), "
            "'cold_cleanup_archive_bindings', jsonb_build_object(%s::text, "
            "jsonb_build_object('archive_token', %s::text, "
            "'archive_generation', %s::text, 'raw_generation', true, "
            "'representation_id', %s::text))) WHERE record_id = %s",
            (
                location_ref,
                location_ref,
                archive_token,
                "b" * 64,
                representation_id,
                record.id,
            ),
        )
        cur.execute("ALTER TABLE heimdal_raw_deletion_receipt ENABLE TRIGGER USER")
        conn.commit()
    finally:
        conn.close()

    type_confused = raw_liveness.project_with_response_leases(
        [(raw_ref_for(record), record.content_identity)],
        now=deleted_at,
    )
    assert type_confused[raw_ref_for(record)].outcome == "erasure_pending"
    with pytest.raises(
        raw_liveness.RawLivenessUnavailableError,
        match="stale or bound to a different generation",
    ):
        raw_liveness.governed_delete_raw_record(
            record_id=record.id,
            reason="test-cleanup",
            retention_window_days=30,
            deleted_at=deleted_at,
        )


@pytest.mark.pg
def test_archive_eligible_hot_selector_is_bounded_in_postgres(
    pg_raw_store_database: str,
) -> None:
    pytest.importorskip("psycopg")
    plaintext = f"archive-selector-{secrets.token_hex(12)}".encode()
    ciphertext, nonce = encrypt_raw_bytes(plaintext, key=_TEST_KEY)
    record, created = insert_raw_record(
        content_identity=compute_raw_content_identity(plaintext),
        capture_chain=["archive-selector-test"],
        sensor=_sensor_block(),
        consent=_consent_block(),
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="v1-process-key",
        key=_TEST_KEY,
        source_path="selector-test.raw",
    )
    assert created

    selected, eligible_count = raw_store.archive_eligible_hot_raw_records(
        ingested_before=record.ingested_at + timedelta(microseconds=1),
        ingested_at_or_after=record.ingested_at - timedelta(microseconds=1),
        limit=1,
    )

    assert eligible_count >= 1
    assert len(selected) == 1
    assert selected[0].id == record.id


# --- Gated read path (A7, HEIM-5) -------------------------------------------


def _insert_test_record(content_identity: str = "hash-gate-1") -> "raw_store.RawRecord":
    plaintext = f"raw voice memo bytes:{content_identity}".encode()
    ciphertext, nonce = encrypt_raw_bytes(plaintext, key=_TEST_KEY)
    record, _ = insert_raw_record(
        content_identity=compute_raw_content_identity(plaintext),
        capture_chain=["ios_voice_memos", "icloud_drive", "folder_watch"],
        sensor=_sensor_block(),
        consent=_consent_block(),
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="v1-process-key",
        key=_TEST_KEY,
        source_path="/tmp/very/secret/memo.m4a",
    )
    return record


def test_gated_read_requires_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    """A raw read is refused unless it passes the allowlist AND emits a receipt.

    Positive path: an allowlisted reader's read succeeds, returns the
    correct plaintext, and produces exactly one persisted receipt recording
    the read (reader, raw_ref, content_identity, purpose).
    """
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "asr_stage")
    record = _insert_test_record()
    raw_ref = raw_ref_for(record)

    assert all_raw_read_receipts() == []

    result = read_raw_record(raw_ref, reader="asr_stage", purpose="transcription", key=_TEST_KEY)

    assert result.plaintext == b"raw voice memo bytes:hash-gate-1"

    receipts = all_raw_read_receipts()
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt.raw_ref == raw_ref
    assert receipt.content_identity == record.content_identity
    assert receipt.reader == "asr_stage"
    assert receipt.purpose == "transcription"
    assert receipt is result.receipt


def test_gated_read_refused_when_not_allowlisted(monkeypatch: pytest.MonkeyPatch) -> None:
    """A reader absent from the allowlist is refused loudly; no receipt is written."""
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "asr_stage")
    record = _insert_test_record(content_identity="hash-gate-refused")
    raw_ref = raw_ref_for(record)

    with pytest.raises(RawReadRefusedError):
        read_raw_record(raw_ref, reader="unregistered_reader", purpose="snooping", key=_TEST_KEY)

    assert all_raw_read_receipts() == []


def test_gated_read_refused_unknown_raw_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unrecognized/malformed raw_ref is refused, not silently resolved to nothing."""
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "asr_stage")

    with pytest.raises(RawReadRefusedError):
        read_raw_record("heimraw:does-not-exist", reader="asr_stage", purpose="test", key=_TEST_KEY)

    with pytest.raises(RawReadRefusedError):
        read_raw_record("/tmp/some/path.m4a", reader="asr_stage", purpose="test", key=_TEST_KEY)

    assert all_raw_read_receipts() == []


def test_resolve_read_allowlist_missing_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """No configured allowlist refuses loudly rather than default-allowing every reader."""
    monkeypatch.delenv("HEIMDAL_RAW_READ_ALLOWLIST", raising=False)
    with pytest.raises(RawReadAllowlistMissingError):
        resolve_read_allowlist()


def test_resolve_read_allowlist_empty_string_allows_no_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit empty allowlist is a valid (maximally strict) configuration, not a missing one."""
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "")
    assert resolve_read_allowlist() == frozenset()


def test_receipt_append_only_no_mutation_surface() -> None:
    """Structural HEIM-1 guarantee: the receipt module exposes no update/delete function."""
    public_names = {name for name in dir(raw_read_gate) if not name.startswith("_")}
    mutating_names = {name for name in public_names if "update" in name or "delete" in name}
    assert mutating_names == set(), f"unexpected mutation surface exported: {mutating_names}"


def test_receipt_append_only_on_resolved_backend() -> None:
    backend = raw_read_gate._backend()
    assert not hasattr(backend, "update")
    assert not hasattr(backend, "delete")


def test_multiple_reads_append_multiple_receipts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each successful read appends its own receipt; reads are never deduplicated/merged."""
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "asr_stage,attribution_stage")
    record = _insert_test_record(content_identity="hash-gate-multi")
    raw_ref = raw_ref_for(record)

    read_raw_record(raw_ref, reader="asr_stage", purpose="transcription", key=_TEST_KEY)
    read_raw_record(raw_ref, reader="attribution_stage", purpose="attribution", key=_TEST_KEY)

    receipts = all_raw_read_receipts()
    assert len(receipts) == 2
    assert {r.reader for r in receipts} == {"asr_stage", "attribution_stage"}
    assert all(r.raw_ref == raw_ref for r in receipts)


def test_raw_ref_is_opaque_and_never_a_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """`raw_ref` never leaks `source_path` -- opaque handle only (FABLE_COMPANION §1.1 item 2)."""
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "asr_stage")
    record = _insert_test_record(content_identity="hash-gate-opaque")
    raw_ref = raw_ref_for(record)

    assert record.source_path not in raw_ref
    assert "/tmp" not in raw_ref
    assert raw_ref.startswith("heimraw:")
    assert record.id in raw_ref

    result = read_raw_record(raw_ref, reader="asr_stage", purpose="transcription", key=_TEST_KEY)

    # The receipt records the opaque handle and content_identity, never the path.
    assert result.receipt.raw_ref == raw_ref
    for field_value in vars(result.receipt).values():
        if isinstance(field_value, str):
            assert record.source_path not in field_value


def test_gated_read_exercises_real_production_call_site(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercises the actual production entrypoint end-to-end: insert -> mint raw_ref -> gated read.

    Guards against a stubbed-dependency-only test: this drives the same
    `app.heimdal.raw_read_gate.read_raw_record` call a real ASR/attribution
    stage would make, through the real memory backend resolution path
    (`app.heimdal._backend.resolve_heimdal_backend`), not a mocked store.
    """
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "asr_stage")
    plaintext = b"end-to-end raw bytes"
    ciphertext, nonce = encrypt_raw_bytes(plaintext, key=_TEST_KEY)
    identity = compute_raw_content_identity(plaintext)
    record, created = insert_raw_record(
        content_identity=identity,
        capture_chain=["ios_voice_memos", "icloud_drive", "folder_watch"],
        sensor=_sensor_block(),
        consent=_consent_block(),
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="v1-process-key",
        key=_TEST_KEY,
        source_path="/tmp/memo.m4a",
    )
    assert created is True

    raw_ref = raw_ref_for(record)
    result = read_raw_record(raw_ref, reader="asr_stage", purpose="transcription", key=_TEST_KEY)

    assert result.plaintext == b"end-to-end raw bytes"
    assert get_raw_record_by_content_identity(identity) is not None
    assert len(all_raw_read_receipts()) == 1


@pytest.mark.pg
def test_append_only_enforced_pg_read_receipt(
    monkeypatch: pytest.MonkeyPatch,
    pg_raw_store_database: str,
) -> None:
    """Real Postgres trigger rejects UPDATE/DELETE against heimdal_raw_read_receipt (HEIM-1)."""
    pytest.importorskip("psycopg")
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "asr_stage")

    plaintext = f"bytes-{secrets.token_hex(8)}".encode()
    ciphertext, nonce = encrypt_raw_bytes(plaintext, key=_TEST_KEY)
    record, _ = insert_raw_record(
        content_identity=compute_raw_content_identity(plaintext),
        capture_chain=["ios_voice_memos", "icloud_drive", "folder_watch"],
        sensor=_sensor_block(),
        consent=_consent_block(),
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="v1-process-key",
        key=_TEST_KEY,
        source_path="/tmp/memo.m4a",
    )
    raw_ref = raw_ref_for(record)
    result = read_raw_record(raw_ref, reader="asr_stage", purpose="transcription", key=_TEST_KEY)
    receipt_id = result.receipt.id

    conn = raw_read_gate._pg_connect()
    try:
        cur = conn.cursor()
        with pytest.raises(Exception) as excinfo:
            cur.execute(
                f"UPDATE {raw_read_gate._TABLE} SET purpose = 'tampered' WHERE id = %s",
                (receipt_id,),
            )
        assert "append-only" in str(excinfo.value).lower() or "HEIM-1" in str(excinfo.value)

        with pytest.raises(Exception) as excinfo_del:
            cur.execute(f"DELETE FROM {raw_read_gate._TABLE} WHERE id = %s", (receipt_id,))
        assert "append-only" in str(excinfo_del.value).lower() or "HEIM-1" in str(excinfo_del.value)
    finally:
        conn.close()
