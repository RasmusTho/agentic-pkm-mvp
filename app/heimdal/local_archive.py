"""Verified hot-to-cold relocation for Heimdal raw evidence (HAR-04).

The archive is a storage representation, not a second authority. A record's
opaque ``raw_ref`` and immutable identity stay in the raw store; this module
only copies the encrypted hot bytes, writes a redacted manifest, and then
activates a registered cold representation.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Callable, Mapping, Optional, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.heimdal import raw_liveness, raw_read_gate, raw_store
from app.heimdal.raw_store import RawRecord, RawRepresentation
from app.heimdal.retention import RetentionWindowMissingError, resolve_retention_window_days
from app.ops.heimdal_cold_volume import (
    ArchiveVolumeReady,
    ArchiveVolumeRefusedError,
    load_channel_archive_metadata,
    require_archive_volume_ready,
)

ARCHIVE_SCHEMA = "heimdal_archive_receipt.v1"
ARCHIVE_STORAGE_KIND = "encrypted_local_cold"
ARCHIVE_MINIMUM_AGE_DAYS = 7
DEFAULT_ARCHIVE_PASS_LIMIT = 100

_relocation_stage_hook: Callable[[str], None] = lambda _stage: None


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
    location_ref: str
    archive_token: str
    archive_generation: str
    raw_generation: int
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
            "location_ref": self.location_ref,
            "archive_token": self.archive_token,
            "archive_generation": self.archive_generation,
            "raw_generation": self.raw_generation,
            "encrypted_bytes": self.encrypted_bytes,
            "ciphertext_sha256": self.ciphertext_sha256,
            "verified_at": _iso(self.verified_at),
        }


@dataclass(frozen=True)
class RestoreDrillReceipt:
    """Redacted proof that one cold representation restored through GOV."""

    raw_ref: str
    content_identity: str
    read_receipt_id: str
    verified_at: datetime
    storage_kind: str = ARCHIVE_STORAGE_KIND
    proven: bool = True
    schema: str = "heimdal_archive_restore_drill.v1"

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "proven": self.proven,
            "raw_ref": self.raw_ref,
            "content_identity": self.content_identity,
            "storage_kind": self.storage_kind,
            "read_receipt_id": self.read_receipt_id,
            "verified_at": _iso(self.verified_at),
        }


@dataclass(frozen=True)
class ArchiveResult:
    receipt: ArchiveReceipt
    health: ArchiveHealth
    active_representation: RawRepresentation


@dataclass(frozen=True)
class ArchivePassReceipt:
    """Secret-safe outcome for one bounded production archive pass."""

    ran: bool
    healthy: bool
    reason: str
    eligible_count: int
    selected_count: int
    archived_count: int
    failed_count: int
    deferred_count: int
    failure_reason_counts: tuple[tuple[str, int], ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "ran": self.ran,
            "healthy": self.healthy,
            "reason": self.reason,
            "eligible_count": self.eligible_count,
            "selected_count": self.selected_count,
            "archived_count": self.archived_count,
            "failed_count": self.failed_count,
            "deferred_count": self.deferred_count,
            "failure_reason_counts": dict(self.failure_reason_counts),
        }


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


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
    return ingested < reference - timedelta(
        days=minimum_age_days
    ) and ingested >= reference - timedelta(days=retention_window_days)


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
        and any(
            representation.active and representation.storage_kind == "postgres_hot"
            for representation in raw_store.all_raw_representations(record.id)
        )
    ]


def _ensure_archive_dirs(archive_root: Path) -> tuple[Path, Path]:
    if not archive_root.is_absolute() or not archive_root.is_dir():
        raise ArchiveDegradedError("archive_mount_unavailable")
    objects = archive_root / "representations"
    manifests = archive_root / "manifests"
    mount_error = False
    try:
        objects.mkdir(exist_ok=True)
        manifests.mkdir(exist_ok=True)
    except OSError:
        mount_error = True
    if mount_error:
        raise ArchiveDegradedError("archive_mount_unavailable")
    return objects, manifests


def _discard_uncommitted_object(object_path: Path) -> None:
    try:
        object_path.unlink(missing_ok=True)
    except OSError:
        # A later retry can reconcile an unreadable orphan; never disclose the
        # mounted volume path through an exception or log value.
        return


def _discard_uncommitted_manifest(manifest_path: Path) -> None:
    try:
        manifest_path.unlink(missing_ok=True)
    except OSError:
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
    payload = receipt.as_dict()
    payload["ownership_state"] = "verified"
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _reserved_ownership_manifest_payload(receipt: ArchiveReceipt) -> bytes:
    """Persist exact unlink authority before any cold object can exist."""

    payload = receipt.as_dict()
    payload["ownership_state"] = "reserved"
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _manifest_with_operation(
    payload: bytes,
    operation_binding: Mapping[str, object] | None,
) -> bytes:
    """Bind GAF operation identity inside the existing HAR owner manifest."""

    if operation_binding is None:
        return payload
    parsed = json.loads(payload.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ArchiveDegradedError("archive_manifest_invalid")
    expected = dict(operation_binding)
    existing = parsed.get("gaf_operation")
    if existing is not None and (
        not isinstance(existing, dict)
        or set(existing) != set(expected)
        or any(
            type(existing[field]) is not type(value) or existing[field] != value
            for field, value in expected.items()
        )
    ):
        raise ArchiveDegradedError("archive_manifest_invalid")
    parsed["gaf_operation"] = expected
    return (json.dumps(parsed, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _archive_receipt_from_manifest(payload: Mapping[str, object]) -> ArchiveReceipt:
    """Load exact owner receipt fields for an additive pre-GAF retry."""

    try:
        verified_at = datetime.fromisoformat(
            str(payload["verified_at"]).replace("Z", "+00:00")
        )
        receipt = ArchiveReceipt(
            receipt_id=str(payload["receipt_id"]),
            record_id=str(payload["record_id"]),
            content_identity=str(payload["content_identity"]),
            representation_id=str(payload["representation_id"]),
            location_ref=str(payload["location_ref"]),
            archive_token=str(payload["archive_token"]),
            archive_generation=str(payload["archive_generation"]),
            raw_generation=int(str(payload["raw_generation"])),
            encrypted_bytes=int(str(payload["encrypted_bytes"])),
            ciphertext_sha256=str(payload["ciphertext_sha256"]),
            verified_at=verified_at,
            schema=str(payload["schema"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ArchiveDegradedError("archive_manifest_invalid") from exc
    if str(UUID(receipt.receipt_id)) != receipt.receipt_id or receipt.schema != ARCHIVE_SCHEMA:
        raise ArchiveDegradedError("archive_manifest_invalid")
    return receipt


def _read_archive_manifest(
    manifest_path: Path, *, required: bool
) -> Mapping[str, object] | None:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        if required:
            raise ArchiveDegradedError("archive_manifest_invalid") from exc
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArchiveDegradedError("archive_manifest_invalid") from exc
    if not isinstance(payload, dict):
        raise ArchiveDegradedError("archive_manifest_invalid")
    return payload


def _active_hot(record_id: str) -> RawRepresentation:
    active = [item for item in raw_store.all_raw_representations(record_id) if item.active]
    if len(active) != 1 or active[0].storage_kind != "postgres_hot":
        raise ArchiveDegradedError("hot_representation_unavailable")
    return active[0]


def _pending_cold(
    record_id: str,
    hot: RawRepresentation,
    *,
    archive_ref: str,
    archive_generation: str,
    raw_generation: int,
) -> RawRepresentation | None:
    """Resolve the one retryable durable reservation without reading its object."""

    pending = [
        item
        for item in raw_store.all_raw_representations(record_id)
        if item.storage_kind == ARCHIVE_STORAGE_KIND and not item.active
    ]
    if not pending:
        return None
    if len(pending) != 1:
        raise ArchiveDegradedError("archive_pending_state_invalid")
    candidate = pending[0]
    try:
        canonical_id = str(UUID(candidate.id))
    except (TypeError, ValueError, AttributeError):
        canonical_id = ""
    if (
        canonical_id != candidate.id
        or candidate.location_ref != raw_store._cold_location_ref(archive_ref, candidate.id)  # noqa: SLF001
        or candidate.nonce != hot.nonce
        or candidate.key_ref != hot.key_ref
        or candidate.archive_token != raw_store._archive_binding_token(archive_ref)  # noqa: SLF001
        or candidate.archive_generation != archive_generation
        or candidate.raw_generation != raw_generation
    ):
        raise ArchiveDegradedError("archive_pending_state_invalid")
    return candidate


def _relocate_raw_record_owner_native(
    record: RawRecord,
    *,
    archive_root: Path,
    archive_ref: str,
    now: Optional[datetime] = None,
    retention_window_days: Optional[int] = None,
    vault_root: Optional[Path] = None,
    key: Optional[bytes] = None,
    volume_ready: Callable[[], ArchiveVolumeReady],
    requested_representation_id: str | None = None,
    requested_receipt_id: str | None = None,
    operation_binding: Mapping[str, object] | None = None,
    existing_manifest: Mapping[str, object] | None = None,
) -> ArchiveResult:
    """Copy, verify, receipt, then activate cold; fail closed on every error."""
    reference = now or datetime.now(timezone.utc)
    if retention_window_days is None:
        if vault_root is None:
            raise ArchiveDegradedError("retention_policy_unavailable")
        retention_window_days = resolve_retention_window_days(vault_root)
    if not archive_eligible(record, now=reference, retention_window_days=retention_window_days):
        raise ArchiveDegradedError("record_outside_archive_window")
    callback_failed = False
    volume_proof: ArchiveVolumeReady | object = object()
    try:
        volume_proof = volume_ready()
    except Exception:
        callback_failed = True
    if callback_failed:
        raise ArchiveDegradedError("archive_mount_unavailable")
    if (
        not isinstance(volume_proof, ArchiveVolumeReady)
        or not volume_proof.ready
        or volume_proof.archive_ref != archive_ref
        or volume_proof.mountpoint != archive_root
    ):
        raise ArchiveDegradedError("archive_mount_unavailable")
    raw_store.configure_cold_archive_root(
        archive_root,
        verified_volume=volume_proof,
        expected_archive_ref=archive_ref,
    )

    objects, manifests = _ensure_archive_dirs(archive_root)
    with raw_liveness.raw_relocation_fence(
        record_id=record.id,
        content_identity=record.content_identity,
    ) as mutation_authority:
        hot = _active_hot(record.id)
        ciphertext = hot.ciphertext
        ciphertext_hash = hashlib.sha256(ciphertext).hexdigest()
        pending = _pending_cold(
            record.id,
            hot,
            archive_ref=archive_ref,
            archive_generation=volume_proof.archive_generation,
            raw_generation=mutation_authority.generation,
        )
        representation_id = (
            pending.id
            if pending is not None
            else requested_representation_id or str(uuid4())
        )
        if requested_representation_id is not None and representation_id != requested_representation_id:
            raise ArchiveDegradedError("archive_pending_state_invalid")
        receipt_id = requested_receipt_id or str(uuid4())
        location_ref = raw_store._cold_location_ref(  # noqa: SLF001
            archive_ref,
            representation_id,
        )
        object_path = objects / f"{representation_id}.bin"
        manifest_path = manifests / f"{representation_id}.json"
        # The outer read is only an optimization/receipt hint. Re-read under
        # the record relocation fence so stale evidence can never authorize a
        # replacement manifest or target transition.
        existing_manifest = _read_archive_manifest(
            manifest_path,
            required=pending is not None,
        )
        reservation_durable = False
        activation_started = False
        copied_verified = False
        failure: ArchiveDegradedError | None = None
        receipt = (
            _archive_receipt_from_manifest(existing_manifest)
            if existing_manifest is not None
            else ArchiveReceipt(
                receipt_id=receipt_id,
                record_id=record.id,
                content_identity=record.content_identity,
                representation_id=representation_id,
                location_ref=location_ref,
                archive_token=raw_store._archive_binding_token(archive_ref),  # noqa: SLF001
                archive_generation=volume_proof.archive_generation,
                raw_generation=mutation_authority.generation,
                encrypted_bytes=len(ciphertext),
                ciphertext_sha256=ciphertext_hash,
                verified_at=_utc(reference),
            )
        )
        if (
            receipt.record_id != record.id
            or receipt.content_identity != record.content_identity
            or receipt.representation_id != representation_id
            or receipt.location_ref != location_ref
            or receipt.archive_token != raw_store._archive_binding_token(archive_ref)  # noqa: SLF001
            or receipt.archive_generation != volume_proof.archive_generation
            or receipt.raw_generation != mutation_authority.generation
            or receipt.encrypted_bytes != len(ciphertext)
            or receipt.ciphertext_sha256 != ciphertext_hash
        ):
            raise ArchiveDegradedError("archive_manifest_invalid")

        try:
            with raw_store.cold_archive_mutation_lock(archive_root, verified_volume=volume_proof):
                _relocation_stage_hook("after_archive_lock")
                # Existing HAR manifest authority is also the GAF operation
                # journal. Persist the immutable tuple before reservation or
                # external bytes, without adding a store or sidecar registry.
                _durable_write(
                    manifest_path,
                    _manifest_with_operation(
                        (
                            (
                                json.dumps(
                                    dict(existing_manifest),
                                    sort_keys=True,
                                    separators=(",", ":"),
                                )
                                + "\n"
                            ).encode()
                            if existing_manifest is not None
                            else _reserved_ownership_manifest_payload(receipt)
                        ),
                        operation_binding,
                    ),
                )
                _relocation_stage_hook("after_operation_binding")
                raw_store.register_cold_location(
                    location_ref,
                    object_path,
                    verified_volume=volume_proof,
                    raw_generation=mutation_authority.generation,
                    representation_id=representation_id,
                )
                try:
                    cold, _ = raw_store.register_cold_raw_representation(
                        record_id=record.id,
                        ciphertext=ciphertext,
                        nonce=hot.nonce,
                        key_ref=hot.key_ref,
                        location_ref=location_ref,
                        key=key,
                        representation_id=representation_id,
                        verified_volume=volume_proof,
                        _authority=mutation_authority,
                    )
                    # The registration call has crossed the commit boundary.
                    # Preserve its operation manifest even if the following
                    # checkpoint commits and raises before acknowledging it.
                    reservation_durable = True
                    raw_liveness._checkpoint_raw_mutation_authority(  # noqa: SLF001
                        mutation_authority
                    )
                    _relocation_stage_hook("after_reservation")
                    if (
                        existing_manifest is None
                        or existing_manifest.get("ownership_state") != "verified"
                    ):
                        _durable_write(object_path, ciphertext)
                    _relocation_stage_hook("after_object_write")
                    copied = object_path.read_bytes()
                    if (
                        copied != ciphertext
                        or hashlib.sha256(copied).hexdigest() != ciphertext_hash
                    ):
                        raise ArchiveDegradedError("archive_copy_verification_failed")
                    raw_store.decrypt_and_verify_raw_bytes(
                        record.content_identity,
                        copied,
                        hot.nonce,
                        key=key or raw_store.resolve_raw_store_key(),
                    )
                    copied_verified = True
                    _durable_write(
                        manifest_path,
                        _manifest_with_operation(
                            _manifest_payload(receipt),
                            operation_binding,
                        ),
                    )
                    _relocation_stage_hook("after_manifest_write")
                    activation_started = True
                    active = raw_store.activate_raw_representation(
                        record.id,
                        cold.id,
                        key=key,
                        _authority=mutation_authority,
                    )
                    _relocation_stage_hook("after_activation")
                    return ArchiveResult(receipt, ArchiveHealth(True, "ok"), active)
                except ArchiveDegradedError as exc:
                    failure = exc
                except Exception:
                    failure = ArchiveDegradedError("archive_relocation_failed")

                # Before activation starts, hot remains authoritative and
                # external artifacts can be removed safely. Keep the durable
                # inactive reservation so retry and retention retain cleanup
                # authority. Once activation starts its commit may be
                # ambiguous, so preserve verified bytes.
                if not activation_started:
                    if not copied_verified:
                        _discard_uncommitted_object(object_path)
                    if not reservation_durable:
                        _discard_uncommitted_manifest(manifest_path)
                if failure is not None:
                    raise failure
        except ArchiveDegradedError as exc:
            failure = exc
        except Exception:
            failure = ArchiveDegradedError("archive_relocation_failed")

        if not reservation_durable:
            raw_store.discard_cold_location(location_ref)
        if failure is not None:
            raise failure


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
    """Run HAR-04's owner-native atomic relocation through the public GAF kernel."""

    from app.archival.adapters.heimdal import HeimdalRawMediaAdapter
    from app.archival.contracts import TransitionStage
    from app.archival.transition import ArchivalTransitionKernel

    representations = raw_store.all_raw_representations(record.id)
    hot = next(
        (
            item
            for item in representations
            if item.active and item.storage_kind == "postgres_hot"
        ),
        None,
    )
    active_cold = next(
        (
            item
            for item in representations
            if item.active and item.storage_kind == ARCHIVE_STORAGE_KIND
        ),
        None,
    )
    source_hot = hot or next(
        (item for item in representations if item.storage_kind == "postgres_hot"),
        None,
    )
    if source_hot is None or (hot is None and active_cold is None):
        raise ArchiveDegradedError("hot_representation_unavailable")
    pending = [
        item
        for item in representations
        if item.storage_kind == ARCHIVE_STORAGE_KIND and not item.active
    ]
    if len(pending) > 1:
        raise ArchiveDegradedError("archive_pending_state_invalid")
    deterministic_target_id = str(
        uuid5(
            NAMESPACE_URL,
            f"heimdal-archive:{record.id}:{source_hot.raw_generation}:{archive_ref}",
        )
    )
    target_id = (
        active_cold.id
        if active_cold is not None
        else pending[0].id
        if pending
        else deterministic_target_id
    )

    def read_operation_manifest(representation_id: str) -> Mapping[str, object] | None:
        manifest_path = archive_root / "manifests" / f"{representation_id}.json"
        registered_target = any(
            item.id == representation_id
            and item.storage_kind == ARCHIVE_STORAGE_KIND
            for item in raw_store.all_raw_representations(record.id)
        )
        return _read_archive_manifest(manifest_path, required=registered_target)

    def owner_action(
        representation_id: str,
        receipt_id: str,
        operation_binding: Mapping[str, object],
        existing_manifest: Mapping[str, object] | None,
    ) -> ArchiveResult:
        return _relocate_raw_record_owner_native(
            record,
            archive_root=archive_root,
            archive_ref=archive_ref,
            now=now,
            retention_window_days=retention_window_days,
            vault_root=vault_root,
            key=key,
            volume_ready=volume_ready,
            requested_representation_id=representation_id,
            requested_receipt_id=receipt_id,
            operation_binding=operation_binding,
            existing_manifest=existing_manifest,
        )

    adapter = HeimdalRawMediaAdapter(
        record,
        generation=source_hot.raw_generation,
        archive_action=owner_action,
        operation_reader=read_operation_manifest,
    )
    source = adapter.ref_for(source_hot)
    target = adapter.ref_for(target_id)
    idempotency_key = f"heimdal-raw-archive:{record.id}:{source_hot.raw_generation}:{target_id}"
    outcome = ArchivalTransitionKernel(adapter).transition(
        adapter.artifact,
        source,
        target,
        idempotency_key,
    )
    if outcome.stage is not TransitionStage.RETIRED:
        operation = adapter.read_operation(idempotency_key)
        if operation is None or not operation.completed:
            raise ArchiveDegradedError(adapter.failure_reason or "archive_relocation_failed")
    if adapter.archive_result is None:
        owner_receipt = adapter.owner_archive_receipt
        current_active_cold = next(
            (
                item
                for item in raw_store.all_raw_representations(record.id)
                if item.active and item.storage_kind == ARCHIVE_STORAGE_KIND
            ),
            None,
        )
        if owner_receipt is None or current_active_cold is None:
            raise ArchiveDegradedError("archive_relocation_failed")
        return ArchiveResult(
            cast(ArchiveReceipt, owner_receipt),
            ArchiveHealth(True, "ok"),
            current_active_cold,
        )
    return cast(ArchiveResult, adapter.archive_result)


