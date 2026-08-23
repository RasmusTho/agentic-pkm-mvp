"""HAR-04: verified encrypted hot-to-cold relocation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
import threading
from types import SimpleNamespace

import pytest

from app.heimdal import local_archive, raw_store, retention as retention_module
from app.heimdal.raw_store import (
    all_raw_representations,
    compute_raw_content_identity,
    encrypt_raw_bytes,
    insert_raw_record,
    reset_memory_raw_store,
)
from app.heimdal.raw_read_gate import raw_ref_for, read_raw_record, reset_memory_raw_read_receipts
from app.heimdal.raw_liveness import reset_memory_deletion_receipts
from app.heimdal import raw_liveness
from app.ops.heimdal_cold_volume import (
    _ARCHIVE_VOLUME_READY_ISSUER,
    _issue_archive_volume_ready,
    ArchiveVolumeRefusedError,
)

pytestmark = pytest.mark.not_pg

_KEY = bytes.fromhex(secrets.token_hex(32))
_ARCHIVE_REF = "test-archive"


def _test_volume_ready(archive_ref: str, archive_root: Path):
    return _issue_archive_volume_ready(
        archive_ref, archive_root, _issuer=_ARCHIVE_VOLUME_READY_ISSUER
    )


def _cold_ref(
    representation_id: str,
    *,
    archive_ref: str = _ARCHIVE_REF,
) -> str:
    return raw_store._cold_location_ref(archive_ref, representation_id)  # noqa: SLF001


def test_verified_volume_proof_cannot_be_reused_as_minting_authority(tmp_path: Path) -> None:
    proof = _test_volume_ready(_ARCHIVE_REF, tmp_path / "verified")
    with pytest.raises(ArchiveVolumeRefusedError):
        _issue_archive_volume_ready(
            "forged-archive", tmp_path / "arbitrary", _issuer=getattr(proof, "_issuer", object())
        )

    raw_store.revoke_cold_archive_binding()
    assert (
        raw_store._cold_object_path(  # noqa: SLF001
            _cold_ref("33333333-3333-4333-8333-333333333333")
        )
        is None
    )

    forged_root = tmp_path / "forged"
    object.__setattr__(proof, "mountpoint", forged_root)
    with pytest.raises(raw_store.RawRepresentationDeletionError):
        raw_store.configure_cold_archive_root(forged_root, verified_volume=proof)

    object.__setattr__(proof, "mountpoint", tmp_path / "verified")
    object.__setattr__(proof, "archive_ref", "forged-archive")
    with pytest.raises(raw_store.RawRepresentationDeletionError):
        raw_store.configure_cold_archive_root(
            tmp_path / "verified",
            verified_volume=proof,
            expected_archive_ref=_ARCHIVE_REF,
        )


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


def _insert(plaintext: bytes = b"archive-evidence"):
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


def _eligible(record):
    now = datetime.now(timezone.utc)
    return replace(record, ingested_at=now - timedelta(days=8)), now


def _age_memory_record(record, *, now: datetime):
    """Age the memory fixture's durable identity for production-selector tests."""
    store = raw_store._MEMORY_STORE  # noqa: SLF001
    with store._lock:  # noqa: SLF001
        current = next(row for row in store._rows if row.id == record.id)  # noqa: SLF001
        aged = replace(current, ingested_at=now - timedelta(days=8))
        store._rows = [aged if row.id == record.id else row for row in store._rows]  # noqa: SLF001
        store._by_identity[aged.content_identity] = aged  # noqa: SLF001
    resolved = raw_store.resolve_active_raw_record(record.id)
    assert resolved is not None
    return resolved


def test_archive_eligibility_respects_hot_and_retention_bounds() -> None:
    record = _insert()
    now = datetime.now(timezone.utc)
    assert not local_archive.archive_eligible(record, now=now, retention_window_days=30)
    eligible, now = _eligible(record)
    assert local_archive.archive_eligible(eligible, now=now, retention_window_days=30)
    assert not local_archive.archive_eligible(eligible, now=now, retention_window_days=7)


