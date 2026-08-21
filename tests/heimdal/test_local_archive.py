"""HAR-04: verified encrypted hot-to-cold relocation."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import secrets

import pytest

from app.heimdal import local_archive, raw_store
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
)

pytestmark = pytest.mark.not_pg

_KEY = bytes.fromhex(secrets.token_hex(32))
_ARCHIVE_REF = "test-archive"


def _test_volume_ready(archive_ref: str, archive_root: Path):
    return _issue_archive_volume_ready(
        archive_ref, archive_root, _issuer=_ARCHIVE_VOLUME_READY_ISSUER
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


def test_archive_eligibility_respects_hot_and_retention_bounds() -> None:
    record = _insert()
    now = datetime.now(timezone.utc)
    assert not local_archive.archive_eligible(
        record, now=now, retention_window_days=30
    )
    eligible, now = _eligible(record)
    assert local_archive.archive_eligible(eligible, now=now, retention_window_days=30)
    assert not local_archive.archive_eligible(eligible, now=now, retention_window_days=7)


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
    assert (tmp_path / "mounted-cold" / "manifests" / f"{result.receipt.representation_id}.json").exists()
    raw_store._cold_location_paths.clear()  # noqa: SLF001 - restart-like cache loss
    assert raw_store._resolve_cold_ciphertext(result.active_representation.location_ref) == next(  # noqa: SLF001
        (archive_root / "representations").glob("*.bin")
    ).read_bytes()
    representations = all_raw_representations(record.id)
    assert [item.storage_kind for item in representations if item.active] == [
        "encrypted_local_cold"
    ]
    assert read_raw_record(
        raw_ref_for(record), reader="authorized-reader", purpose="HAR-04 proof", key=_KEY
    ).plaintext == b"verified-archive"


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
    arbitrary_object = arbitrary_root / "representations" / "33333333-3333-4333-8333-333333333333.bin"
    arbitrary_object.parent.mkdir()
    with pytest.raises(raw_store.RawRepresentationDeletionError):
        raw_store.register_cold_location(
            "heimloc:cold:33333333-3333-4333-8333-333333333333",
            arbitrary_object,
            verified_volume=_test_volume_ready(_ARCHIVE_REF, archive_root),
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


def test_pg_cursor_cold_cleanup_locks_rows_and_removes_files(tmp_path: Path) -> None:
    archive_root = tmp_path / "mounted-cold"
    objects = archive_root / "representations"
    manifests = archive_root / "manifests"
    objects.mkdir(parents=True)
    manifests.mkdir()
    representation_id = "11111111-1111-4111-8111-111111111111"
    location_ref = f"heimloc:cold:{representation_id}"
    object_path = objects / f"{representation_id}.bin"
    object_path.write_bytes(b"ciphertext")
    (manifests / f"{representation_id}.json").write_text("{}\n")
    raw_store.register_cold_location(
        location_ref,
        object_path,
        verified_volume=_test_volume_ready(_ARCHIVE_REF, archive_root),
    )

    class Cursor:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def execute(self, query: str, params: object) -> None:
            self.queries.append(query)

        def fetchall(self) -> list[tuple[str]]:
            return [(location_ref,)]

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
    location_ref = f"heimloc:cold:{representation_id}"
    object_path = objects / f"{representation_id}.bin"
    object_path.write_bytes(b"ciphertext")
    (manifests / f"{representation_id}.json").write_text("{}\n")
    raw_store.register_cold_location(
        location_ref,
        object_path,
        verified_volume=_test_volume_ready(_ARCHIVE_REF, archive_root),
    )

    class ReceiptCursor:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, query: str, params: object) -> None:
            self.calls += 1

        def fetchone(self) -> tuple[object]:
            if self.calls == 1:
                return ("receipt-id",)
            return ({"cold_cleanup_location_refs": [location_ref]},)

    cursor = ReceiptCursor()
    raw_liveness._reconcile_pg_cold_cleanup(cursor, "record-id")  # noqa: SLF001
    assert cursor.calls == 3
    assert not object_path.exists()
    assert not (manifests / f"{representation_id}.json").exists()
