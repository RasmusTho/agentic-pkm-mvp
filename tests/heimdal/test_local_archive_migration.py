"""HAR-02: location-aware raw identity and representation behavior (#3848)."""

from __future__ import annotations

import inspect
import secrets
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.heimdal import raw_store
from app.heimdal.raw_read_gate import (
    RawReadRefusedError,
    all_raw_read_receipts,
    raw_ref_for,
    read_raw_record,
    reset_memory_raw_read_receipts,
)
from app.heimdal.raw_store import (
    RawRepresentationDeletionError,
    RawRepresentationIdentityMismatchError,
    activate_raw_representation,
    all_raw_records,
    all_raw_representations,
    compute_raw_content_identity,
    encrypt_raw_bytes,
    get_raw_record_by_content_identity,
    insert_raw_record,
    register_raw_representation,
    reset_memory_raw_store,
)
from app.heimdal.retention import (
    all_deletion_receipts,
    enforce_hard_retention_bound,
    reset_memory_deletion_receipts,
)
from app.heimdal.settings_notes import DEFAULT_SETTINGS_DIR, SETTINGS, SettingsNote, write_settings_note
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg

_KEY = bytes.fromhex(secrets.token_hex(32))


@pytest.fixture(autouse=True)
def _memory_runtime(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "authorized-reader")
    reset_memory_raw_store()
    reset_memory_raw_read_receipts()
    reset_memory_deletion_receipts()
    yield
    reset_memory_raw_store()
    reset_memory_raw_read_receipts()
    reset_memory_deletion_receipts()


def _insert(plaintext: bytes = b"raw-evidence"):
    ciphertext, nonce = encrypt_raw_bytes(plaintext, key=_KEY)
    record, created = insert_raw_record(
        content_identity=compute_raw_content_identity(plaintext),
        capture_chain=["registered-sensor", "heimdal"],
        sensor={"sensor_id": "registered-sensor"},
        consent={"grant_ref": "standing-grant"},
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="test-key-v1",
        key=_KEY,
        source_path="source-class-redacted",
    )
    assert created
    return record