def test_bounded_archive_pass_selects_and_relocates_eligible_hot_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(timezone.utc)
    record = _age_memory_record(_insert(b"scheduled-archive-pass"), now=now)
    deferred_record = _age_memory_record(
        _insert(b"scheduled-archive-pass-deferred"),
        now=now,
    )
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    metadata = SimpleNamespace(
        mountpoint=archive_root,
        archive_id=_ARCHIVE_REF,
        channel="test",
    )
    monkeypatch.setattr(
        local_archive,
        "load_channel_archive_metadata",
        lambda **_kwargs: metadata,
    )
    monkeypatch.setattr(
        local_archive,
        "require_archive_volume_ready",
        lambda *_args, **_kwargs: _test_volume_ready(_ARCHIVE_REF, archive_root),
    )
    monkeypatch.setattr(local_archive, "resolve_retention_window_days", lambda _root: 30)

    receipt = local_archive.run_archive_pass(
        vault_root=tmp_path,
        config_root=tmp_path,
        channel="test",
        now=now,
        max_records=1,
    )

    assert receipt.as_dict() == {
        "ran": True,
        "healthy": True,
        "reason": "ok",
        "eligible_count": 2,
        "selected_count": 1,
        "archived_count": 1,
        "failed_count": 0,
        "deferred_count": 1,
        "failure_reason_counts": {},
    }
    assert [
        representation.storage_kind
        for representation in all_raw_representations(record.id)
        if representation.active
    ] == ["encrypted_local_cold"]
    assert [
        representation.storage_kind
        for representation in all_raw_representations(deferred_record.id)
        if representation.active
    ] == ["postgres_hot"]

    # A scheduler replay skips the now-cold identity and drains the next
    # bounded hot generation without producing a duplicate inactive copy.
    replay = local_archive.run_archive_pass(
        vault_root=tmp_path,
        config_root=tmp_path,
        channel="test",
        now=now,
        max_records=10,
    )
    assert replay.healthy
    assert replay.eligible_count == 1
    assert replay.archived_count == 1

    complete_replay = local_archive.run_archive_pass(
        vault_root=tmp_path,
        config_root=tmp_path,
        channel="test",
        now=now,
        max_records=10,
    )
    assert complete_replay.healthy
    assert complete_replay.eligible_count == 0
    assert complete_replay.archived_count == 0


def test_archive_pass_is_retryable_and_continues_after_one_volume_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(timezone.utc)
    first = _age_memory_record(_insert(b"archive-pass-first"), now=now)
    second = _age_memory_record(_insert(b"archive-pass-second"), now=now)
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    metadata = SimpleNamespace(
        mountpoint=archive_root,
        archive_id=_ARCHIVE_REF,
        channel="test",
    )
    readiness_calls = 0

    def readiness(*_args: object, **_kwargs: object):
        nonlocal readiness_calls
        readiness_calls += 1
        if readiness_calls == 2:
            raise ArchiveVolumeRefusedError("archive volume unavailable")
        return _test_volume_ready(_ARCHIVE_REF, archive_root)

    monkeypatch.setattr(
        local_archive,
        "load_channel_archive_metadata",
        lambda **_kwargs: metadata,
    )
    monkeypatch.setattr(local_archive, "require_archive_volume_ready", readiness)
    monkeypatch.setattr(local_archive, "resolve_retention_window_days", lambda _root: 30)

    receipt = local_archive.run_archive_pass(
        vault_root=tmp_path,
        config_root=tmp_path,
        channel="test",
        now=now,
    )

    assert not receipt.healthy
    assert receipt.reason == "archive_relocation_degraded"
    assert receipt.selected_count == 2
    assert receipt.archived_count == 1
    assert receipt.failed_count == 1
    assert dict(receipt.failure_reason_counts) == {"archive_mount_unavailable": 1}
    assert [
        representation.storage_kind
        for representation in all_raw_representations(first.id)
        if representation.active
    ] == ["postgres_hot"]
    assert [
        representation.storage_kind
        for representation in all_raw_representations(second.id)
        if representation.active
    ] == ["encrypted_local_cold"]


def test_archive_pass_refuses_overlap_before_volume_or_record_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    touched = False

    def unexpected_metadata(**_kwargs: object) -> object:
        nonlocal touched
        touched = True
        raise AssertionError("overlapping pass reached metadata")

    monkeypatch.setattr(local_archive, "load_channel_archive_metadata", unexpected_metadata)
    with raw_store.archive_relocation_lease():
        receipt = local_archive.run_archive_pass(
            vault_root=tmp_path,
            config_root=tmp_path,
            channel="test",
        )
    assert receipt.reason == "archive_pass_already_running"
    assert not receipt.ran
    assert not receipt.healthy
    assert not touched


def test_api_startup_explicitly_rebinds_returned_volume_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.app import _run_cold_volume_startup_binding
    from app.ops import heimdal_cold_volume as volume

    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    metadata = SimpleNamespace(
        mountpoint=archive_root,
        archive_id=_ARCHIVE_REF,
        channel="prod",
    )
    proof = _test_volume_ready(_ARCHIVE_REF, archive_root)
    monkeypatch.setenv("PKM_ENVIRONMENT", "prod")
    monkeypatch.setenv("PKM_CONFIG_ROOT", str(tmp_path))
    monkeypatch.setattr(
        volume,
        "_channel_archive_metadata_authority",
        lambda **_kwargs: (tmp_path / "archive.json", metadata),
    )
    # Model a validation-only readiness implementation.  Startup must still
    # consume the returned capability and bind its own process-local resolver.
    monkeypatch.setattr(
        volume,
        "require_archive_volume_ready",
        lambda *_args, **_kwargs: proof,
    )

    raw_store.revoke_cold_archive_binding()
    try:
        _run_cold_volume_startup_binding()
        assert (
            raw_store._cold_object_path(  # noqa: SLF001
                _cold_ref("33333333-3333-4333-8333-333333333333")
            )
            == archive_root / "representations" / "33333333-3333-4333-8333-333333333333.bin"
        )
    finally:
        raw_store.revoke_cold_archive_binding()