def _pass_receipt(
    *,
    ran: bool,
    healthy: bool,
    reason: str,
    eligible_count: int = 0,
    selected_count: int = 0,
    archived_count: int = 0,
    failed_count: int = 0,
    deferred_count: int = 0,
    failure_reasons: Counter[str] | None = None,
) -> ArchivePassReceipt:
    return ArchivePassReceipt(
        ran=ran,
        healthy=healthy,
        reason=reason,
        eligible_count=eligible_count,
        selected_count=selected_count,
        archived_count=archived_count,
        failed_count=failed_count,
        deferred_count=deferred_count,
        failure_reason_counts=tuple(sorted((failure_reasons or Counter()).items())),
    )


def _redacted_failure_reason(error: ArchiveDegradedError) -> str:
    if re.fullmatch(r"[a-z0-9_]+", error.reason):
        return error.reason
    return "archive_relocation_failed"


def run_restore_drill(
    raw_ref: str,
    *,
    reader: str,
    key: Optional[bytes] = None,
) -> RestoreDrillReceipt:
    """Restore one archived identity through the production gated read path.

    Authorization and the durable read receipt are deliberately delegated to
    :func:`raw_read_gate.read_raw_record`; this function never resolves cold
    bytes directly.  The returned evidence contains only opaque identity and
    receipt fields, never plaintext or a filesystem path.
    """

    from app.archival.adapters.heimdal import HeimdalRawMediaAdapter
    from app.archival.contracts import AccessAuthority, OpaqueReference, OwnerAuthority
    from app.archival.transition import ArchivalTransitionKernel

    record_id = raw_read_gate._record_id_from_raw_ref(raw_ref)  # noqa: SLF001
    record = raw_store.resolve_active_raw_record(record_id)
    if record is None:
        raise raw_read_gate.RawReadRefusedError(
            f"raw_ref {raw_ref!r} does not resolve to active raw evidence"
        )
    active = [item for item in raw_store.all_raw_representations(record.id) if item.active]
    if len(active) != 1:
        raise ArchiveDegradedError("archived_representation_unavailable")
    adapter = HeimdalRawMediaAdapter(
        record,
        generation=active[0].raw_generation,
        read_key=key,
    )
    authority = AccessAuthority(
        OwnerAuthority.CLASS_ADAPTER,
        OpaqueReference("heimdal-reader", reader),
    )
    outcome = ArchivalTransitionKernel(adapter).restore(
        adapter.artifact,
        authority,
        adapter.ref_for(active[0]),
    )
    if outcome.receipt is None:
        raise ArchiveDegradedError("restore_identity_mismatch")
    if adapter.restored_storage_kind != ARCHIVE_STORAGE_KIND:
        raise ArchiveDegradedError("archived_representation_unavailable")
    read_receipt_id = outcome.receipt.receipt_ref.token
    owner_receipt = next(
        (
            receipt
            for receipt in raw_read_gate.all_raw_read_receipts()
            if receipt.id == read_receipt_id
        ),
        None,
    )
    if owner_receipt is None:
        raise ArchiveDegradedError("restore_identity_mismatch")
    return RestoreDrillReceipt(
        raw_ref=raw_ref,
        content_identity=owner_receipt.content_identity,
        read_receipt_id=owner_receipt.id,
        verified_at=owner_receipt.read_at,
    )


