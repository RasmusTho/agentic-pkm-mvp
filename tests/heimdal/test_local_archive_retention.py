"""HAR-05: gated restore and all-copy expiry for the local archive."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
import threading

import pytest

from app.heimdal import (
    consent_ledger,
    local_archive,
    media_ingress,
    media_receipts,
    raw_liveness,
    raw_store,
    retention,
)
from app.heimdal import raw_read_gate
from app.heimdal.consent_ledger import (
    grant_consent,
    reset_memory_consent_ledger,
    resolve_active_grant,
    revoke_consent,
)
from app.heimdal.raw_read_gate import (
    RawReadRefusedError,
    all_raw_read_receipts,
    raw_ref_for,
    read_raw_record,
    reset_memory_raw_read_receipts,
)
from app.heimdal.settings_notes import (
    SETTINGS,
    SettingsNote,
    read_settings_note,
    write_settings_note,
)
from app.ops.heimdal_cold_volume import _ARCHIVE_VOLUME_READY_ISSUER, _issue_archive_volume_ready
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg

_KEY = bytes.fromhex(secrets.token_hex(32))
_ARCHIVE_REF = "har05-test-archive"
_READER = "har05-restore-drill"


@pytest.fixture(autouse=True)
def _memory_runtime(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", _READER)
    raw_store.reset_memory_raw_store()
    reset_memory_raw_read_receipts()
    raw_liveness.reset_memory_deletion_receipts()
    reset_memory_consent_ledger()
    media_receipts.reset_memory_media_receipts()
    yield
    raw_store.reset_memory_raw_store()
    reset_memory_raw_read_receipts()
    raw_liveness.reset_memory_deletion_receipts()
    reset_memory_consent_ledger()
    media_receipts.reset_memory_media_receipts()


def _volume_ready(archive_root: Path):
    return _issue_archive_volume_ready(
        _ARCHIVE_REF,
        archive_root,
        _issuer=_ARCHIVE_VOLUME_READY_ISSUER,
    )


def _insert(plaintext: bytes, *, grant_ref: str, modality: str | None = None):
    ciphertext, nonce = raw_store.encrypt_raw_bytes(plaintext, key=_KEY)
    record, created = raw_store.insert_raw_record(
        content_identity=raw_store.compute_raw_content_identity(plaintext),
        capture_chain=["registered-sensor", "heimdal"],
        sensor={"sensor_id": "registered-sensor"},
        consent={"grant_ref": grant_ref},
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="test-key-v1",
        key=_KEY,
        source_path="source-class-redacted",
        payload={"modality": modality} if modality is not None else None,
    )
    assert created
    return record


def _age_record(record, *, now: datetime):
    store = raw_store._MEMORY_STORE  # noqa: SLF001
    with store._lock:  # noqa: SLF001
        current = next(row for row in store._rows if row.id == record.id)  # noqa: SLF001
        aged = replace(current, ingested_at=now - timedelta(days=8))
        store._rows = [aged if row.id == record.id else row for row in store._rows]  # noqa: SLF001
        store._by_identity[aged.content_identity] = aged  # noqa: SLF001
    resolved = raw_store.resolve_active_raw_record(record.id)
    assert resolved is not None
    return resolved


def _archive(record, *, archive_root: Path, now: datetime):
    return local_archive.relocate_raw_record(
        record,
        archive_root=archive_root,
        archive_ref=_ARCHIVE_REF,
        now=now,
        retention_window_days=30,
        key=_KEY,
        volume_ready=lambda: _volume_ready(archive_root),
    )


def _write_retention_window(vault_root: Path, *, days: int) -> None:
    vault_root.mkdir(parents=True, exist_ok=True)
    write_settings_note(
        vault_root,
        SettingsNote(spec=SETTINGS, values={"retention_window_days": days}),
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )


def _write_screen_retention_window(vault_root: Path, *, minutes: int) -> None:
    vault_root.mkdir(parents=True, exist_ok=True)
    write_settings_note(
        vault_root,
        SettingsNote(
            spec=SETTINGS,
            values={
                "retention_window_days": 30,
                "screen_frame_retention_minutes": minutes,
            },
        ),
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )


@pytest.mark.parametrize("revoked_grant", ["grant-a", "grant-b"])
def test_identical_bytes_preserve_every_grant_and_either_revocation_erases(
    revoked_grant: str,
) -> None:
    plaintext = b"one raw identity admitted under two independent grants"
    first = _insert(plaintext, grant_ref="grant-a")
    replay_ciphertext, replay_nonce = raw_store.encrypt_raw_bytes(plaintext, key=_KEY)

    replay, created = raw_store.insert_raw_record(
        content_identity=raw_store.compute_raw_content_identity(plaintext),
        capture_chain=["registered-sensor", "heimdal"],
        sensor={"sensor_id": "registered-sensor"},
        consent={"grant_ref": "grant-b"},
        ciphertext=replay_ciphertext,
        nonce=replay_nonce,
        key_ref="test-key-v1",
        key=_KEY,
        source_path="source-class-redacted",
    )

    assert created is False
    assert replay.id == first.id
    assert raw_store.raw_record_ids_by_consent_grant("grant-a") == [first.id]
    assert raw_store.raw_record_ids_by_consent_grant("grant-b") == [first.id]

    result = retention.enforce_consent_revocation(
        grant_ref=revoked_grant,
        revoked_at=datetime.now(timezone.utc),
    )

    assert result.deleted_count == 1
    assert raw_store.resolve_active_raw_record(first.id) is None
    assert raw_store.all_raw_representations(first.id) == []
    receipt = result.deletions[0]
    assert receipt.payload[raw_liveness.CONSENT_GRANT_DIGEST_PAYLOAD_KEY] == (
        raw_liveness.consent_grant_digest(revoked_grant)
    )
    assert set(receipt.payload[raw_liveness.CONSENT_GRANT_DIGESTS_PAYLOAD_KEY]) == {
        raw_liveness.consent_grant_digest("grant-a"),
        raw_liveness.consent_grant_digest("grant-b"),
    }


def test_retirement_claim_refuses_reads_writers_and_freshness_until_drained(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc)
    enforcement_time = now + timedelta(days=31)
    vault_root = tmp_path / "vault"
    _write_retention_window(vault_root, days=30)
    record = _age_record(_insert(b"retirement fence", grant_ref="grant-retiring"), now=now)
    lease = raw_liveness.issue_response_lease(
        raw_ref=raw_ref_for(record),
        content_identity=record.content_identity,
        now=enforcement_time,
    )

    with pytest.raises(retention.RetentionErasurePendingError, match="draining"):
        retention.enforce_hard_retention_bound(
            vault_root=vault_root,
            now=enforcement_time,
        )

    with pytest.raises(RawReadRefusedError, match="retiring"):
        read_raw_record(
            raw_ref_for(record),
            reader=_READER,
            purpose="must stop after retirement claim",
            key=_KEY,
        )
    with pytest.raises(raw_liveness.RawLivenessUnavailableError, match="retiring"):
        raw_liveness.issue_response_lease(
            raw_ref=raw_ref_for(record),
            content_identity=record.content_identity,
            now=enforcement_time,
        )
    replacement_ciphertext, replacement_nonce = raw_store.encrypt_raw_bytes(
        b"retirement fence",
        key=_KEY,
    )
    with pytest.raises(raw_liveness.RawLivenessUnavailableError, match="retiring"):
        raw_store.register_raw_representation(
            record_id=record.id,
            ciphertext=replacement_ciphertext,
            nonce=replacement_nonce,
            key_ref="test-key-v1",
            key=_KEY,
            activate=False,
        )
    with pytest.raises(raw_liveness.RawLivenessUnavailableError, match="retiring"):
        raw_store.activate_raw_representation(record.id, record.id, key=_KEY)
    settings = read_settings_note(vault_root, SETTINGS)
    assert settings is not None
    assert "last_enforced_at" not in settings.values
    assert raw_liveness.all_deletion_receipts() == []

    completed = retention.enforce_hard_retention_bound(
        vault_root=vault_root,
        now=lease.expires_at + timedelta(microseconds=1),
    )
    assert completed.deleted_count == 1
    settings = read_settings_note(vault_root, SETTINGS)
    assert settings is not None and settings.values["last_enforced_at"]


def test_terminal_archive_replay_refuses_retiring_generation(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    enforcement_time = now + timedelta(days=31)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    vault_root = tmp_path / "vault"
    _write_retention_window(vault_root, days=30)
    record = _age_record(
        _insert(b"terminal replay retirement fence", grant_ref="grant-replay-retiring"),
        now=now,
    )
    archived = _archive(record, archive_root=archive_root, now=now)
    lease = raw_liveness.issue_response_lease(
        raw_ref=raw_ref_for(record),
        content_identity=record.content_identity,
        now=enforcement_time,
    )
    with pytest.raises(retention.RetentionErasurePendingError, match="draining"):
        retention.enforce_hard_retention_bound(
            vault_root=vault_root,
            now=enforcement_time,
            record_last_enforced=False,
        )

    with pytest.raises(local_archive.ArchiveDegradedError) as error:
        local_archive.relocate_raw_record(
            record,
            archive_root=archive_root,
            archive_ref=_ARCHIVE_REF,
            now=now,
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: _volume_ready(archive_root),
    )
    assert error.value.reason == "archive_relocation_failed"
    assert next(
        row for row in raw_store.all_raw_representations(record.id) if row.active
    ) == archived.active_representation

    retention.enforce_hard_retention_bound(
        vault_root=vault_root,
        now=lease.expires_at + timedelta(microseconds=1),
        record_last_enforced=False,
    )


def test_screen_retention_live_lease_is_pending_not_receipted(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    vault_root = tmp_path / "vault"
    _write_screen_retention_window(vault_root, minutes=1)
    record = _age_record(
        _insert(
            b"screen retention lease",
            grant_ref="grant-screen-lease",
            modality="screen",
        ),
        now=now,
    )
    lease = raw_liveness.issue_response_lease(
        raw_ref=raw_ref_for(record),
        content_identity=record.content_identity,
        now=now,
    )

    with pytest.raises(retention.RetentionErasurePendingError, match="drain|lease"):
        retention.enforce_screen_frame_retention(vault_root=vault_root, now=now)

    assert raw_store.resolve_active_raw_record(record.id) is not None
    assert raw_liveness.all_deletion_receipts() == []
    completed = retention.enforce_screen_frame_retention(
        vault_root=vault_root,
        now=lease.expires_at + timedelta(microseconds=1),
    )
    assert completed.deleted_count == 1


def test_screen_retention_unmounted_selection_and_queued_cleanup_are_loud(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    vault_root = tmp_path / "vault"
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    _write_screen_retention_window(vault_root, minutes=1)
    record = _age_record(
        _insert(
            b"screen retention cold retry",
            grant_ref="grant-screen-cold",
            modality="screen",
        ),
        now=now,
    )
    _archive(record, archive_root=archive_root, now=now)
    monkeypatch.setattr(
        raw_store,
        "_resolve_cold_ciphertext",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("screen retention discovery resolved cold ciphertext")
        ),
    )
    raw_store.revoke_cold_archive_binding()

    with pytest.raises(raw_store.RawRepresentationDeletionError, match="binding"):
        retention.enforce_screen_frame_retention(vault_root=vault_root, now=now)

    assert raw_store.raw_record_ids_by_consent_grant("grant-screen-cold") == []
    pending = raw_liveness.all_deletion_receipts()[0]
    assert pending.reason == retention.REASON_SCREEN_FRAME_RETENTION_BUFFER
    assert pending.payload["cold_cleanup_location_refs"]

    # Restart-like retry has no active identity to discover. The durable queue
    # remains authority and must still prevent a successful screen receipt.
    with pytest.raises(raw_store.RawRepresentationDeletionError, match="binding"):
        retention.enforce_screen_frame_retention(vault_root=vault_root, now=now)


def test_screen_retry_finds_cross_reason_pending_receipt_by_modality(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc)
    vault_root = tmp_path / "vault"
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    vault_root.mkdir()
    write_settings_note(
        vault_root,
        SettingsNote(
            spec=SETTINGS,
            values={
                "retention_window_days": 1,
                "screen_frame_retention_minutes": 1,
            },
        ),
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    record = _age_record(
        _insert(
            b"screen cleanup created by hard retention",
            grant_ref="grant-screen-cross-reason",
            modality="screen",
        ),
        now=now,
    )
    _archive(record, archive_root=archive_root, now=now)
    raw_store.revoke_cold_archive_binding()

    with pytest.raises(raw_store.RawRepresentationDeletionError, match="binding"):
        retention.enforce_hard_retention_bound(
            vault_root=vault_root,
            now=now,
            record_last_enforced=False,
        )

    pending = raw_liveness.all_deletion_receipts()[0]
    assert pending.reason == retention.REASON_HARD_RETENTION_BOUND
    assert pending.payload.get("raw_modality") == "screen"
    assert pending.payload["cold_cleanup_location_refs"]

    with pytest.raises(raw_store.RawRepresentationDeletionError, match="binding"):
        retention.enforce_screen_frame_retention(vault_root=vault_root, now=now)

    proof = _volume_ready(archive_root)
    raw_store.configure_cold_archive_root(
        archive_root,
        verified_volume=proof,
        expected_archive_ref=_ARCHIVE_REF,
    )
    converged = retention.enforce_screen_frame_retention(
        vault_root=vault_root,
        now=now,
    )
    assert converged.deleted_count == 0
    assert raw_liveness.all_deletion_receipts()[0].payload[
        "cold_cleanup_location_refs"
    ] == []


def test_screen_retry_refuses_unclassified_historical_pending_receipt(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc)
    vault_root = tmp_path / "vault"
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    _write_screen_retention_window(vault_root, minutes=1)
    record = _age_record(
        _insert(
            b"historical unclassified screen cleanup",
            grant_ref="grant-screen-unclassified",
            modality="screen",
        ),
        now=now,
    )
    _archive(record, archive_root=archive_root, now=now)
    raw_store.revoke_cold_archive_binding()
    with pytest.raises(raw_store.RawRepresentationDeletionError, match="binding"):
        retention.enforce_screen_frame_retention(vault_root=vault_root, now=now)

    with raw_liveness.memory_fence():
        raw_liveness._MEMORY.deletion_receipts[0].payload.pop(  # noqa: SLF001
            raw_liveness.RAW_MODALITY_PAYLOAD_KEY
        )

    with pytest.raises(
        raw_liveness.RawLivenessUnavailableError,
        match="modality classification",
    ):
        retention.enforce_screen_frame_retention(vault_root=vault_root, now=now)


def test_unmounted_cold_expiry_selects_metadata_and_leaves_retry_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    vault_root = tmp_path / "vault"
    _write_retention_window(vault_root, days=30)
    record = _age_record(_insert(b"metadata-only expiry", grant_ref="grant-expiry"), now=now)
    _archive(record, archive_root=archive_root, now=now)

    monkeypatch.setattr(
        raw_store,
        "_resolve_cold_ciphertext",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("expiry discovery resolved cold ciphertext")
        ),
    )
    raw_store.revoke_cold_archive_binding()
    with pytest.raises(raw_store.RawRepresentationDeletionError, match="binding"):
        retention.enforce_hard_retention_bound(
            vault_root=vault_root,
            now=now + timedelta(days=31),
            record_last_enforced=False,
        )

    assert raw_store.raw_record_ids_by_consent_grant("grant-expiry") == []
    pending = raw_liveness.all_deletion_receipts()[0]
    assert pending.payload["cold_cleanup_location_refs"]
    assert pending.payload["cold_cleanup_archive_bindings"]

    proof = _volume_ready(archive_root)
    raw_store.configure_cold_archive_root(
        archive_root,
        verified_volume=proof,
        expected_archive_ref=_ARCHIVE_REF,
    )
    retention.enforce_hard_retention_bound(
        vault_root=vault_root,
        now=now + timedelta(days=31),
        record_last_enforced=False,
    )
    assert raw_liveness.all_deletion_receipts()[0].payload[
        "cold_cleanup_location_refs"
    ] == []


def test_pending_cleanup_never_retargets_same_identity_new_archive_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    archive_a = tmp_path / "archive-a"
    archive_b = tmp_path / "archive-b"
    archive_a.mkdir()
    archive_b.mkdir()
    record = _age_record(_insert(b"generation-bound cleanup", grant_ref="grant-binding"), now=now)
    archived = _archive(record, archive_root=archive_a, now=now)
    representation_id = archived.active_representation.id
    original_delete = raw_store._delete_cold_object_path  # noqa: SLF001
    monkeypatch.setattr(
        raw_store,
        "_delete_cold_object_path",
        lambda _path: (_ for _ in ()).throw(
            raw_store.RawRepresentationDeletionError("leave cleanup pending")
        ),
    )
    with pytest.raises(raw_store.RawRepresentationDeletionError):
        raw_liveness.governed_delete_raw_record(
            record_id=record.id,
            reason=retention.REASON_HARD_RETENTION_BOUND,
            retention_window_days=30,
            deleted_at=now,
        )

    monkeypatch.setattr(raw_store, "_delete_cold_object_path", original_delete)
    proof_b = _volume_ready(archive_b)
    raw_store.configure_cold_archive_root(
        archive_b,
        verified_volume=proof_b,
        expected_archive_ref=_ARCHIVE_REF,
    )
    (archive_b / "representations").mkdir()
    (archive_b / "manifests").mkdir()
    decoy_object = archive_b / "representations" / f"{representation_id}.bin"
    decoy_manifest = archive_b / "manifests" / f"{representation_id}.json"
    decoy_object.write_bytes(b"must-not-delete")
    decoy_manifest.write_text("{}", encoding="utf-8")

    with pytest.raises(raw_store.RawRepresentationDeletionError, match="binding"):
        raw_liveness.governed_delete_raw_record(
            record_id=record.id,
            reason=retention.REASON_HARD_RETENTION_BOUND,
            retention_window_days=30,
            deleted_at=now,
        )
    assert decoy_object.read_bytes() == b"must-not-delete"
    assert decoy_manifest.exists()

    proof_a = _volume_ready(archive_a)
    raw_store.configure_cold_archive_root(
        archive_a,
        verified_volume=proof_a,
        expected_archive_ref=_ARCHIVE_REF,
    )
    assert raw_liveness.governed_delete_raw_record(
        record_id=record.id,
        reason=retention.REASON_HARD_RETENTION_BOUND,
        retention_window_days=30,
        deleted_at=now,
    ).outcome == "already_erased"
    assert raw_liveness.all_deletion_receipts()[0].payload[
        "cold_cleanup_location_refs"
    ] == []


def test_pending_cleanup_refuses_same_archive_new_raw_generation_manifest_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    plaintext = b"same archive newer raw generation"
    original = _age_record(
        _insert(plaintext, grant_ref="grant-generation-one"),
        now=now,
    )
    archived = _archive(original, archive_root=archive_root, now=now)
    representation_id = archived.active_representation.id
    location_ref = archived.active_representation.location_ref
    object_path = archive_root / "representations" / f"{representation_id}.bin"
    manifest_path = archive_root / "manifests" / f"{representation_id}.json"
    original_delete = raw_store._delete_cold_object_path  # noqa: SLF001
    monkeypatch.setattr(
        raw_store,
        "_delete_cold_object_path",
        lambda _path: (_ for _ in ()).throw(
            raw_store.RawRepresentationDeletionError("leave generation one cleanup pending")
        ),
    )
    with pytest.raises(raw_store.RawRepresentationDeletionError):
        raw_liveness.governed_delete_raw_record(
            record_id=original.id,
            reason=retention.REASON_HARD_RETENTION_BOUND,
            retention_window_days=30,
            deleted_at=now,
        )

    newer = _insert(plaintext, grant_ref="grant-generation-two")
    with raw_liveness.memory_fence():
        newer_generation = raw_liveness._MEMORY.generations_by_record[newer.id].generation  # noqa: SLF001
    assert newer_generation == archived.active_representation.raw_generation + 1
    newer_bytes = b"newer-generation-object-must-survive"
    object_path.write_bytes(newer_bytes)
    manifest_path.write_text(
        json.dumps(
            {
                "schema": local_archive.ARCHIVE_SCHEMA,
                "record_id": newer.id,
                "content_identity": newer.content_identity,
                "representation_id": representation_id,
                "location_ref": location_ref,
                "archive_token": archived.active_representation.archive_token,
                "archive_generation": archived.active_representation.archive_generation,
                "raw_generation": newer_generation,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
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

    assert object_path.read_bytes() == newer_bytes
    assert manifest_path.exists()


def test_archived_read_reuses_gated_read_path(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    record = _age_record(_insert(b"gated archived evidence", grant_ref="grant-read"), now=now)
    _archive(record, archive_root=archive_root, now=now)

    with pytest.raises(RawReadRefusedError):
        read_raw_record(
            raw_ref_for(record),
            reader="unauthorized-reader",
            purpose="must remain refused",
            key=_KEY,
        )
    assert all_raw_read_receipts() == []

    authorized = read_raw_record(
        raw_ref_for(record),
        reader=_READER,
        purpose="HAR-05 archived read",
        key=_KEY,
    )

    assert authorized.plaintext == b"gated archived evidence"
    assert authorized.receipt.raw_ref == raw_ref_for(record)
    assert authorized.receipt.content_identity == record.content_identity
    assert len(all_raw_read_receipts()) == 1


def test_cold_read_never_acquires_archive_lock_while_binding_lock_is_held(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    record = _age_record(
        _insert(b"cold-read-lock-order", grant_ref="grant-read-lock-order"),
        now=now,
    )
    _archive(record, archive_root=archive_root, now=now)
    original_archive_lock = raw_store._cold_archive_mutation_lock  # noqa: SLF001
    acquisitions: list[Path] = []

    def assert_canonical_lock_order(archive: Path, *, blocking: bool):
        assert not raw_store._COLD_BINDING_LOCK._is_owned()  # noqa: SLF001
        acquisitions.append(archive)
        return original_archive_lock(archive, blocking=blocking)

    monkeypatch.setattr(
        raw_store,
        "_cold_archive_mutation_lock",
        assert_canonical_lock_order,
    )

    resolved = raw_store.resolve_active_raw_record(record.id)

    assert resolved is not None
    assert resolved.ciphertext
    assert acquisitions == [archive_root]


def test_cross_identity_cold_read_and_relocation_revalidate_without_lock_cycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    read_record = _age_record(
        _insert(b"cross-identity-cold-read", grant_ref="grant-cross-read"),
        now=now,
    )
    archived_read = _archive(read_record, archive_root=archive_root, now=now)
    relocation_record = _age_record(
        _insert(b"cross-identity-relocation", grant_ref="grant-cross-relocation"),
        now=now,
    )
    read_snapshotted = threading.Event()
    relocation_locked = threading.Event()
    reader_advancing = threading.Event()

    def coordinate_read(stage: str, location_ref: str) -> None:
        if (
            stage != "after_binding_snapshot"
            or location_ref != archived_read.active_representation.location_ref
        ):
            return
        read_snapshotted.set()
        assert relocation_locked.wait(timeout=10)
        reader_advancing.set()

    def coordinate_relocation(stage: str) -> None:
        if stage != "after_archive_lock":
            return
        relocation_locked.set()
        assert reader_advancing.wait(timeout=10)

    monkeypatch.setattr(raw_store, "_cold_read_stage_hook", coordinate_read)
    monkeypatch.setattr(local_archive, "_relocation_stage_hook", coordinate_relocation)

    def read_from_snapshot() -> str:
        try:
            raw_store.resolve_active_raw_record(read_record.id)
        except raw_store.RawRepresentationUnavailableError:
            return "stale_snapshot_refused"
        return "read_completed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        read_future = executor.submit(read_from_snapshot)
        assert read_snapshotted.wait(timeout=10)
        relocation_future = executor.submit(
            _archive,
            relocation_record,
            archive_root=archive_root,
            now=now,
        )
        assert read_future.result(timeout=10) == "stale_snapshot_refused"
        relocated = relocation_future.result(timeout=10)

    assert relocated.active_representation.storage_kind == local_archive.ARCHIVE_STORAGE_KIND
    retried = raw_store.resolve_active_raw_record(read_record.id)
    assert retried is not None and retried.ciphertext


@pytest.mark.parametrize("ownership_state", ["missing", None, "reserved", "unknown"])
def test_cold_read_requires_exact_verified_manifest_state(
    tmp_path: Path,
    ownership_state: str | None,
) -> None:
    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    record = _age_record(
        _insert(
            f"cold-read-state-{ownership_state}".encode(),
            grant_ref=f"grant-read-state-{ownership_state}",
        ),
        now=now,
    )
    archived = _archive(record, archive_root=archive_root, now=now)
    manifest_path = archive_root / "manifests" / f"{archived.receipt.representation_id}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if ownership_state == "missing":
        manifest.pop("ownership_state")
    else:
        manifest["ownership_state"] = ownership_state
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(
        raw_store.RawRepresentationUnavailableError,
        match="cold representation bytes are unavailable",
    ):
        raw_store.resolve_active_raw_record(record.id)


@pytest.mark.parametrize("ownership_state", ["missing", None, "unknown"])
def test_cold_cleanup_rejects_unclassified_manifest_state(
    tmp_path: Path,
    ownership_state: str | None,
) -> None:
    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    record = _age_record(
        _insert(
            f"cold-cleanup-state-{ownership_state}".encode(),
            grant_ref=f"grant-cleanup-state-{ownership_state}",
        ),
        now=now,
    )
    archived = _archive(record, archive_root=archive_root, now=now)
    object_path = archive_root / "representations" / f"{archived.receipt.representation_id}.bin"
    manifest_path = archive_root / "manifests" / f"{archived.receipt.representation_id}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if ownership_state == "missing":
        manifest.pop("ownership_state")
    else:
        manifest["ownership_state"] = ownership_state
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(raw_store.RawRepresentationDeletionError, match="manifest ownership"):
        raw_liveness.governed_delete_raw_record(
            record_id=record.id,
            reason=retention.REASON_HARD_RETENTION_BOUND,
            retention_window_days=30,
            deleted_at=now,
        )

    assert object_path.exists()
    assert manifest_path.exists()
    assert raw_liveness.all_deletion_receipts()[0].payload["cold_cleanup_location_refs"]


def test_reserved_manifest_refuses_activation_but_authorizes_exact_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    record = _age_record(
        _insert(b"reserved-activation-boundary", grant_ref="grant-reserved-activation"),
        now=now,
    )
    monkeypatch.setattr(
        local_archive,
        "_manifest_payload",
        local_archive._reserved_ownership_manifest_payload,  # noqa: SLF001
    )

    with pytest.raises(local_archive.ArchiveDegradedError, match="archive_relocation_failed"):
        _archive(record, archive_root=archive_root, now=now)

    representations = raw_store.all_raw_representations(record.id)
    hot = next(item for item in representations if item.storage_kind == "postgres_hot")
    reserved = next(
        item for item in representations if item.storage_kind == local_archive.ARCHIVE_STORAGE_KIND
    )
    manifest_path = archive_root / "manifests" / f"{reserved.id}.json"
    object_path = archive_root / "representations" / f"{reserved.id}.bin"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["ownership_state"] == "reserved"
    assert hot.active is True and reserved.active is False

    deleted = raw_liveness.governed_delete_raw_record(
        record_id=record.id,
        reason=retention.REASON_HARD_RETENTION_BOUND,
        retention_window_days=30,
        deleted_at=now,
    )

    assert deleted.outcome == "deleted"
    assert not object_path.exists()
    assert not manifest_path.exists()


@pytest.mark.parametrize(
    "crash_stage",
    [
        "after_object_unlink",
        "after_object_directory_fsync",
        "after_manifest_unlink",
        "after_manifest_directory_fsync",
    ],
)
def test_cold_cleanup_crash_cuts_restart_idempotently_before_queue_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_stage: str,
) -> None:
    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    record = _age_record(
        _insert(
            f"cold-cleanup-crash-{crash_stage}".encode(),
            grant_ref=f"grant-cleanup-crash-{crash_stage}",
        ),
        now=now,
    )
    archived = _archive(record, archive_root=archive_root, now=now)
    object_path = archive_root / "representations" / f"{archived.receipt.representation_id}.bin"
    manifest_path = archive_root / "manifests" / f"{archived.receipt.representation_id}.json"
    stages: list[str] = []

    def crash_at_cut(stage: str, _path: Path) -> None:
        stages.append(stage)
        if stage == crash_stage:
            raise raw_store.RawRepresentationDeletionError(f"crash cut {stage}")

    monkeypatch.setattr(raw_store, "_cold_delete_stage_hook", crash_at_cut)
    with pytest.raises(raw_store.RawRepresentationDeletionError, match="crash cut"):
        raw_liveness.governed_delete_raw_record(
            record_id=record.id,
            reason=retention.REASON_HARD_RETENTION_BOUND,
            retention_window_days=30,
            deleted_at=now,
        )

    pending = raw_liveness.all_deletion_receipts()[0]
    assert pending.payload["cold_cleanup_location_refs"]
    assert crash_stage in stages
    assert not object_path.exists()
    assert manifest_path.exists() is (
        crash_stage in {"after_object_unlink", "after_object_directory_fsync"}
    )

    raw_store.revoke_cold_archive_binding()
    proof = _volume_ready(archive_root)
    raw_store.configure_cold_archive_root(
        archive_root,
        verified_volume=proof,
        expected_archive_ref=_ARCHIVE_REF,
    )
    monkeypatch.setattr(raw_store, "_cold_delete_stage_hook", lambda _stage, _path: None)
    retried = raw_liveness.governed_delete_raw_record(
        record_id=record.id,
        reason=retention.REASON_HARD_RETENTION_BOUND,
        retention_window_days=30,
        deleted_at=now,
    )

    assert retried.outcome == "already_erased"
    assert raw_liveness.all_deletion_receipts()[0].payload[
        "cold_cleanup_location_refs"
    ] == []
    assert not object_path.exists()
    assert not manifest_path.exists()


def test_restore_drill_proves_archived_identity(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    plaintext = b"restore drill bytes stay out of receipts"
    record = _age_record(_insert(plaintext, grant_ref="grant-restore"), now=now)
    _archive(record, archive_root=archive_root, now=now)

    receipt = local_archive.run_restore_drill(
        raw_ref_for(record),
        reader=_READER,
        key=_KEY,
    )

    assert receipt.proven is True
    assert receipt.content_identity == raw_store.compute_raw_content_identity(plaintext)
    assert receipt.raw_ref == raw_ref_for(record)
    assert receipt.storage_kind == local_archive.ARCHIVE_STORAGE_KIND
    encoded = json.dumps(receipt.as_dict(), sort_keys=True)
    assert plaintext.decode() not in encoded
    assert str(tmp_path) not in encoded
    assert record.source_path not in encoded


def test_restore_then_delete_all_raw_copies(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    vault_root = tmp_path / "vault"
    _write_retention_window(vault_root, days=30)

    retention_record = _age_record(
        _insert(b"expires by retention", grant_ref="grant-retention"), now=now
    )
    revoked_record = _age_record(
        _insert(b"expires by revocation", grant_ref="grant-revoked"), now=now
    )
    grant_consent(
        grant_ref="grant-revoked",
        basis="session_optin",
        scope="session:har05",
        granted_by="operator",
    )
    _archive(retention_record, archive_root=archive_root, now=now)
    _archive(revoked_record, archive_root=archive_root, now=now)
    local_archive.run_restore_drill(raw_ref_for(retention_record), reader=_READER, key=_KEY)

    revoke_consent(grant_ref="grant-revoked", revoked_by="operator")
    retention_receipt = retention.enforce_hard_retention_bound(
        vault_root=vault_root,
        now=now + timedelta(days=31),
        record_last_enforced=False,
    )

    assert retention_receipt.retention_window_days == 30
    assert retention_receipt.deleted_count == 1
    assert resolve_active_grant(scope="session:har05") is None
    assert raw_store.all_raw_records() == []
    assert raw_store.all_raw_representations(retention_record.id) == []
    assert raw_store.all_raw_representations(revoked_record.id) == []
    assert list((archive_root / "representations").glob("*.bin")) == []
    assert list((archive_root / "manifests").glob("*.json")) == []
    receipts = raw_liveness.all_deletion_receipts()
    assert {item.reason for item in receipts} == {
        retention.REASON_CONSENT_REVOKED,
        retention.REASON_HARD_RETENTION_BOUND,
    }
    assert all(item.payload.get("cold_cleanup_location_refs") == [] for item in receipts)


def test_cold_delete_failure_is_loud_and_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    grant_ref = "grant-retry"
    record = _age_record(_insert(b"retry cold deletion", grant_ref=grant_ref), now=now)
    grant_consent(
        grant_ref=grant_ref,
        basis="session_optin",
        scope="session:retry",
        granted_by="operator",
    )
    _archive(record, archive_root=archive_root, now=now)
    capture_id = "har05-cold-delete-retry"
    media_receipt, created = media_receipts.append_media_receipt(
        capture_id=capture_id,
        content_sha256=record.content_identity,
        raw_ref=raw_ref_for(record),
        kind="audio",
        lane="media_ingress",
    )
    assert created
    original_delete = raw_store._delete_cold_object_path  # noqa: SLF001

    def fail_delete(_path: Path) -> None:
        raise raw_store.RawRepresentationDeletionError("simulated cold delete failure")

    monkeypatch.setattr(raw_store, "_delete_cold_object_path", fail_delete)
    with pytest.raises(raw_store.RawRepresentationDeletionError):
        revoke_consent(grant_ref=grant_ref, revoked_by="operator")

    assert resolve_active_grant(scope="session:retry") is None
    assert raw_store.all_raw_records() == []
    pending = raw_liveness.all_deletion_receipts()
    assert len(pending) == 1
    assert pending[0].reason == retention.REASON_CONSENT_REVOKED
    assert pending[0].payload["cold_cleanup_location_refs"]
    pending_projection = raw_liveness.project_with_response_leases(
        [(raw_ref_for(record), record.content_identity)],
        now=now,
    )
    assert pending_projection[raw_ref_for(record)].outcome == "erasure_pending"
    with pytest.raises(raw_liveness.RawLivenessUnavailableError):
        media_ingress.receipt_answer(
            media_receipt,
            capture_id,
            liveness_by_raw_ref=pending_projection,
        )
    assert list((archive_root / "representations").glob("*.bin"))
    assert list((archive_root / "manifests").glob("*.json"))

    monkeypatch.setattr(raw_store, "_delete_cold_object_path", original_delete)
    retried = retention.enforce_consent_revocation(grant_ref=grant_ref, revoked_at=now)

    assert retried.receipted is True
    assert retried.deleted_count == 0
    assert raw_liveness.all_deletion_receipts()[0].payload["cold_cleanup_location_refs"] == []
    erased_projection = raw_liveness.project_with_response_leases(
        [(raw_ref_for(record), record.content_identity)],
        now=now,
    )
    assert erased_projection[raw_ref_for(record)].outcome == "erased"
    assert media_ingress.receipt_answer(
        media_receipt,
        capture_id,
        liveness_by_raw_ref=erased_projection,
    )["outcome"] == "erased"
    assert list((archive_root / "representations").glob("*.bin")) == []
    assert list((archive_root / "manifests").glob("*.json")) == []


def test_hard_retention_pending_cleanup_blocks_revocation_until_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    grant_ref = "grant-cross-reason"
    grant_consent(
        grant_ref=grant_ref,
        basis="session_optin",
        scope="session:cross-reason",
        granted_by="operator",
    )
    record = _age_record(_insert(b"cross-reason-cleanup", grant_ref=grant_ref), now=now)
    _archive(record, archive_root=archive_root, now=now)
    original_delete = raw_store._delete_cold_object_path  # noqa: SLF001
    monkeypatch.setattr(
        raw_store,
        "_delete_cold_object_path",
        lambda _path: (_ for _ in ()).throw(
            raw_store.RawRepresentationDeletionError("cold unavailable")
        ),
    )

    with pytest.raises(raw_store.RawRepresentationDeletionError):
        raw_liveness.governed_delete_raw_record(
            record_id=record.id,
            reason=retention.REASON_HARD_RETENTION_BOUND,
            retention_window_days=30,
            deleted_at=now,
        )
    pending = raw_liveness.all_deletion_receipts()[0]
    assert pending.reason == retention.REASON_HARD_RETENTION_BOUND
    assert pending.payload[raw_liveness.CONSENT_GRANT_DIGEST_PAYLOAD_KEY] == (
        raw_liveness.consent_grant_digest(grant_ref)
    )

    with pytest.raises(raw_store.RawRepresentationDeletionError):
        revoke_consent(grant_ref=grant_ref, revoked_by="operator")

    monkeypatch.setattr(raw_store, "_delete_cold_object_path", original_delete)
    assert consent_ledger.reconcile_revoked_consent_erasure() == 1
    assert raw_liveness.all_deletion_receipts()[0].payload[
        "cold_cleanup_location_refs"
    ] == []


@pytest.mark.parametrize("matching_grant", ["grant-a", "grant-b"])
def test_multigrant_cleanup_ignores_unrelated_grant_and_true_legacy_is_keyless(
    matching_grant: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    plaintext = f"multigrant-cleanup-{matching_grant}".encode()
    first = _insert(plaintext, grant_ref="grant-a")
    replay_ciphertext, replay_nonce = raw_store.encrypt_raw_bytes(plaintext, key=_KEY)
    replay, created = raw_store.insert_raw_record(
        content_identity=raw_store.compute_raw_content_identity(plaintext),
        capture_chain=["registered-sensor", "heimdal"],
        sensor={"sensor_id": "registered-sensor"},
        consent={"grant_ref": "grant-b"},
        ciphertext=replay_ciphertext,
        nonce=replay_nonce,
        key_ref="test-key-v1",
        key=_KEY,
        source_path="source-class-redacted",
    )
    assert created is False and replay.id == first.id
    record = _age_record(first, now=now)
    _archive(record, archive_root=archive_root, now=now)
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
            record_id=record.id,
            reason=retention.REASON_HARD_RETENTION_BOUND,
            retention_window_days=30,
            deleted_at=now,
        )
    current = raw_liveness.all_deletion_receipts()[0]
    assert raw_liveness.CONSENT_GRANT_DIGEST_PAYLOAD_KEY not in current.payload
    assert set(current.payload[raw_liveness.CONSENT_GRANT_DIGESTS_PAYLOAD_KEY]) == {
        raw_liveness.consent_grant_digest("grant-a"),
        raw_liveness.consent_grant_digest("grant-b"),
    }

    unrelated = retention.enforce_consent_revocation(
        grant_ref="grant-c",
        revoked_at=now,
    )
    assert unrelated.deleted_count == 0
    assert raw_liveness.all_deletion_receipts()[0].payload[
        "cold_cleanup_location_refs"
    ]

    monkeypatch.setattr(raw_store, "_delete_cold_object_path", original_delete)
    matched = retention.enforce_consent_revocation(
        grant_ref=matching_grant,
        revoked_at=now,
    )
    assert matched.deleted_count == 0
    assert raw_liveness.all_deletion_receipts()[0].payload[
        "cold_cleanup_location_refs"
    ] == []

    legacy = _age_record(
        _insert(
            f"true-keyless-legacy-{matching_grant}".encode(),
            grant_ref="grant-historical-row",
        ),
        now=now,
    )
    _archive(legacy, archive_root=archive_root, now=now)
    monkeypatch.setattr(
        raw_store,
        "_delete_cold_object_path",
        lambda _path: (_ for _ in ()).throw(
            raw_store.RawRepresentationDeletionError("legacy cleanup remains pending")
        ),
    )
    with pytest.raises(raw_store.RawRepresentationDeletionError):
        raw_liveness.governed_delete_raw_record(
            record_id=legacy.id,
            reason=retention.REASON_HARD_RETENTION_BOUND,
            retention_window_days=30,
            deleted_at=now,
        )
    with raw_liveness.memory_fence():
        legacy_payload = raw_liveness._MEMORY.deletion_receipts[-1].payload  # noqa: SLF001
        legacy_payload.pop(raw_liveness.CONSENT_GRANT_DIGEST_PAYLOAD_KEY, None)
        legacy_payload.pop(raw_liveness.CONSENT_GRANT_DIGESTS_PAYLOAD_KEY, None)
    legacy_receipt = raw_liveness.all_deletion_receipts()[-1]
    assert raw_liveness.CONSENT_GRANT_DIGEST_PAYLOAD_KEY not in legacy_receipt.payload
    assert raw_liveness.CONSENT_GRANT_DIGESTS_PAYLOAD_KEY not in legacy_receipt.payload

    with pytest.raises(raw_store.RawRepresentationDeletionError, match="legacy cleanup"):
        retention.enforce_consent_revocation(
            grant_ref="grant-legacy-trigger",
            revoked_at=now,
        )


def test_revocation_isolates_tagged_other_grant_but_reconciles_legacy_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    original_delete = raw_store._delete_cold_object_path  # noqa: SLF001

    unrelated = _age_record(_insert(b"unrelated-pending", grant_ref="grant-other"), now=now)
    _archive(unrelated, archive_root=archive_root, now=now)
    monkeypatch.setattr(
        raw_store,
        "_delete_cold_object_path",
        lambda _path: (_ for _ in ()).throw(
            raw_store.RawRepresentationDeletionError("cold unavailable")
        ),
    )
    with pytest.raises(raw_store.RawRepresentationDeletionError):
        raw_liveness.governed_delete_raw_record(
            record_id=unrelated.id,
            reason=retention.REASON_HARD_RETENTION_BOUND,
            retention_window_days=30,
            deleted_at=now,
        )

    target_ref = "grant-isolated-target"
    grant_consent(
        grant_ref=target_ref,
        basis="session_optin",
        scope="session:isolated-target",
        granted_by="operator",
    )
    target = _insert(b"target-hot-only", grant_ref=target_ref)
    revoke_consent(grant_ref=target_ref, revoked_by="operator")
    assert raw_store.resolve_active_raw_record(target.id) is None
    assert raw_liveness.all_deletion_receipts()[0].payload["cold_cleanup_location_refs"]

    monkeypatch.setattr(raw_store, "_delete_cold_object_path", original_delete)
    raw_liveness.governed_delete_raw_record(
        record_id=unrelated.id,
        reason=retention.REASON_HARD_RETENTION_BOUND,
        retention_window_days=30,
        deleted_at=now,
    )

    legacy = _age_record(
        _insert(b"legacy-untagged", grant_ref="grant-historical-row"), now=now
    )
    _archive(legacy, archive_root=archive_root, now=now)
    monkeypatch.setattr(
        raw_store,
        "_delete_cold_object_path",
        lambda _path: (_ for _ in ()).throw(
            raw_store.RawRepresentationDeletionError("legacy cold unavailable")
        ),
    )
    with pytest.raises(raw_store.RawRepresentationDeletionError):
        raw_liveness.governed_delete_raw_record(
            record_id=legacy.id,
            reason=retention.REASON_HARD_RETENTION_BOUND,
            retention_window_days=30,
            deleted_at=now,
        )
    # Model a pre-HAR-05 durable receipt, which could not carry the new
    # redacted grant correlation. The migration posture is conservative:
    # unknown legacy ownership is retried, never silently excluded.
    with raw_liveness.memory_fence():
        legacy_payload = raw_liveness._MEMORY.deletion_receipts[-1].payload  # noqa: SLF001
        legacy_payload.pop(raw_liveness.CONSENT_GRANT_DIGEST_PAYLOAD_KEY, None)
        legacy_payload.pop(raw_liveness.CONSENT_GRANT_DIGESTS_PAYLOAD_KEY, None)
    legacy_receipt = raw_liveness.all_deletion_receipts()[-1]
    assert raw_liveness.CONSENT_GRANT_DIGEST_PAYLOAD_KEY not in legacy_receipt.payload
    assert raw_liveness.CONSENT_GRANT_DIGESTS_PAYLOAD_KEY not in legacy_receipt.payload

    legacy_trigger_ref = "grant-legacy-trigger"
    grant_consent(
        grant_ref=legacy_trigger_ref,
        basis="session_optin",
        scope="session:legacy-trigger",
        granted_by="operator",
    )
    with pytest.raises(raw_store.RawRepresentationDeletionError):
        revoke_consent(grant_ref=legacy_trigger_ref, revoked_by="operator")

    monkeypatch.setattr(raw_store, "_delete_cold_object_path", original_delete)
    assert consent_ledger.reconcile_revoked_consent_erasure() == 2
    assert legacy_receipt.payload["cold_cleanup_location_refs"]
    assert raw_liveness.all_deletion_receipts()[-1].payload[
        "cold_cleanup_location_refs"
    ] == []


def test_scheduled_cleanup_failure_is_loud_and_does_not_advance_freshness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    vault_root = tmp_path / "vault"
    _write_retention_window(vault_root, days=30)
    record = _age_record(_insert(b"scheduled-loud-retry", grant_ref="grant-scheduled"), now=now)
    _archive(record, archive_root=archive_root, now=now)
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

    with pytest.raises(raw_store.RawRepresentationDeletionError):
        retention.enforce_hard_retention_bound(vault_root=vault_root, now=now)
    settings = read_settings_note(vault_root, SETTINGS)
    assert settings is not None
    assert "last_enforced_at" not in settings.values
    projection = raw_liveness.project_with_response_leases(
        [(raw_ref_for(record), record.content_identity)], now=now
    )
    assert projection[raw_ref_for(record)].outcome == "erasure_pending"

    monkeypatch.setattr(raw_store, "_delete_cold_object_path", original_delete)
    retention.enforce_hard_retention_bound(vault_root=vault_root, now=now)
    assert raw_liveness.all_deletion_receipts()[0].payload[
        "cold_cleanup_location_refs"
    ] == []
    settings = read_settings_note(vault_root, SETTINGS)
    assert settings is not None
    assert settings.values["last_enforced_at"]


def test_restore_proof_is_bound_to_the_representation_actually_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    record = _age_record(_insert(b"representation-race", grant_ref="grant-race"), now=now)
    read_fenced = threading.Event()
    release_read = threading.Event()

    def pause_read(stage: str) -> None:
        assert stage == "after_active_representation_resolution"
        read_fenced.set()
        assert release_read.wait(timeout=10)

    monkeypatch.setattr(raw_read_gate, "_raw_read_stage_hook", pause_read)

    def restore() -> str:
        try:
            local_archive.run_restore_drill(raw_ref_for(record), reader=_READER, key=_KEY)
        except local_archive.ArchiveDegradedError as exc:
            return exc.reason
        raise AssertionError("a hot read must not become a cold restore proof")

    with ThreadPoolExecutor(max_workers=2) as executor:
        restore_future = executor.submit(restore)
        assert read_fenced.wait(timeout=10)
        archive_future = executor.submit(_archive, record, archive_root=archive_root, now=now)
        assert not archive_future.done()
        release_read.set()
        assert restore_future.result(timeout=10) == "archived_representation_unavailable"
        assert archive_future.result(timeout=10).active_representation.storage_kind == (
            local_archive.ARCHIVE_STORAGE_KIND
        )


def test_consent_fence_covers_both_capture_revocation_orderings() -> None:
    grant_ref = "grant-fenced-race"
    scope = "session:fenced-race"
    grant_consent(
        grant_ref=grant_ref,
        basis="session_optin",
        scope=scope,
        granted_by="operator",
    )
    admitted = consent_ledger.admit_raw_evidence(scope=scope)
    insert_fenced = threading.Event()
    release_insert = threading.Event()

    def insert_before_revocation():
        with consent_ledger.consent_raw_admission(grant_ref):
            insert_fenced.set()
            assert release_insert.wait(timeout=10)
            return _insert(b"insert-before-revocation", grant_ref=grant_ref)

    with ThreadPoolExecutor(max_workers=2) as executor:
        insertion = executor.submit(insert_before_revocation)
        assert insert_fenced.wait(timeout=10)
        revocation = executor.submit(
            revoke_consent,
            grant_ref=grant_ref,
            revoked_by="operator",
        )
        assert not revocation.done()
        release_insert.set()
        inserted = insertion.result(timeout=10)
        revocation.result(timeout=10)

    assert raw_store.resolve_active_raw_record(inserted.id) is None
    assert admitted.grant.grant_ref == grant_ref
    with pytest.raises(consent_ledger.ConsentRefusedError):
        with consent_ledger.consent_raw_admission(grant_ref):
            _insert(b"insert-after-revocation", grant_ref=grant_ref)


def test_revocation_selector_does_not_materialize_unrelated_cold_bytes(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    unrelated = _age_record(
        _insert(b"unrelated-cold", grant_ref="grant-unrelated"),
        now=now,
    )
    _archive(unrelated, archive_root=archive_root, now=now)
    grant_ref = "grant-metadata-selector"
    grant_consent(
        grant_ref=grant_ref,
        basis="session_optin",
        scope="session:metadata-selector",
        granted_by="operator",
    )
    target = _insert(b"target-hot", grant_ref=grant_ref)
    raw_store.revoke_cold_archive_binding()

    revoke_consent(grant_ref=grant_ref, revoked_by="operator")

    assert raw_store.resolve_active_raw_record(target.id) is None
    assert raw_store.raw_record_ids_by_consent_grant("grant-unrelated") == [unrelated.id]


def test_cold_directory_sync_failure_preserves_erasure_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    record = _age_record(_insert(b"durable-unlink", grant_ref="grant-sync"), now=now)
    _archive(record, archive_root=archive_root, now=now)
    original_fsync = raw_store.os.fsync
    monkeypatch.setattr(raw_store.os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("sync")))

    with pytest.raises(raw_store.RawRepresentationDeletionError):
        raw_liveness.governed_delete_raw_record(
            record_id=record.id,
            reason=retention.REASON_HARD_RETENTION_BOUND,
            retention_window_days=30,
            deleted_at=now,
        )

    detached = raw_liveness.all_deletion_receipts()[0]
    assert detached.payload["cold_cleanup_location_refs"]
    detached.payload["cold_cleanup_location_refs"].clear()
    projection = raw_liveness.project_with_response_leases(
        [(raw_ref_for(record), record.content_identity)],
        now=now,
    )
    assert projection[raw_ref_for(record)].outcome == "erasure_pending"

    monkeypatch.setattr(raw_store.os, "fsync", original_fsync)
    retried = raw_liveness.governed_delete_raw_record(
        record_id=record.id,
        reason=retention.REASON_HARD_RETENTION_BOUND,
        retention_window_days=30,
        deleted_at=now,
    )
    assert retried.outcome == "already_erased"
    assert raw_liveness.all_deletion_receipts()[0].payload["cold_cleanup_location_refs"] == []
