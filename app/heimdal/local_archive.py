"""Verified hot-to-cold relocation for Heimdal raw evidence (HAR-04).

The archive is a storage representation, not a second authority. A record's
opaque ``raw_ref`` and immutable identity stay in the raw store; this module
only copies the encrypted hot bytes, writes a redacted manifest, and then
activates a registered cold representation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Callable, Optional
from uuid import uuid4

from app.heimdal import raw_store
from app.heimdal.raw_store import RawRecord, RawRepresentation
from app.heimdal.retention import resolve_retention_window_days
from app.ops.heimdal_cold_volume import ArchiveVolumeReady

ARCHIVE_SCHEMA = "heimdal_archive_receipt.v1"
ARCHIVE_STORAGE_KIND = "encrypted_local_cold"
ARCHIVE_MINIMUM_AGE_DAYS = 7


class ArchiveDegradedError(RuntimeError):
    """A cold relocation could not be proven safe; hot data remains active."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Heimdal local archive degraded: {reason}")


@dataclass(frozen=True)
class ArchiveHealth:
    healthy: bool
    reason: str


@dataclass(frozen=True)
class ArchiveReceipt:
    receipt_id: str
    record_id: str
    content_identity: str
    representation_id: str
    encrypted_bytes: int
    ciphertext_sha256: str
    verified_at: datetime
    schema: str = ARCHIVE_SCHEMA

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "receipt_id": self.receipt_id,
            "record_id": self.record_id,
            "content_identity": self.content_identity,
            "representation_id": self.representation_id,
            "encrypted_bytes": self.encrypted_bytes,
            "ciphertext_sha256": self.ciphertext_sha256,
            "verified_at": _iso(self.verified_at),
        }


@dataclass(frozen=True)
class ArchiveResult:
    receipt: ArchiveReceipt
    health: ArchiveHealth
    active_representation: RawRepresentation


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def archive_eligible(
    record: RawRecord,
    *,
    now: datetime,
    retention_window_days: int,
    minimum_age_days: int = ARCHIVE_MINIMUM_AGE_DAYS,
) -> bool:
    """Return true only inside the seven-day-to-retention window."""
    reference = _utc(now)
    ingested = _utc(record.ingested_at)
    return (
        ingested < reference - timedelta(days=minimum_age_days)
        and ingested >= reference - timedelta(days=retention_window_days)
    )


def eligible_raw_records(
    *,
    vault_root: Path,
    now: Optional[datetime] = None,
    retention_window_days: Optional[int] = None,
) -> list[RawRecord]:
    reference = now or datetime.now(timezone.utc)
    window = (
        retention_window_days
        if retention_window_days is not None
        else resolve_retention_window_days(vault_root)
    )
    return [
        record
        for record in raw_store.all_raw_records()
        if archive_eligible(record, now=reference, retention_window_days=window)
    ]


def _ensure_archive_dirs(archive_root: Path) -> tuple[Path, Path]:
    if not archive_root.is_absolute() or not archive_root.is_dir():
        raise ArchiveDegradedError("archive_mount_unavailable")
    objects = archive_root / "representations"
    manifests = archive_root / "manifests"
    try:
        objects.mkdir(exist_ok=True)
        manifests.mkdir(exist_ok=True)
    except OSError:
        raise ArchiveDegradedError("archive_mount_unavailable") from None
    return objects, manifests


def _discard_uncommitted_object(object_path: Path) -> None:
    try:
        object_path.unlink(missing_ok=True)
    except OSError:
        # A later retry can reconcile an unreadable orphan; never disclose the
        # mounted volume path through an exception or log value.
        return


