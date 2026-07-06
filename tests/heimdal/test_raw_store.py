"""Heimdal raw-evidence store v0 (#3025, Epic #3019 slice A6).

Covers the store's own contract independent of the capture adapter that
calls it (`tests/heimdal/test_capture_adapter.py` exercises the adapter's
behavioral ACs through this store as its durable write target):

- append-only enforcement (HEIM-1), mirroring the identical test pattern in
  `test_consent_ledger.py` / `test_observation_log.py`;
- encryption round-trip (AES-256-GCM) and tamper detection;
- idempotent insert by ``content_identity``;
- provenance fields are required and rejected when missing (defense in
  depth beyond the capture adapter's own validation).
"""

from __future__ import annotations

import secrets

import pytest

from app.heimdal import raw_store
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
    yield
    reset_memory_raw_store()


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