def test_verified_archive_receipt_precedes_hot_retirement(tmp_path: Path) -> None:
    record, now = _eligible(_insert(b"verified-archive"))
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    result = local_archive.relocate_raw_record(
        record,
        archive_root=archive_root,
        archive_ref=_ARCHIVE_REF,
        now=now,
        retention_window_days=30,
        key=_KEY,
        volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
    )
    assert result.health.healthy
    assert result.receipt.schema == "heimdal_archive_receipt.v1"
    assert (
        tmp_path / "mounted-cold" / "manifests" / f"{result.receipt.representation_id}.json"
    ).exists()
    raw_store._cold_location_paths.clear()  # noqa: SLF001 - restart-like cache loss
    assert result.active_representation.archive_token is not None
    assert result.active_representation.archive_generation is not None
    assert (
        raw_store._resolve_cold_ciphertext(
            result.active_representation.location_ref,
            expected_archive_token=result.active_representation.archive_token,
            expected_archive_generation=result.active_representation.archive_generation,
            expected_raw_generation=result.active_representation.raw_generation,
            expected_representation_id=result.active_representation.id,
        )
        == next(  # noqa: SLF001
            (archive_root / "representations").glob("*.bin")
        ).read_bytes()
    )
    representations = all_raw_representations(record.id)
    assert [item.storage_kind for item in representations if item.active] == [
        "encrypted_local_cold"
    ]
    assert (
        read_raw_record(
            raw_ref_for(record), reader="authorized-reader", purpose="HAR-04 proof", key=_KEY
        ).plaintext
        == b"verified-archive"
    )


def test_terminal_archive_replay_rebinds_cold_volume_after_restart(tmp_path: Path) -> None:
    record, now = _eligible(_insert(b"restart-terminal-replay"))
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    first = local_archive.relocate_raw_record(
        record,
        archive_root=archive_root,
        archive_ref=_ARCHIVE_REF,
        now=now,
        retention_window_days=30,
        key=_KEY,
        volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
    )

    raw_store.revoke_cold_archive_binding()
    replay = local_archive.relocate_raw_record(
        record,
        archive_root=archive_root,
        archive_ref=_ARCHIVE_REF,
        now=now,
        retention_window_days=30,
        key=_KEY,
        volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
    )

    assert replay.receipt == first.receipt
    assert replay.active_representation == first.active_representation


