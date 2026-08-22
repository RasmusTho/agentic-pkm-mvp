"""HAR-05: gated restore and all-copy expiry for the local archive."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets

import pytest

from app.heimdal import (
    local_archive,
    media_ingress,
    media_receipts,
    raw_liveness,
    raw_store,
    retention,
)
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
from app.heimdal.settings_notes import SETTINGS, SettingsNote, write_settings_note
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


def _insert(plaintext: bytes, *, grant_ref: str):
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
    assert media_ingress.receipt_answer(
        media_receipt,
        capture_id,
        liveness_by_raw_ref=pending_projection,
    )["outcome"] == "erasure_pending"
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