def run_archive_pass(
    *,
    vault_root: Path,
    config_root: Path,
    channel: str,
    now: Optional[datetime] = None,
    max_records: int = DEFAULT_ARCHIVE_PASS_LIMIT,
) -> ArchivePassReceipt:
    """Relocate one bounded batch through the channel-governed volume authority.

    This is HAR-04's production one-shot scheduler boundary.  It holds the raw
    store's cross-process run lease, revalidates the encrypted volume before
    every external write, continues past record-local failures, and reports
    only counts plus closed reason codes.  A later invocation retries every
    record whose hot representation remains active.
    """
    if type(max_records) is not int or max_records <= 0:
        raise ValueError("max_records must be a positive integer")
    reference = now or datetime.now(timezone.utc)

    try:
        with raw_store.archive_relocation_lease():
            try:
                metadata = load_channel_archive_metadata(
                    config_root=config_root,
                    channel=channel,
                )
                require_archive_volume_ready(metadata, expected_channel=channel)
            except ArchiveVolumeRefusedError:
                return _pass_receipt(
                    ran=True,
                    healthy=False,
                    reason="archive_mount_unavailable",
                )

            try:
                retention_window_days = resolve_retention_window_days(vault_root)
            except RetentionWindowMissingError:
                return _pass_receipt(
                    ran=True,
                    healthy=False,
                    reason="retention_policy_unavailable",
                )

            if retention_window_days <= ARCHIVE_MINIMUM_AGE_DAYS:
                return _pass_receipt(
                    ran=True,
                    healthy=True,
                    reason="ok",
                )

            reference_utc = _utc(reference)
            try:
                batch, eligible_count = raw_store.archive_eligible_hot_raw_records(
                    ingested_before=reference_utc - timedelta(days=ARCHIVE_MINIMUM_AGE_DAYS),
                    ingested_at_or_after=reference_utc - timedelta(days=retention_window_days),
                    limit=max_records,
                )
            except Exception:
                return _pass_receipt(
                    ran=True,
                    healthy=False,
                    reason="archive_selection_failed",
                )

            archived_count = 0
            failure_reasons: Counter[str] = Counter()
            for record in batch:
                try:
                    relocate_raw_record(
                        record,
                        archive_root=metadata.mountpoint,
                        archive_ref=metadata.archive_id,
                        now=reference,
                        retention_window_days=retention_window_days,
                        volume_ready=lambda: require_archive_volume_ready(
                            metadata,
                            expected_channel=channel,
                        ),
                    )
                    archived_count += 1
                except ArchiveDegradedError as exc:
                    failure_reasons[_redacted_failure_reason(exc)] += 1
                except Exception:
                    failure_reasons["archive_relocation_failed"] += 1

            failed_count = sum(failure_reasons.values())
            return _pass_receipt(
                ran=True,
                healthy=failed_count == 0,
                reason="ok" if failed_count == 0 else "archive_relocation_degraded",
                eligible_count=eligible_count,
                selected_count=len(batch),
                archived_count=archived_count,
                failed_count=failed_count,
                deferred_count=eligible_count - len(batch),
                failure_reasons=failure_reasons,
            )
    except raw_store.RawArchiveRelocationLeaseUnavailableError:
        return _pass_receipt(
            ran=False,
            healthy=False,
            reason="archive_pass_already_running",
        )


__all__ = [
    "ARCHIVE_MINIMUM_AGE_DAYS",
    "ARCHIVE_SCHEMA",
    "ARCHIVE_STORAGE_KIND",
    "DEFAULT_ARCHIVE_PASS_LIMIT",
    "ArchiveDegradedError",
    "ArchiveHealth",
    "ArchivePassReceipt",
    "ArchiveReceipt",
    "ArchiveResult",
    "RestoreDrillReceipt",
    "archive_eligible",
    "eligible_raw_records",
    "relocate_raw_record",
    "run_archive_pass",
    "run_restore_drill",
]