def _retention_vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    write_settings_note(
        root,
        SettingsNote(spec=SETTINGS, values={"retention_window_days": 1}),
        settings_dir=DEFAULT_SETTINGS_DIR,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    return root


def test_relocation_preserves_raw_ref_and_gated_read() -> None:
    record = _insert(b"first-copy")
    original_ref = raw_ref_for(record)
    immutable = (
        record.id,
        record.content_identity,
        record.capture_chain,
        record.sensor,
        record.consent,
        record.source_path,
        record.ingested_at,
    )

    ciphertext, nonce = encrypt_raw_bytes(b"first-copy", key=_KEY)
    representation_id = str(uuid4())
    replacement, created = register_raw_representation(
        record_id=record.id,
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="test-key-v1",
        key=_KEY,
        representation_id=representation_id,
    )
    assert created and not replacement.active

    # A replay of the same registration is idempotent, then activation changes
    # only representation state -- never the immutable raw identity.
    replay, replay_created = register_raw_representation(
        record_id=record.id,
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="test-key-v1",
        key=_KEY,
        representation_id=representation_id,
    )
    assert replay == replacement
    assert replay_created is False
    replay, replay_created = register_raw_representation(
        record_id=record.id,
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="test-key-v1",
        key=_KEY,
        representation_id=representation_id,
        activate=True,
    )
    assert replay_created is False
    assert replay.active is True

    relocated = get_raw_record_by_content_identity(record.content_identity)
    assert relocated is not None
    assert raw_ref_for(relocated) == original_ref
    assert (
        relocated.id,
        relocated.content_identity,
        relocated.capture_chain,
        relocated.sensor,
        relocated.consent,
        relocated.source_path,
        relocated.ingested_at,
    ) == immutable
    assert read_raw_record(
        original_ref, reader="authorized-reader", purpose="HAR-02 continuity proof", key=_KEY
    ).plaintext == b"first-copy"

    with pytest.raises(RawRepresentationIdentityMismatchError):
        register_raw_representation(
            record_id=record.id,
            ciphertext=b"different-registered-bytes",
            nonce=nonce,
            key_ref="test-key-v1",
            key=_KEY,
            representation_id=representation_id,
            activate=True,
        )
    assert read_raw_record(
        original_ref, reader="authorized-reader", purpose="conflict leaves state intact", key=_KEY
    ).plaintext == b"first-copy"


def test_raw_read_gate_resolves_registered_location_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _insert(b"active-copy")
    inactive_ciphertext, inactive_nonce = encrypt_raw_bytes(b"active-copy", key=_KEY)
    inactive, _ = register_raw_representation(
        record_id=record.id,
        ciphertext=inactive_ciphertext,
        nonce=inactive_nonce,
        key_ref="test-key-v1",
        key=_KEY,
    )

    resolved = False
    real_resolve = raw_store.resolve_active_raw_record

    def _observed_resolve(record_id: str):
        nonlocal resolved
        resolved = True
        return real_resolve(record_id)

    monkeypatch.setattr(raw_store, "resolve_active_raw_record", _observed_resolve)
    with pytest.raises(RawReadRefusedError):
        read_raw_record(
            raw_ref_for(record), reader="not-authorized", purpose="must fail before resolution"
        )
    assert resolved is False

    assert read_raw_record(
        raw_ref_for(record),
        reader="authorized-reader",
        purpose="active representation only",
        key=_KEY,
    ).plaintext == b"active-copy"
    assert resolved is True
    assert inactive.active is False

    # The production gate has no location/path input. A caller can present
    # only the opaque raw_ref; registered state selects storage internally.
    assert "path" not in inspect.signature(read_raw_record).parameters
    assert "location" not in inspect.signature(read_raw_record).parameters


def test_representation_identity_mismatch_is_atomic_and_resumable() -> None:
    mismatched_ciphertext, mismatched_nonce = encrypt_raw_bytes(
        b"different-plaintext", key=_KEY
    )
    with pytest.raises(RawRepresentationIdentityMismatchError):
        insert_raw_record(
            content_identity=compute_raw_content_identity(b"identity-bound-copy"),
            capture_chain=["registered-sensor", "heimdal"],
            sensor={"sensor_id": "registered-sensor"},
            consent={"grant_ref": "standing-grant"},
            ciphertext=mismatched_ciphertext,
            nonce=mismatched_nonce,
            key_ref="test-key-v1",
            key=_KEY,
            source_path="source-class-redacted",
        )
    assert all_raw_records() == []

    record = _insert(b"identity-bound-copy")
    original = all_raw_representations(record.id)[0]
    representation_id = str(uuid4())

    with pytest.raises(RawRepresentationIdentityMismatchError):
        register_raw_representation(
            record_id=record.id,
            ciphertext=mismatched_ciphertext,
            nonce=mismatched_nonce,
            key_ref="test-key-v1",
            key=_KEY,
            representation_id=representation_id,
            activate=True,
        )

    # Registration and activation are one fail-closed transition: the bad
    # representation was not admitted, the original remains active, and no
    # read receipt can imply that mismatched bytes were served.
    assert all_raw_representations(record.id) == [original]
    assert original.active is True
    assert all_raw_read_receipts() == []

    corrected_ciphertext, corrected_nonce = encrypt_raw_bytes(
        b"identity-bound-copy", key=_KEY
    )
    corrected, created = register_raw_representation(
        record_id=record.id,
        ciphertext=corrected_ciphertext,
        nonce=corrected_nonce,
        key_ref="test-key-v1",
        key=_KEY,
        representation_id=representation_id,
        activate=True,
    )
    assert created is True and corrected.active is True
    replay, replay_created = register_raw_representation(
        record_id=record.id,
        ciphertext=corrected_ciphertext,
        nonce=corrected_nonce,
        key_ref="test-key-v1",
        key=_KEY,
        representation_id=representation_id,
        activate=True,
    )
    assert replay_created is False and replay == corrected
    assert sum(item.active for item in all_raw_representations(record.id)) == 1
    assert read_raw_record(
        raw_ref_for(record),
        reader="authorized-reader",
        purpose="identity-bound retry",
        key=_KEY,
    ).plaintext == b"identity-bound-copy"


def test_activation_and_read_refuse_identity_mismatch_without_receipt() -> None:
    record = _insert(b"active-identity-copy")
    original = all_raw_representations(record.id)[0]
    candidate_ciphertext, candidate_nonce = encrypt_raw_bytes(
        b"active-identity-copy", key=_KEY
    )
    candidate, created = register_raw_representation(
        record_id=record.id,
        ciphertext=candidate_ciphertext,
        nonce=candidate_nonce,
        key_ref="test-key-v1",
        key=_KEY,
    )
    assert created is True and candidate.active is False

    mismatched_ciphertext, mismatched_nonce = encrypt_raw_bytes(
        b"different-plaintext", key=_KEY
    )
    raw_store._MEMORY_STORE._representations[candidate.id] = replace(
        candidate,
        ciphertext=mismatched_ciphertext,
        nonce=mismatched_nonce,
    )
    with pytest.raises(RawRepresentationIdentityMismatchError):
        activate_raw_representation(record.id, candidate.id, key=_KEY)

    representations = all_raw_representations(record.id)
    assert next(item for item in representations if item.id == original.id).active is True
    assert next(item for item in representations if item.id == candidate.id).active is False
    assert all_raw_read_receipts() == []

    # A malformed active row is an impossible state through production APIs,
    # but the read gate still fails closed if storage is corrupted underneath
    # it: no plaintext and no provenance receipt are emitted.
    raw_store._MEMORY_STORE._representations[original.id] = replace(
        original,
        ciphertext=mismatched_ciphertext,
        nonce=mismatched_nonce,
    )
    with pytest.raises(RawReadRefusedError, match="content identity"):
        read_raw_record(
            raw_ref_for(record),
            reader="authorized-reader",
            purpose="corrupt active representation",
            key=_KEY,
        )
    assert all_raw_read_receipts() == []

    # Repair is resumable: restoring valid registered bytes allows activation
    # and the production read path emits its first receipt only on success.
    raw_store._MEMORY_STORE._representations[original.id] = original
    raw_store._MEMORY_STORE._representations[candidate.id] = candidate
    activated = activate_raw_representation(record.id, candidate.id, key=_KEY)
    assert activated.active is True
    result = read_raw_record(
        raw_ref_for(record),
        reader="authorized-reader",
        purpose="identity-bound recovery",
        key=_KEY,
    )
    assert result.plaintext == b"active-identity-copy"
    assert all_raw_read_receipts() == [result.receipt]


def test_all_copy_deletion_is_required_before_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = _retention_vault(tmp_path)
    record = _insert()
    ciphertext, nonce = encrypt_raw_bytes(b"raw-evidence", key=_KEY)
    register_raw_representation(
        record_id=record.id,
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="test-key-v1",
        key=_KEY,
    )
    assert len(all_raw_representations(record.id)) == 2

    real_delete = raw_store._MEMORY_STORE._delete_representation_locked
    calls = 0

    def _fail_second_delete(representation_id: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected representation deletion failure")
        real_delete(representation_id)

    monkeypatch.setattr(raw_store._MEMORY_STORE, "_delete_representation_locked", _fail_second_delete)
    with pytest.raises(RawRepresentationDeletionError):
        enforce_hard_retention_bound(
            vault_root=vault_root,
            now=datetime.now(timezone.utc) + timedelta(days=2),
        )

    # The all-copy deletion is atomic: no success receipt and no partial
    # representation loss. This same primitive is the revocation seam.
    assert len(all_raw_representations(record.id)) == 2
    assert record.id in {row.id for row in all_raw_records()}
    assert all_deletion_receipts() == []

    monkeypatch.setattr(raw_store._MEMORY_STORE, "_delete_representation_locked", real_delete)
    result = enforce_hard_retention_bound(
        vault_root=vault_root,
        now=datetime.now(timezone.utc) + timedelta(days=2),
    )
    assert result.deleted_count == 1
    assert all_raw_representations(record.id) == []
    assert all(row.id != record.id for row in all_raw_records())
    assert [receipt.record_id for receipt in all_deletion_receipts()] == [record.id]


def test_legacy_hot_records_remain_readable_during_migration() -> None:
    """The runtime half mirrors the transactional Postgres backfill proof.

    Every producer now lands identity plus its initial registered hot
    representation atomically. Replaying the migration-owned deterministic
    registration is harmless and never fabricates a cold locator.
    """
    record = _insert(b"legacy-hot-copy")
    representations = all_raw_representations(record.id)
    assert len(representations) == 1
    hot = representations[0]
    assert hot.storage_kind == "postgres_hot"
    assert hot.location_ref.startswith("heimloc:")
    assert "cold" not in hot.location_ref

    replay, created = register_raw_representation(
        record_id=record.id,
        ciphertext=hot.ciphertext,
        nonce=hot.nonce,
        key_ref=hot.key_ref,
        key=_KEY,
        representation_id=hot.id,
        activate=True,
    )
    assert replay == hot
    assert created is False
    assert read_raw_record(
        raw_ref_for(record),
        reader="authorized-reader",
        purpose="legacy backfill continuity",
        key=_KEY,
    ).plaintext == b"legacy-hot-copy"