def test_terminal_pre_gaf_manifest_is_additively_bound_after_restart(tmp_path: Path) -> None:
    record, now = _eligible(_insert(b"terminal-pre-gaf-replay"))
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    first = local_archive.relocate_raw_record(
        record,
        archive_root=archive_root,
        archive_ref=_ARCHIVE_REF,
        now=now,
        retention_window_days=30,
        key=_KEY,
        volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
    )
    manifest_path = archive_root / "manifests" / f"{first.receipt.representation_id}.json"
    legacy = json.loads(manifest_path.read_text(encoding="utf-8"))
    legacy.pop("gaf_operation")
    manifest_path.write_text(
        json.dumps(legacy, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    raw_store.revoke_cold_archive_binding()

    replay = local_archive.relocate_raw_record(
        record,
        archive_root=archive_root,
        archive_ref=_ARCHIVE_REF,
        now=now + timedelta(days=31),
        retention_window_days=30,
        key=_KEY,
        volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
    )

    upgraded = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert replay.receipt == first.receipt
    assert {key: upgraded[key] for key in legacy} == legacy
    assert upgraded["gaf_operation"]["source_representation_id"] != first.receipt.representation_id
    assert upgraded["gaf_operation"]["target_representation_id"] == first.receipt.representation_id


def test_verify_before_hot_representation_retire_and_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record, now = _eligible(_insert(b"must-stay-hot"))
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    original_write = local_archive._durable_write

    def corrupt_first_write(path: Path, payload: bytes) -> None:
        if path.suffix == ".bin":
            return original_write(path, b"tampered")
        return original_write(path, payload)

    monkeypatch.setattr(local_archive, "_durable_write", corrupt_first_write)
    with pytest.raises(local_archive.ArchiveDegradedError) as error:
        local_archive.relocate_raw_record(
            record,
            archive_root=archive_root,
            archive_ref=_ARCHIVE_REF,
            now=now,
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
        )
    assert error.value.reason == "archive_copy_verification_failed"
    assert [item.storage_kind for item in all_raw_representations(record.id) if item.active] == [
        "postgres_hot"
    ]
    pending = [
        item
        for item in all_raw_representations(record.id)
        if item.storage_kind == "encrypted_local_cold" and not item.active
    ]
    assert len(pending) == 1
    assert list((archive_root / "representations").glob("*.bin")) == []
    manifests = list((archive_root / "manifests").glob("*.json"))
    assert len(manifests) == 1
    reserved_manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert reserved_manifest["ownership_state"] == "reserved"
    assert reserved_manifest["representation_id"] == pending[0].id
    assert reserved_manifest["gaf_operation"]["target_representation_id"] == pending[0].id

    monkeypatch.setattr(local_archive, "_durable_write", original_write)
    retried = local_archive.relocate_raw_record(
        record,
        archive_root=archive_root,
        archive_ref=_ARCHIVE_REF,
        now=now,
        retention_window_days=30,
        key=_KEY,
        volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
    )
    assert retried.receipt.representation_id == pending[0].id
    assert retried.active_representation.active


def test_registration_checkpoint_after_effect_preserves_retry_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record, now = _eligible(_insert(b"checkpoint-after-effect"))
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    original_checkpoint = raw_liveness._checkpoint_raw_mutation_authority  # noqa: SLF001

    def commit_then_raise(authority: raw_liveness.RawMutationAuthority) -> None:
        original_checkpoint(authority)
        raise RuntimeError("checkpoint acknowledgement lost")

    monkeypatch.setattr(
        raw_liveness,
        "_checkpoint_raw_mutation_authority",
        commit_then_raise,
    )
    with pytest.raises(local_archive.ArchiveDegradedError, match="archive_relocation_failed"):
        local_archive.relocate_raw_record(
            record,
            archive_root=archive_root,
            archive_ref=_ARCHIVE_REF,
            now=now,
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
        )
    pending = [
        item
        for item in all_raw_representations(record.id)
        if item.storage_kind == "encrypted_local_cold" and not item.active
    ]
    assert len(pending) == 1
    manifest_path = archive_root / "manifests" / f"{pending[0].id}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["ownership_state"] == "reserved"
    assert manifest["representation_id"] == pending[0].id

    monkeypatch.setattr(
        raw_liveness,
        "_checkpoint_raw_mutation_authority",
        original_checkpoint,
    )
    retried = local_archive.relocate_raw_record(
        record,
        archive_root=archive_root,
        archive_ref=_ARCHIVE_REF,
        now=now,
        retention_window_days=30,
        key=_KEY,
        volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
    )
    assert retried.receipt.representation_id == pending[0].id
    assert retried.active_representation.active


def test_verified_manifest_post_effect_failure_preserves_retryable_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record, now = _eligible(_insert(b"verified-manifest-after-effect"))
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    original_write = local_archive._durable_write

    def write_then_lose_ack(path: Path, payload: bytes) -> None:
        original_write(path, payload)
        if path.suffix == ".json" and b'"ownership_state":"verified"' in payload:
            raise RuntimeError("verified manifest acknowledgement lost")

    monkeypatch.setattr(local_archive, "_durable_write", write_then_lose_ack)
    with pytest.raises(local_archive.ArchiveDegradedError, match="archive_relocation_failed"):
        local_archive.relocate_raw_record(
            record,
            archive_root=archive_root,
            archive_ref=_ARCHIVE_REF,
            now=now,
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
        )
    pending = [
        item
        for item in all_raw_representations(record.id)
        if item.storage_kind == "encrypted_local_cold" and not item.active
    ]
    assert len(pending) == 1
    manifest_path = archive_root / "manifests" / f"{pending[0].id}.json"
    object_path = archive_root / "representations" / f"{pending[0].id}.bin"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["ownership_state"] == "verified"
    assert object_path.read_bytes() == record.ciphertext

    monkeypatch.setattr(local_archive, "_durable_write", original_write)
    retried = local_archive.relocate_raw_record(
        record,
        archive_root=archive_root,
        archive_ref=_ARCHIVE_REF,
        now=now,
        retention_window_days=30,
        key=_KEY,
        volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
    )
    assert retried.receipt.representation_id == pending[0].id
    assert retried.active_representation.active


def test_owner_writer_rechecks_missing_pending_manifest_inside_relocation_fence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record, now = _eligible(_insert(b"manifest-fence-recheck"))
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()

    class PendingProcessLoss(BaseException):
        pass

    def lose_after_reservation(stage: str) -> None:
        if stage == "after_reservation":
            raise PendingProcessLoss

    monkeypatch.setattr(local_archive, "_relocation_stage_hook", lose_after_reservation)
    with pytest.raises(PendingProcessLoss):
        local_archive.relocate_raw_record(
            record,
            archive_root=archive_root,
            archive_ref=_ARCHIVE_REF,
            now=now,
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
        )
    pending = next(
        item
        for item in all_raw_representations(record.id)
        if item.storage_kind == "encrypted_local_cold" and not item.active
    )
    manifest_path = archive_root / "manifests" / f"{pending.id}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_path.unlink()
    monkeypatch.setattr(local_archive, "_relocation_stage_hook", lambda _stage: None)

    for stale_outer_read in (None, manifest):
        with pytest.raises(
            local_archive.ArchiveDegradedError, match="archive_manifest_invalid"
        ):
            local_archive._relocate_raw_record_owner_native(
                record,
                archive_root=archive_root,
                archive_ref=_ARCHIVE_REF,
                now=now,
                retention_window_days=30,
                key=_KEY,
                volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
                requested_representation_id=pending.id,
                requested_receipt_id=str(manifest["receipt_id"]),
                operation_binding=manifest["gaf_operation"],
                existing_manifest=stale_outer_read,
            )
    typed_corruption = dict(manifest)
    typed_corruption["encrypted_bytes"] = str(manifest["encrypted_bytes"])
    manifest_path.write_text(
        json.dumps(typed_corruption, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(local_archive.ArchiveDegradedError, match="archive_manifest_invalid"):
        local_archive._relocate_raw_record_owner_native(
            record,
            archive_root=archive_root,
            archive_ref=_ARCHIVE_REF,
            now=now,
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
            requested_representation_id=pending.id,
            requested_receipt_id=str(manifest["receipt_id"]),
            operation_binding=manifest["gaf_operation"],
            existing_manifest=manifest,
        )
    naive_timestamp = dict(manifest)
    naive_timestamp["verified_at"] = str(manifest["verified_at"]).removesuffix("Z")
    manifest_path.write_text(
        json.dumps(naive_timestamp, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(local_archive.ArchiveDegradedError, match="archive_manifest_invalid"):
        local_archive._relocate_raw_record_owner_native(
            record,
            archive_root=archive_root,
            archive_ref=_ARCHIVE_REF,
            now=now,
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
            requested_representation_id=pending.id,
            requested_receipt_id=str(manifest["receipt_id"]),
            operation_binding=manifest["gaf_operation"],
            existing_manifest=manifest,
        )
    rows = all_raw_representations(record.id)
    assert next(item for item in rows if item.active).storage_kind == "postgres_hot"
    assert len([item for item in rows if not item.active]) == 1


def test_relocation_rejects_source_generation_drift_before_manifest_write(
    tmp_path: Path,
) -> None:
    record, now = _eligible(_insert(b"source-generation-drift"))
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    hot = next(item for item in all_raw_representations(record.id) if item.active)
    store = raw_store._MEMORY_STORE  # noqa: SLF001
    with store._lock:  # noqa: SLF001
        store._representations[hot.id] = replace(  # noqa: SLF001
            hot, raw_generation=hot.raw_generation + 1
        )

    with pytest.raises(local_archive.ArchiveDegradedError, match="archive_manifest_invalid"):
        local_archive.relocate_raw_record(
            record,
            archive_root=archive_root,
            archive_ref=_ARCHIVE_REF,
            now=now,
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
        )
    rows = all_raw_representations(record.id)
    assert len(rows) == 1 and rows[0].active
    assert list((archive_root / "manifests").glob("*.json")) == []
    assert list((archive_root / "representations").glob("*.bin")) == []


def test_relocation_reservation_fences_retention_and_crash_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record, now = _eligible(_insert(b"relocation-retention-race"))
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    reservation_seen = threading.Event()
    object_written = threading.Event()
    release_relocation = threading.Event()
    retention_at_fence = threading.Event()

    def crash_after_object(stage: str) -> None:
        if stage == "after_reservation":
            pending = [
                item
                for item in all_raw_representations(record.id)
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
                record,
                archive_root=archive_root,
                archive_ref=_ARCHIVE_REF,
                now=now,
                retention_window_days=30,
                key=_KEY,
                volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
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
    assert all_raw_representations(record.id) == []
    assert raw_liveness.all_deletion_receipts()[0].payload["cold_cleanup_location_refs"] == []
    assert list((archive_root / "representations").glob("*.bin")) == []
    assert list((archive_root / "manifests").glob("*.json")) == []


def test_new_deletion_cannot_inject_cold_cleanup_authority() -> None:
    record = _insert(b"reserved-cleanup-authority")

    with pytest.raises(ValueError, match="reserved for governed retention authority"):
        raw_liveness.governed_delete_raw_record(
            record_id=record.id,
            reason="hard_retention_bound",
            retention_window_days=30,
            deleted_at=datetime.now(timezone.utc),
            payload={
                "cold_cleanup_location_refs": [_cold_ref("33333333-3333-4333-8333-333333333333")]
            },
        )

    assert [item.id for item in raw_store.all_raw_records()] == [record.id]
    assert raw_liveness.all_deletion_receipts() == []


def test_archive_receipts_are_redacted(tmp_path: Path) -> None:
    secret = b"never-put-plaintext-in-receipt"
    record, now = _eligible(_insert(secret))
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    result = local_archive.relocate_raw_record(
        record,
        archive_root=archive_root,
        archive_ref=_ARCHIVE_REF,
        now=now,
        retention_window_days=30,
        key=_KEY,
        volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
    )
    manifest = next((tmp_path / "mounted-cold" / "manifests").glob("*.json")).read_text()
    assert secret.decode() not in manifest
    assert str(tmp_path) not in manifest
    assert record.source_path not in manifest
    assert result.receipt.as_dict()["content_identity"] == record.content_identity


def test_archive_requires_verified_mount_and_redacts_failure(tmp_path: Path) -> None:
    record, now = _eligible(_insert(b"mount-gated"))
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    with pytest.raises(local_archive.ArchiveDegradedError, match="archive_mount_unavailable"):
        local_archive.relocate_raw_record(
            record,
            archive_root=archive_root,
            archive_ref=_ARCHIVE_REF,
            now=now,
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: object(),
        )

    original_write = local_archive._durable_write

    def fail_manifest(path: Path, payload: bytes) -> None:
        if path.suffix == ".json":
            raise OSError(f"sensitive path: {path}")
        original_write(path, payload)

    # The returned error is redacted and the pre-receipt object is cleaned up.
    with pytest.raises(local_archive.ArchiveDegradedError) as error:
        local_archive._durable_write = fail_manifest
        try:
            local_archive.relocate_raw_record(
                record,
                archive_root=archive_root,
                archive_ref=_ARCHIVE_REF,
                now=now,
                retention_window_days=30,
                key=_KEY,
                volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
            )
        finally:
            local_archive._durable_write = original_write
    assert str(tmp_path) not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert list((archive_root / "representations").glob("*.bin")) == []

    bad_root = tmp_path / "bad-root"
    bad_root.mkdir()
    original_mkdir = Path.mkdir

    def fail_mkdir(self: Path, *args: object, **kwargs: object) -> None:
        raise OSError(f"sensitive path: {self}")

    try:
        Path.mkdir = fail_mkdir  # type: ignore[method-assign]
        with pytest.raises(local_archive.ArchiveDegradedError) as mount_error:
            local_archive.relocate_raw_record(
                record,
                archive_root=bad_root,
                archive_ref=_ARCHIVE_REF,
                now=now,
                retention_window_days=30,
                key=_KEY,
                volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
            )
    finally:
        Path.mkdir = original_mkdir  # type: ignore[method-assign]
    assert mount_error.value.__cause__ is None
    assert mount_error.value.__context__ is None

    wrong_root = tmp_path / "wrong-root"
    wrong_root.mkdir()
    with pytest.raises(local_archive.ArchiveDegradedError, match="archive_mount_unavailable"):
        local_archive.relocate_raw_record(
            record,
            archive_root=wrong_root,
            archive_ref=_ARCHIVE_REF,
            now=now,
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
        )

    with pytest.raises(local_archive.ArchiveDegradedError) as callback_error:
        local_archive.relocate_raw_record(
            record,
            archive_root=archive_root,
            archive_ref=_ARCHIVE_REF,
            now=now,
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: (_ for _ in ()).throw(OSError("sensitive callback path")),
        )
    assert callback_error.value.__cause__ is None
    assert callback_error.value.__context__ is None

    with pytest.raises(local_archive.ArchiveDegradedError, match="archive_mount_unavailable"):
        local_archive.relocate_raw_record(
            record,
            archive_root=archive_root,
            archive_ref="different-archive",
            now=now,
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
        )

    with pytest.raises(local_archive.ArchiveDegradedError, match="archive_mount_unavailable"):
        local_archive.relocate_raw_record(
            record,
            archive_root=archive_root,
            archive_ref=_ARCHIVE_REF,
            now=now,
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: True,  # type: ignore[return-value]
        )


def test_registration_failure_discards_unregistered_archive_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record, now = _eligible(_insert(b"registration-failure"))
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()

    def fail_registration(**_kwargs: object) -> object:
        raise RuntimeError("registration unavailable")

    monkeypatch.setattr(raw_store, "register_cold_raw_representation", fail_registration)
    with pytest.raises(local_archive.ArchiveDegradedError, match="archive_relocation_failed"):
        local_archive.relocate_raw_record(
            record,
            archive_root=archive_root,
            archive_ref=_ARCHIVE_REF,
            now=now,
            retention_window_days=30,
            key=_KEY,
            volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
        )

    assert list((archive_root / "representations").glob("*.bin")) == []
    assert list((archive_root / "manifests").glob("*.json")) == []

    arbitrary_root = tmp_path / "arbitrary-root"
    arbitrary_root.mkdir()
    arbitrary_object = (
        arbitrary_root / "representations" / "33333333-3333-4333-8333-333333333333.bin"
    )
    arbitrary_object.parent.mkdir()
    with pytest.raises(raw_store.RawRepresentationDeletionError):
        raw_store.register_cold_location(
            _cold_ref("33333333-3333-4333-8333-333333333333"),
            arbitrary_object,
            verified_volume=_test_volume_ready(_ARCHIVE_REF, archive_root),
            raw_generation=1,
            representation_id="33333333-3333-4333-8333-333333333333",
        )


def test_governed_cold_cleanup_removes_object_and_manifest(tmp_path: Path) -> None:
    record, now = _eligible(_insert(b"delete-cold"))
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    result = local_archive.relocate_raw_record(
        record,
        archive_root=archive_root,
        archive_ref=_ARCHIVE_REF,
        now=now,
        retention_window_days=30,
        key=_KEY,
        volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
    )
    assert list((archive_root / "representations").glob("*.bin"))
    assert list((archive_root / "manifests").glob("*.json"))
    raw_store._delete_cold_objects_for_record(record.id)  # noqa: SLF001
    assert list((archive_root / "representations").glob("*.bin")) == []
    assert list((archive_root / "manifests").glob("*.json")) == []
    assert result.receipt.representation_id


def test_scheduled_retention_retries_pending_cleanup_after_db_erasure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record, now = _eligible(_insert(b"scheduled-retry"))
    archive_root = tmp_path / "mounted-cold"
    archive_root.mkdir()
    local_archive.relocate_raw_record(
        record,
        archive_root=archive_root,
        archive_ref=_ARCHIVE_REF,
        now=now,
        retention_window_days=30,
        key=_KEY,
        volume_ready=lambda: _test_volume_ready(_ARCHIVE_REF, archive_root),
    )

    original_delete = raw_store._delete_cold_object_path  # noqa: SLF001
    attempts = 0

    def fail_once(path: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise raw_store.RawRepresentationDeletionError("simulated cold outage")
        original_delete(path)

    monkeypatch.setattr(raw_store, "_delete_cold_object_path", fail_once)
    with pytest.raises(raw_store.RawRepresentationDeletionError):
        raw_liveness.governed_delete_raw_record(
            record_id=record.id,
            reason="hard_retention_bound",
            retention_window_days=30,
            deleted_at=now,
        )

    assert raw_store.all_raw_records() == []
    pending = raw_liveness.all_deletion_receipts()
    assert len(pending) == 1
    assert pending[0].payload["cold_cleanup_location_refs"]

    monkeypatch.setattr(
        retention_module, "_resolve_retention_window_days", lambda *_args, **_kwargs: 30
    )
    scheduled = retention_module.enforce_hard_retention_bound(
        vault_root=tmp_path, now=now, record_last_enforced=False
    )

    assert scheduled.deleted_count == 0
    assert raw_liveness.all_deletion_receipts()[0].payload["cold_cleanup_location_refs"] == []
    assert list((archive_root / "representations").glob("*.bin")) == []
    assert list((archive_root / "manifests").glob("*.json")) == []


def test_cleanup_refuses_a_different_verified_archive_after_rebind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, now = _eligible(_insert(b"archive-bound-cleanup"))
    original_root = tmp_path / "original-archive"
    replacement_root = tmp_path / "replacement-archive"
    original_root.mkdir()
    replacement_root.mkdir()
    original_proof = _test_volume_ready(_ARCHIVE_REF, original_root)
    replacement_ref = "replacement-archive"
    replacement_proof = _test_volume_ready(replacement_ref, replacement_root)

    result = local_archive.relocate_raw_record(
        record,
        archive_root=original_root,
        archive_ref=_ARCHIVE_REF,
        now=now,
        retention_window_days=30,
        key=_KEY,
        volume_ready=lambda: original_proof,
    )
    location_ref = result.active_representation.location_ref
    original_object = original_root / "representations" / f"{result.active_representation.id}.bin"

    def rebind_after_authority(stage: str) -> None:
        if stage == "after_raw_delete":
            raw_store.configure_cold_archive_root(
                replacement_root,
                verified_volume=replacement_proof,
                expected_archive_ref=replacement_ref,
            )

    monkeypatch.setattr(raw_liveness, "_retention_stage_hook", rebind_after_authority)
    with pytest.raises(
        raw_store.RawRepresentationDeletionError,
        match="archive binding is unavailable",
    ):
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
    assert raw_store._cold_object_path(location_ref) is None  # noqa: SLF001

    monkeypatch.setattr(raw_liveness, "_retention_stage_hook", lambda _stage: None)
    raw_store.configure_cold_archive_root(
        original_root,
        verified_volume=original_proof,
        expected_archive_ref=_ARCHIVE_REF,
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


def test_pg_cursor_cold_cleanup_locks_rows_and_removes_files(tmp_path: Path) -> None:
    archive_root = tmp_path / "mounted-cold"
    objects = archive_root / "representations"
    manifests = archive_root / "manifests"
    objects.mkdir(parents=True)
    manifests.mkdir()
    representation_id = "11111111-1111-4111-8111-111111111111"
    location_ref = _cold_ref(representation_id)
    object_path = objects / f"{representation_id}.bin"
    object_path.write_bytes(b"ciphertext")
    proof = _test_volume_ready(_ARCHIVE_REF, archive_root)
    archive_token = raw_store._archive_binding_token(proof.archive_ref)  # noqa: SLF001
    (manifests / f"{representation_id}.json").write_text(
        json.dumps(
            {
                "ownership_state": "verified",
                "location_ref": location_ref,
                "archive_token": archive_token,
                "archive_generation": proof.archive_generation,
                "raw_generation": 1,
                "representation_id": representation_id,
            }
        )
        + "\n"
    )
    raw_store.configure_cold_archive_root(
        archive_root,
        verified_volume=proof,
        expected_archive_ref=_ARCHIVE_REF,
    )
    raw_store.register_cold_location(
        location_ref,
        object_path,
        verified_volume=proof,
        raw_generation=1,
        representation_id=representation_id,
    )

    class Cursor:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def execute(self, query: str, params: object) -> None:
            self.queries.append(query)

        def fetchall(self) -> list[tuple[object, ...]]:
            return [
                (
                    representation_id,
                    location_ref,
                    archive_token,
                    proof.archive_generation,
                    1,
                )
            ]

    cursor = Cursor()
    raw_store._delete_cold_objects_for_pg_cursor(cursor, "record-id")  # noqa: SLF001
    assert any("FOR UPDATE" in query for query in cursor.queries)
    assert not object_path.exists()
    assert not (manifests / f"{representation_id}.json").exists()


def test_pg_erasure_cleanup_receipt_reconciles_after_commit(tmp_path: Path) -> None:
    archive_root = tmp_path / "mounted-cold"
    objects = archive_root / "representations"
    manifests = archive_root / "manifests"
    objects.mkdir(parents=True)
    manifests.mkdir()
    representation_id = "22222222-2222-4222-8222-222222222222"
    location_ref = _cold_ref(representation_id)
    object_path = objects / f"{representation_id}.bin"
    object_path.write_bytes(b"ciphertext")
    proof = _test_volume_ready(_ARCHIVE_REF, archive_root)
    archive_token = raw_store._archive_binding_token(proof.archive_ref)  # noqa: SLF001
    (manifests / f"{representation_id}.json").write_text(
        json.dumps(
            {
                "ownership_state": "verified",
                "location_ref": location_ref,
                "archive_token": archive_token,
                "archive_generation": proof.archive_generation,
                "raw_generation": 1,
                "representation_id": representation_id,
            }
        )
        + "\n"
    )
    raw_store.configure_cold_archive_root(
        archive_root,
        verified_volume=proof,
        expected_archive_ref=_ARCHIVE_REF,
    )
    raw_store.register_cold_location(
        location_ref,
        object_path,
        verified_volume=proof,
        raw_generation=1,
        representation_id=representation_id,
    )

    class ReceiptCursor:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, query: str, params: object) -> None:
            self.calls += 1

        def fetchone(self) -> tuple[object, ...]:
            if self.calls == 1:
                return ("receipt-id", 1)
            return (
                {
                    "cold_cleanup_location_refs": [location_ref],
                    "cold_cleanup_archive_bindings": {
                        location_ref: {
                            "archive_token": raw_store._archive_binding_token(  # noqa: SLF001
                                proof.archive_ref
                            ),
                            "archive_generation": proof.archive_generation,
                            "raw_generation": 1,
                            "representation_id": representation_id,
                        }
                    },
                },
            )

    cursor = ReceiptCursor()
    raw_liveness._reconcile_pg_cold_cleanup(cursor, "record-id")  # noqa: SLF001
    assert cursor.calls == 3
    assert not object_path.exists()
    assert not (manifests / f"{representation_id}.json").exists()
