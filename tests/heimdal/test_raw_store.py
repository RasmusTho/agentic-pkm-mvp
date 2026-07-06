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

import secrets

import pytest

from app.heimdal import raw_read_gate, raw_store
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
def _reset_raw_store(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_memory_raw_store()
    reset_memory_raw_read_receipts()
    yield
    reset_memory_raw_store()
    reset_memory_raw_read_receipts()


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
    ciphertext, nonce = encrypt_raw_bytes(b"bytes", key=_TEST_KEY)
    record, created = insert_raw_record(
        content_identity="hash-1",
        capture_chain=["ios_voice_memos", "icloud_drive", "folder_watch"],
        sensor=_sensor_block(),
        consent=_consent_block(),
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="v1-process-key",
        source_path="/tmp/memo.m4a",
    )

    assert created is True
    assert record.content_identity == "hash-1"
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
        content_identity="hash-missing-field",
        capture_chain=["ios_voice_memos", "icloud_drive", "folder_watch"],
        sensor=_sensor_block(),
        consent=_consent_block(),
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="v1-process-key",
        source_path="/tmp/memo.m4a",
    )
    kwargs[field] = value

    with pytest.raises(ValueError):
        insert_raw_record(**kwargs)


# --- Idempotency by content_identity ---------------------------------------


def test_insert_raw_record_idempotent_by_content_identity() -> None:
    ciphertext, nonce = encrypt_raw_bytes(b"bytes", key=_TEST_KEY)
    kwargs = dict(
        content_identity="hash-dup",
        capture_chain=["ios_voice_memos", "icloud_drive", "folder_watch"],
        sensor=_sensor_block(),
        consent=_consent_block(),
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="v1-process-key",
        source_path="/tmp/memo.m4a",
    )

    first, first_created = insert_raw_record(**kwargs)
    second, second_created = insert_raw_record(**kwargs)

    assert first_created is True
    assert second_created is False
    assert first.id == second.id
    assert len(all_raw_records()) == 1


def test_get_raw_record_by_content_identity() -> None:
    ciphertext, nonce = encrypt_raw_bytes(b"bytes", key=_TEST_KEY)
    record, _ = insert_raw_record(
        content_identity="hash-lookup",
        capture_chain=["ios_voice_memos", "icloud_drive", "folder_watch"],
        sensor=_sensor_block(),
        consent=_consent_block(),
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="v1-process-key",
        source_path="/tmp/memo.m4a",
    )

    found = get_raw_record_by_content_identity("hash-lookup")
    assert found is not None
    assert found.id == record.id
    assert get_raw_record_by_content_identity("no-such-hash") is None


# --- Append-only structural guarantee (HEIM-1) ------------------------------


def test_no_mutation_method_exported() -> None:
    public_names = {name for name in dir(raw_store) if not name.startswith("_")}
    mutating_names = {name for name in public_names if "update" in name or "delete" in name}
    assert mutating_names == set(), f"unexpected mutation surface exported: {mutating_names}"


def test_no_mutation_method_on_resolved_backend() -> None:
    backend = raw_store._backend()
    assert not hasattr(backend, "update")
    assert not hasattr(backend, "delete")


@pytest.mark.pg
def test_append_only_enforced_pg() -> None:
    """Real Postgres trigger rejects UPDATE/DELETE against heimdal_raw_record (HEIM-1)."""
    pytest.importorskip("psycopg")

    ciphertext, nonce = encrypt_raw_bytes(b"bytes", key=_TEST_KEY)
    record, _ = insert_raw_record(
        content_identity=f"hash-pg-{secrets.token_hex(8)}",
        capture_chain=["ios_voice_memos", "icloud_drive", "folder_watch"],
        sensor=_sensor_block(),
        consent=_consent_block(),
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="v1-process-key",
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


# --- Gated read path (A7, HEIM-5) -------------------------------------------


def _insert_test_record(content_identity: str = "hash-gate-1") -> "raw_store.RawRecord":
    ciphertext, nonce = encrypt_raw_bytes(b"raw voice memo bytes", key=_TEST_KEY)
    record, _ = insert_raw_record(
        content_identity=content_identity,
        capture_chain=["ios_voice_memos", "icloud_drive", "folder_watch"],
        sensor=_sensor_block(),
        consent=_consent_block(),
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="v1-process-key",
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

    assert result.plaintext == b"raw voice memo bytes"

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
    ciphertext, nonce = encrypt_raw_bytes(b"end-to-end raw bytes", key=_TEST_KEY)
    record, created = insert_raw_record(
        content_identity="hash-gate-e2e",
        capture_chain=["ios_voice_memos", "icloud_drive", "folder_watch"],
        sensor=_sensor_block(),
        consent=_consent_block(),
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="v1-process-key",
        source_path="/tmp/memo.m4a",
    )
    assert created is True

    raw_ref = raw_ref_for(record)
    result = read_raw_record(raw_ref, reader="asr_stage", purpose="transcription", key=_TEST_KEY)

    assert result.plaintext == b"end-to-end raw bytes"
    assert get_raw_record_by_content_identity("hash-gate-e2e") is not None
    assert len(all_raw_read_receipts()) == 1


@pytest.mark.pg
def test_append_only_enforced_pg_read_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real Postgres trigger rejects UPDATE/DELETE against heimdal_raw_read_receipt (HEIM-1)."""
    pytest.importorskip("psycopg")
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "asr_stage")

    ciphertext, nonce = encrypt_raw_bytes(b"bytes", key=_TEST_KEY)
    record, _ = insert_raw_record(
        content_identity=f"hash-pg-receipt-{secrets.token_hex(8)}",
        capture_chain=["ios_voice_memos", "icloud_drive", "folder_watch"],
        sensor=_sensor_block(),
        consent=_consent_block(),
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="v1-process-key",
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