def _durable_write(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _manifest_payload(receipt: ArchiveReceipt) -> bytes:
    return (json.dumps(receipt.as_dict(), sort_keys=True, separators=(",", ":")) + "\n").encode()


def _active_hot(record_id: str) -> RawRepresentation:
    active = [item for item in raw_store.all_raw_representations(record_id) if item.active]
    if len(active) != 1 or active[0].storage_kind != "postgres_hot":
        raise ArchiveDegradedError("hot_representation_unavailable")
    return active[0]


def relocate_raw_record(
    record: RawRecord,
    *,
    archive_root: Path,
    archive_ref: str,
    now: Optional[datetime] = None,
    retention_window_days: Optional[int] = None,
    vault_root: Optional[Path] = None,
    key: Optional[bytes] = None,
    volume_ready: Callable[[], ArchiveVolumeReady],
) -> ArchiveResult:
    """Copy, verify, receipt, then activate cold; fail closed on every error."""
    reference = now or datetime.now(timezone.utc)
    if retention_window_days is None:
        if vault_root is None:
            raise ArchiveDegradedError("retention_policy_unavailable")
        retention_window_days = resolve_retention_window_days(vault_root)
    if not archive_eligible(record, now=reference, retention_window_days=retention_window_days):
        raise ArchiveDegradedError("record_outside_archive_window")
    try:
        volume_proof = volume_ready()
    except Exception:
        raise ArchiveDegradedError("archive_mount_unavailable") from None
    if (
        not isinstance(volume_proof, ArchiveVolumeReady)
        or not volume_proof.ready
        or volume_proof.archive_ref != archive_ref
    ):
        raise ArchiveDegradedError("archive_mount_unavailable")

    objects, manifests = _ensure_archive_dirs(archive_root)
    hot = _active_hot(record.id)
    ciphertext = hot.ciphertext
    ciphertext_hash = hashlib.sha256(ciphertext).hexdigest()
    representation_id = str(uuid4())
    receipt_id = str(uuid4())
    location_ref = f"heimloc:cold:{representation_id}"
    object_path = objects / f"{representation_id}.bin"
    manifest_written = False
    failure: ArchiveDegradedError | None = None

    try:
        _durable_write(object_path, ciphertext)
        copied = object_path.read_bytes()
        if copied != ciphertext or hashlib.sha256(copied).hexdigest() != ciphertext_hash:
            raise ArchiveDegradedError("archive_copy_verification_failed")
        raw_store.register_cold_location(location_ref, object_path)
        raw_store.decrypt_and_verify_raw_bytes(
            record.content_identity, copied, hot.nonce, key=key or raw_store.resolve_raw_store_key()
        )
        receipt = ArchiveReceipt(
            receipt_id=receipt_id,
            record_id=record.id,
            content_identity=record.content_identity,
            representation_id=representation_id,
            encrypted_bytes=len(copied),
            ciphertext_sha256=ciphertext_hash,
            verified_at=_utc(reference),
        )
        _durable_write(manifests / f"{representation_id}.json", _manifest_payload(receipt))
        manifest_written = True
        cold, _ = raw_store.register_cold_raw_representation(
            record_id=record.id,
            ciphertext=copied,
            nonce=hot.nonce,
            key_ref=hot.key_ref,
            location_ref=location_ref,
            key=key,
            representation_id=representation_id,
        )
        active = raw_store.activate_raw_representation(record.id, cold.id, key=key)
        return ArchiveResult(receipt, ArchiveHealth(True, "ok"), active)
    except ArchiveDegradedError as exc:
        if not manifest_written:
            _discard_uncommitted_object(object_path)
        failure = exc
    except Exception:
        if not manifest_written:
            _discard_uncommitted_object(object_path)
        failure = ArchiveDegradedError("archive_relocation_failed")
    if failure is not None:
        raise failure


__all__ = [
    "ARCHIVE_MINIMUM_AGE_DAYS",
    "ARCHIVE_SCHEMA",
    "ARCHIVE_STORAGE_KIND",
    "ArchiveDegradedError",
    "ArchiveHealth",
    "ArchiveReceipt",
    "ArchiveResult",
    "archive_eligible",
    "eligible_raw_records",
    "relocate_raw_record",
]
