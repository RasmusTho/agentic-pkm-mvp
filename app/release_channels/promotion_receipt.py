"""Durable promotion-test receipts and prod activation admission.

This module deliberately stops at admission.  It never deploys, migrates,
restarts, or activates a channel.  The promotion-test writer persists one
content-addressed PASS/FAIL receipt per attempt outside resettable test roots;
the prod entrypoint validates that immutable evidence before a separate caller
may activate anything.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from app.release_channels.channel_manifest import (
    ArtifactRenderError,
    create_promotion_candidate,
)
from app.release_channels.reversibility import (
    MigrationMarkerError,
    check_migration_snapshots,
)


RECEIPT_VERSION = "promotion-receipt.v1"
REGISTRY_VERSION = "promotion-receipt-registry.v1"
ATTEMPT_VERSION = "promotion-test-attempt.v1"
RESERVATION_VERSION = "promotion-test-reservation.v1"
REPORT_VERSION = "promotion-test-check-report.v1"
REQUIRED_CHECKS = ("migration", "readiness", "schema", "smoke", "ui", "version")
_OBSERVED_CHECKS = REQUIRED_CHECKS[1:]
_RECEIPT_FIELDS = {
    "receipt_version",
    "receipt_id",
    "outcome",
    "artifact_digest",
    "config_identity",
    "test_identity",
    "vault_identity",
    "schema_identity",
    "required_checks",
    "issued_at",
    "fresh_until",
    "issuer_id",
    "issuer_key_id",
    "issuer_signature",
}
_IDENTITY_FIELDS = {
    "artifact_digest",
    "config_identity",
    "test_identity",
    "vault_identity",
    "schema_identity",
}
_REGISTRY_FIELDS = {"registry_version", "trusted_keys", "entries"}
_REGISTRY_ENTRY_FIELDS = {
    "issuer_id",
    "issuer_key_id",
    "public_key",
    "issuer_signature",
    "status",
}
_ATTEMPT_FIELDS = {
    "attempt_version",
    "attempt_id",
    "candidate_identity",
    "check_report_identity",
    "receipt_id",
    "outcome",
    "identity",
    "check_results",
    "migration_classification",
}
_RESERVATION_FIELDS = {
    "reservation_version",
    "attempt_id",
    "receipt_id",
    "outcome",
    "intent_digest",
}
_REPORT_FIELDS = {
    "report_version",
    "candidate_identity",
    "identity",
    "check_results",
    "migration_set_identity",
}
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ATTEMPT_ID = re.compile(r"pt-[0-9a-f]{32}\Z")
_TEST_IDENTITY = re.compile(r"promotion-test:[0-9]{8}\Z")
_VAULT_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_SCHEMA_IDENTITY = re.compile(r"alembic:[A-Za-z0-9._-]+\Z")
_ISSUER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_B64URL = re.compile(r"[A-Za-z0-9_-]+\Z")
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")


class PromotionReceiptError(RuntimeError):
    """A receipt cannot be produced or accepted without weakening authority."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)

    def as_dict(self) -> dict[str, str]:
        return {"error": self.code}


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise PromotionReceiptError("invalid_shape") from exc


def _mapping(value: object, *, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise PromotionReceiptError(code)
    return value


def _canonical_b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_canonical_b64url(value: object, *, length: int, code: str) -> bytes:
    if not isinstance(value, str) or _B64URL.fullmatch(value) is None or len(value) % 4 == 1:
        raise PromotionReceiptError(code)
    try:
        raw = base64.urlsafe_b64decode(value + "=" * ((4 - len(value) % 4) % 4))
    except (ValueError, binascii.Error) as exc:
        raise PromotionReceiptError(code) from exc
    if len(raw) != length or _canonical_b64url(raw) != value:
        raise PromotionReceiptError(code)
    return raw


def _timestamp(value: datetime, *, code: str) -> str:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise PromotionReceiptError(code)
    normalized = value.astimezone(timezone.utc)
    if normalized.microsecond:
        raise PromotionReceiptError(code)
    return normalized.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_timestamp(value: object, *, code: str) -> datetime:
    if not isinstance(value, str) or _TIMESTAMP.fullmatch(value) is None:
        raise PromotionReceiptError(code)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PromotionReceiptError(code) from exc
    return parsed


def _validate_identity(value: object) -> dict[str, str]:
    identity = _mapping(value, code="identity_invalid")
    if set(identity) != _IDENTITY_FIELDS:
        raise PromotionReceiptError("identity_invalid")
    artifact_digest = identity.get("artifact_digest")
    config_identity = identity.get("config_identity")
    test_identity = identity.get("test_identity")
    vault_identity = identity.get("vault_identity")
    schema_identity = identity.get("schema_identity")
    if not isinstance(artifact_digest, str) or _DIGEST.fullmatch(artifact_digest) is None:
        raise PromotionReceiptError("identity_invalid")
    if not isinstance(config_identity, str) or _DIGEST.fullmatch(config_identity) is None:
        raise PromotionReceiptError("identity_invalid")
    if not isinstance(test_identity, str) or _TEST_IDENTITY.fullmatch(test_identity) is None:
        raise PromotionReceiptError("identity_invalid")
    if not isinstance(vault_identity, str) or _VAULT_IDENTITY.fullmatch(vault_identity) is None:
        raise PromotionReceiptError("identity_invalid")
    if not isinstance(schema_identity, str) or _SCHEMA_IDENTITY.fullmatch(schema_identity) is None:
        raise PromotionReceiptError("identity_invalid")
    return {field: str(identity[field]) for field in sorted(_IDENTITY_FIELDS)}


def _validate_checks(value: object) -> dict[str, bool]:
    checks = _mapping(value, code="check_results_invalid")
    if set(checks) != set(_OBSERVED_CHECKS) or any(
        type(result) is not bool for result in checks.values()
    ):
        raise PromotionReceiptError("check_results_invalid")
    return {name: bool(checks[name]) for name in _OBSERVED_CHECKS}


def _capture_migration_snapshots(paths: Sequence[Path]) -> tuple[tuple[str, bytes], ...]:
    snapshots: list[tuple[str, bytes]] = []
    names: set[str] = set()
    for path in paths:
        if path.name in names or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.py", path.name) is None:
            raise PromotionReceiptError("migration_paths_invalid")
        descriptor = -1
        try:
            descriptor = os.open(
                path,
                os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            )
            info = os.fstat(descriptor)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            named_info = path.stat(follow_symlinks=False)
        except OSError as exc:
            raise PromotionReceiptError("migration_paths_invalid") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or (named_info.st_dev, named_info.st_ino) != (info.st_dev, info.st_ino)
        ):
            raise PromotionReceiptError("migration_paths_invalid")
        names.add(path.name)
        snapshots.append((path.name, b"".join(chunks)))
    return tuple(snapshots)


def _migration_set_identity(snapshots: Sequence[tuple[str, bytes]]) -> str:
    records: list[dict[str, str]] = []
    for name, content in snapshots:
        digest = hashlib.sha256(content).hexdigest()
        records.append({"migration": name, "digest": f"sha256:{digest}"})
    return "sha256:" + hashlib.sha256(
        _canonical_bytes(sorted(records, key=lambda record: record["migration"]))
    ).hexdigest()


def _validate_migration_paths(value: object) -> tuple[Path, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or any(
        not isinstance(path, Path) for path in value
    ):
        raise PromotionReceiptError("migration_paths_invalid")
    return tuple(value)


def _derive_candidate_identity(
    *,
    rendered: Mapping[str, object],
    channel_manifest: Mapping[str, object],
    prod_admission_context: Mapping[str, str],
) -> tuple[dict[str, object], dict[str, str]]:
    try:
        candidate = create_promotion_candidate(rendered, channel_manifest)
    except ArtifactRenderError as exc:
        raise PromotionReceiptError("candidate_invalid") from exc
    if candidate.get("channel") != "promotion-test":
        raise PromotionReceiptError("candidate_invalid")
    graph = _mapping(candidate.get("artifact_graph"), code="candidate_invalid")
    image_index = graph.get("image_index")
    config_identity = graph.get("config_identity")
    schema_identity = graph.get("migration_identity")
    if not isinstance(image_index, str) or "@" not in image_index:
        raise PromotionReceiptError("candidate_invalid")
    candidate_bound_identity = _validate_identity(prod_admission_context)
    for field, expected in (
        ("artifact_digest", image_index.rsplit("@", 1)[1]),
        ("config_identity", config_identity),
        ("schema_identity", schema_identity),
    ):
        if candidate_bound_identity[field] != expected:
            raise PromotionReceiptError("candidate_identity_mismatch")
    return candidate, candidate_bound_identity


def build_promotion_test_check_report(
    *,
    rendered: Mapping[str, object],
    channel_manifest: Mapping[str, object],
    prod_admission_context: Mapping[str, str],
    check_results: Mapping[str, bool],
    migration_paths: Sequence[Path],
) -> dict[str, object]:
    """Bind runner observations to one immutable candidate and migration set."""
    validated_paths = _validate_migration_paths(migration_paths)
    migration_snapshots = _capture_migration_snapshots(validated_paths)
    candidate, identity = _derive_candidate_identity(
        rendered=rendered,
        channel_manifest=channel_manifest,
        prod_admission_context=prod_admission_context,
    )
    return {
        "report_version": REPORT_VERSION,
        "candidate_identity": candidate["candidate_identity"],
        "identity": identity,
        "check_results": _validate_checks(check_results),
        "migration_set_identity": _migration_set_identity(migration_snapshots),
    }


def _bind_promotion_test_report(
    *,
    rendered: Mapping[str, object],
    channel_manifest: Mapping[str, object],
    prod_admission_context: Mapping[str, str],
    check_report: Mapping[str, object],
    migration_snapshots: Sequence[tuple[str, bytes]],
) -> tuple[dict[str, str], dict[str, bool], dict[str, object]]:
    candidate, candidate_bound_identity = _derive_candidate_identity(
        rendered=rendered,
        channel_manifest=channel_manifest,
        prod_admission_context=prod_admission_context,
    )

    report = _mapping(check_report, code="check_report_invalid")
    if set(report) != _REPORT_FIELDS or report.get("report_version") != REPORT_VERSION:
        raise PromotionReceiptError("check_report_invalid")
    candidate_identity = report.get("candidate_identity")
    if candidate_identity != candidate.get("candidate_identity"):
        raise PromotionReceiptError("check_report_candidate_mismatch")
    report_identity = _validate_identity(report.get("identity"))
    if report_identity != candidate_bound_identity:
        raise PromotionReceiptError("check_report_identity_mismatch")
    migration_set_identity = report.get("migration_set_identity")
    if migration_set_identity != _migration_set_identity(migration_snapshots):
        raise PromotionReceiptError("check_report_migration_mismatch")
    validated_checks = _validate_checks(report.get("check_results"))
    validated_report: dict[str, object] = {
        "report_version": REPORT_VERSION,
        "candidate_identity": candidate_identity,
        "identity": report_identity,
        "check_results": validated_checks,
        "migration_set_identity": migration_set_identity,
    }
    return candidate_bound_identity, validated_checks, validated_report


def _receipt_unsigned_payload(receipt: Mapping[str, object]) -> bytes:
    return _canonical_bytes(
        {
            key: value
            for key, value in receipt.items()
            if key not in {"receipt_id", "issuer_signature"}
        }
    )


def _receipt_digest_payload(receipt: Mapping[str, object]) -> bytes:
    return _canonical_bytes({key: value for key, value in receipt.items() if key != "receipt_id"})


def _build_receipt(
    *,
    identity: Mapping[str, str],
    outcome: str,
    issued_at: datetime,
    fresh_until: datetime,
    issuer_id: str,
    issuer_key_id: str,
    signer: Callable[[bytes], bytes],
    issuer_public_key: bytes,
) -> dict[str, object]:
    if outcome not in {"PASS", "FAIL"}:
        raise PromotionReceiptError("outcome_invalid")
    if _ISSUER_ID.fullmatch(issuer_id) is None or _ISSUER_ID.fullmatch(issuer_key_id) is None:
        raise PromotionReceiptError("issuer_invalid")
    if not isinstance(issuer_public_key, bytes) or len(issuer_public_key) != 32:
        raise PromotionReceiptError("issuer_key_invalid")
    issued = _timestamp(issued_at, code="issued_at_invalid")
    fresh = _timestamp(fresh_until, code="fresh_until_invalid")
    if issued_at >= fresh_until:
        raise PromotionReceiptError("freshness_window_invalid")
    receipt: dict[str, object] = {
        "receipt_version": RECEIPT_VERSION,
        "outcome": outcome,
        **identity,
        "required_checks": list(REQUIRED_CHECKS),
        "issued_at": issued,
        "fresh_until": fresh,
        "issuer_id": issuer_id,
        "issuer_key_id": issuer_key_id,
    }
    unsigned_payload = _receipt_unsigned_payload(receipt)
    try:
        signature = signer(unsigned_payload)
    except Exception as exc:
        raise PromotionReceiptError("receipt_signing_failed") from exc
    if not isinstance(signature, bytes) or len(signature) != 64:
        raise PromotionReceiptError("receipt_signing_failed")
    try:
        Ed25519PublicKey.from_public_bytes(issuer_public_key).verify(signature, unsigned_payload)
    except (ValueError, InvalidSignature) as exc:
        raise PromotionReceiptError("receipt_signing_failed") from exc
    receipt["issuer_signature"] = "ed25519:v1:" + _canonical_b64url(signature)
    receipt["receipt_id"] = "sha256:" + hashlib.sha256(
        _receipt_digest_payload(receipt)
    ).hexdigest()
    return receipt


def _validate_private_directory(path: Path) -> None:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise PromotionReceiptError("receipt_store_unavailable") from exc
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise PromotionReceiptError("unsafe_receipt_store")


def _durable_mkdir(path: Path) -> None:
    if path.exists():
        try:
            _fsync_directory(path.parent)
        except OSError as exc:
            raise PromotionReceiptError("receipt_store_unavailable") from exc
        return
    missing: list[Path] = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    try:
        _fsync_directory(cursor.parent)
    except OSError as exc:
        raise PromotionReceiptError("receipt_store_unavailable") from exc
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
        except OSError as exc:
            raise PromotionReceiptError("receipt_store_unavailable") from exc
        try:
            _fsync_directory(directory.parent)
        except OSError as exc:
            raise PromotionReceiptError("receipt_store_unavailable") from exc


def _prepare_store(
    receipt_store: Path,
    resettable_roots: Sequence[Path],
) -> tuple[Path, Path, Path, Path]:
    if not isinstance(receipt_store, Path) or not receipt_store.is_absolute():
        raise PromotionReceiptError("receipt_store_must_be_absolute")
    requested = Path(os.path.abspath(receipt_store))
    resolved_store = requested.resolve(strict=False)
    if resolved_store != requested:
        raise PromotionReceiptError("unsafe_receipt_store")
    for root in resettable_roots:
        if not isinstance(root, Path) or not root.is_absolute():
            raise PromotionReceiptError("resettable_root_must_be_absolute")
        resolved_root = root.resolve(strict=False)
        if resolved_store == resolved_root or resolved_root in resolved_store.parents:
            raise PromotionReceiptError("resettable_receipt_store")
    try:
        _durable_mkdir(receipt_store)
        if receipt_store.resolve(strict=True) != receipt_store:
            raise PromotionReceiptError("unsafe_receipt_store")
        _validate_private_directory(receipt_store)
        receipts = receipt_store / "receipts"
        attempts = receipt_store / "attempts"
        reservations = receipt_store / "reservations"
        _durable_mkdir(receipts)
        _durable_mkdir(attempts)
        _durable_mkdir(reservations)
    except OSError as exc:
        raise PromotionReceiptError("receipt_store_unavailable") from exc
    for directory in (receipt_store, receipts, attempts, reservations):
        if directory.resolve(strict=True) != directory:
            raise PromotionReceiptError("unsafe_receipt_store")
        _validate_private_directory(directory)
    return receipt_store, receipts, attempts, reservations


def _write_all(descriptor: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(descriptor, data[offset:])
        if written <= 0:
            raise OSError("write made no progress")
        offset += written


def _write_temp(path: Path, data: bytes) -> Path:
    temp = path.parent / f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(temp, flags, 0o600)
    try:
        _write_all(descriptor, data)
        os.fsync(descriptor)
    except Exception:
        os.close(descriptor)
        temp.unlink(missing_ok=True)
        raise
    os.close(descriptor)
    return temp


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fence_receipt_store(path: Path) -> None:
    try:
        _fsync_directory(path)
    except OSError as exc:
        raise PromotionReceiptError("receipt_store_io_failure") from exc


def _read_canonical_file(path: Path, *, code: str) -> dict[str, object]:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        info = os.fstat(descriptor)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
        named_info = path.stat(follow_symlinks=False)
        value = json.loads(data, object_pairs_hook=_reject_duplicate_keys)
    except (OSError, json.JSONDecodeError, PromotionReceiptError) as exc:
        raise PromotionReceiptError(code) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
        or (named_info.st_dev, named_info.st_ino) != (info.st_dev, info.st_ino)
        or _canonical_bytes(value) != data
        or not isinstance(value, dict)
    ):
        raise PromotionReceiptError(code)
    return value


def _recover_linked_temp(path: Path, *, code: str) -> None:
    """Remove only writer temp names hard-linked to an already published inode."""
    try:
        target = path.stat(follow_symlinks=False)
        candidates = tuple(path.parent.glob(f".{path.name}.*.tmp"))
        removed = False
        for candidate in candidates:
            info = candidate.stat(follow_symlinks=False)
            if (
                stat.S_ISREG(info.st_mode)
                and info.st_uid == os.geteuid()
                and (info.st_dev, info.st_ino) == (target.st_dev, target.st_ino)
            ):
                candidate.unlink()
                removed = True
        if removed:
            _fsync_directory(path.parent)
    except OSError as exc:
        raise PromotionReceiptError(code) from exc


def _unlink_temp(path: Path) -> None:
    path.unlink(missing_ok=True)


def _install_content_addressed(path: Path, data: bytes) -> None:
    if path.exists():
        _recover_linked_temp(path, code="receipt_store_corrupt")
        if _read_canonical_file(path, code="receipt_store_corrupt") != json.loads(data):
            raise PromotionReceiptError("receipt_store_corrupt")
        try:
            _fsync_directory(path.parent)
        except OSError as exc:
            raise PromotionReceiptError("receipt_store_io_failure") from exc
        return
    temp = _write_temp(path, data)
    try:
        try:
            os.link(temp, path, follow_symlinks=False)
        except FileExistsError:
            _unlink_temp(temp)
            _recover_linked_temp(path, code="receipt_store_corrupt")
            if _read_canonical_file(path, code="receipt_store_corrupt") != json.loads(data):
                raise PromotionReceiptError("receipt_store_corrupt")
        else:
            _unlink_temp(temp)
        _fsync_directory(path.parent)
    except OSError as exc:
        raise PromotionReceiptError("receipt_store_io_failure") from exc
    finally:
        _unlink_temp(temp)


def _install_immutable_record(path: Path, data: bytes, *, code: str) -> None:
    if path.exists():
        _recover_linked_temp(path, code=code)
        if _read_canonical_file(path, code=code) != json.loads(data):
            raise PromotionReceiptError(code)
        try:
            _fsync_directory(path.parent)
        except OSError as exc:
            raise PromotionReceiptError("receipt_store_io_failure") from exc
        return
    temp = _write_temp(path, data)
    try:
        try:
            os.link(temp, path, follow_symlinks=False)
        except FileExistsError:
            _unlink_temp(temp)
            _recover_linked_temp(path, code=code)
            if _read_canonical_file(path, code=code) != json.loads(data):
                raise PromotionReceiptError(code)
        else:
            _unlink_temp(temp)
        _fsync_directory(path.parent)
    except OSError as exc:
        raise PromotionReceiptError("receipt_store_io_failure") from exc
    finally:
        _unlink_temp(temp)


def _validate_registry_update_shape(registry: Mapping[str, object]) -> None:
    if set(registry) != _REGISTRY_FIELDS or registry.get("registry_version") != REGISTRY_VERSION:
        raise PromotionReceiptError("registry_corrupt")
    trusted_keys = _mapping(registry.get("trusted_keys"), code="registry_corrupt")
    entries = _mapping(registry.get("entries"), code="registry_corrupt")
    for key_id, public_key in trusted_keys.items():
        if _ISSUER_ID.fullmatch(key_id) is None:
            raise PromotionReceiptError("registry_corrupt")
        _decode_canonical_b64url(
            public_key,
            length=32,
            code="registry_corrupt",
        )
    for receipt_id, raw_entry in entries.items():
        if _DIGEST.fullmatch(receipt_id) is None:
            raise PromotionReceiptError("registry_corrupt")
        entry = _mapping(raw_entry, code="registry_corrupt")
        if set(entry) != _REGISTRY_ENTRY_FIELDS or entry.get("status") not in {
            "issued",
            "revoked",
        }:
            raise PromotionReceiptError("registry_corrupt")
        issuer_id = entry.get("issuer_id")
        issuer_key_id = entry.get("issuer_key_id")
        public_key = entry.get("public_key")
        signature = entry.get("issuer_signature")
        if (
            not isinstance(issuer_id, str)
            or _ISSUER_ID.fullmatch(issuer_id) is None
            or not isinstance(issuer_key_id, str)
            or _ISSUER_ID.fullmatch(issuer_key_id) is None
            or trusted_keys.get(issuer_key_id) != public_key
            or not isinstance(signature, str)
            or not signature.startswith("ed25519:v1:")
        ):
            raise PromotionReceiptError("registry_corrupt")
        _decode_canonical_b64url(public_key, length=32, code="registry_corrupt")
        _decode_canonical_b64url(
            signature.removeprefix("ed25519:v1:"),
            length=64,
            code="registry_corrupt",
        )


def _publish_registry_entry(
    path: Path,
    *,
    receipt: Mapping[str, object],
    issuer_public_key: bytes,
) -> dict[str, object]:
    receipt_id = str(receipt["receipt_id"])
    issuer_key_id = str(receipt["issuer_key_id"])
    public_key = _canonical_b64url(issuer_public_key)
    entry: dict[str, object] = {
        "issuer_id": receipt["issuer_id"],
        "issuer_key_id": issuer_key_id,
        "public_key": public_key,
        "issuer_signature": receipt["issuer_signature"],
        "status": "issued",
    }
    if not path.exists():
        initial: dict[str, object] = {
            "registry_version": REGISTRY_VERSION,
            "trusted_keys": {issuer_key_id: public_key},
            "entries": {receipt_id: entry},
        }
        _install_immutable_record(
            path,
            _canonical_bytes(initial),
            code="registry_conflict",
        )
        return initial

    _recover_linked_temp(path, code="registry_corrupt")
    existing = _read_canonical_file(path, code="registry_corrupt")
    _validate_registry_update_shape(existing)
    trusted_keys = dict(
        _mapping(existing["trusted_keys"], code="registry_corrupt")
    )
    entries = dict(_mapping(existing["entries"], code="registry_corrupt"))
    current_key = trusted_keys.get(issuer_key_id)
    if current_key is not None and current_key != public_key:
        raise PromotionReceiptError("registry_key_conflict")
    current_entry = entries.get(receipt_id)
    if current_entry is not None:
        if current_entry != entry:
            raise PromotionReceiptError("registry_entry_conflict")
        try:
            _fsync_directory(path.parent)
        except OSError as exc:
            raise PromotionReceiptError("receipt_store_io_failure") from exc
        return existing

    trusted_keys[issuer_key_id] = public_key
    entries[receipt_id] = entry
    updated: dict[str, object] = {
        "registry_version": REGISTRY_VERSION,
        "trusted_keys": trusted_keys,
        "entries": entries,
    }
    temp = _write_temp(path, _canonical_bytes(updated))
    try:
        if _read_canonical_file(path, code="registry_conflict") != existing:
            raise PromotionReceiptError("registry_conflict")
        os.replace(temp, path)
        _fsync_directory(path.parent)
    except OSError as exc:
        raise PromotionReceiptError("receipt_store_io_failure") from exc
    finally:
        _unlink_temp(temp)
    return updated


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, child in pairs:
        if key in value:
            raise PromotionReceiptError("duplicate_json_key")
        value[key] = child
    return value


def write_promotion_test_terminal_receipt(
    *,
    attempt_id: str,
    rendered: Mapping[str, object],
    channel_manifest: Mapping[str, object],
    prod_admission_context: Mapping[str, str],
    check_report: Mapping[str, object],
    migration_paths: Sequence[Path],
    issued_at: datetime,
    fresh_until: datetime,
    issuer_id: str,
    issuer_key_id: str,
    signer: Callable[[bytes], bytes],
    issuer_public_key: bytes,
    receipt_store: Path,
    resettable_roots: Sequence[Path],
) -> dict[str, object]:
    """Persist one immutable PASS/FAIL result for a promotion-test attempt.

    ``migration`` is derived through the existing active reversibility
    classifier.  This writer neither duplicates its marker rules nor accepts a
    caller-supplied migration boolean.
    """
    if not isinstance(attempt_id, str) or _ATTEMPT_ID.fullmatch(attempt_id) is None:
        raise PromotionReceiptError("attempt_id_invalid")
    validated_paths = _validate_migration_paths(migration_paths)
    migration_snapshots = _capture_migration_snapshots(validated_paths)
    validated_identity, validated_checks, validated_report = _bind_promotion_test_report(
        rendered=rendered,
        channel_manifest=channel_manifest,
        prod_admission_context=prod_admission_context,
        check_report=check_report,
        migration_snapshots=migration_snapshots,
    )
    try:
        migration_classification: dict[str, object] = check_migration_snapshots(
            migration_snapshots
        )
        migration_ok = True
    except (MigrationMarkerError, OSError, UnicodeError):
        migration_classification = {"status": "invalid"}
        migration_ok = False
    terminal_checks = {"migration": migration_ok, **validated_checks}
    outcome = "PASS" if all(terminal_checks.values()) else "FAIL"
    receipt = _build_receipt(
        identity=validated_identity,
        outcome=outcome,
        issued_at=issued_at,
        fresh_until=fresh_until,
        issuer_id=issuer_id,
        issuer_key_id=issuer_key_id,
        signer=signer,
        issuer_public_key=issuer_public_key,
    )
    store, receipts, attempts, reservations = _prepare_store(
        receipt_store,
        resettable_roots,
    )
    receipt_id = str(receipt["receipt_id"])
    receipt_path = receipts / f"{receipt_id.removeprefix('sha256:')}.json"
    registry_path = store / "registry.json"
    attempt_path = attempts / f"{attempt_id}.json"
    attempt = {
        "attempt_version": ATTEMPT_VERSION,
        "attempt_id": attempt_id,
        "candidate_identity": validated_report["candidate_identity"],
        "check_report_identity": "sha256:"
        + hashlib.sha256(_canonical_bytes(validated_report)).hexdigest(),
        "receipt_id": receipt_id,
        "outcome": outcome,
        "identity": validated_identity,
        "check_results": terminal_checks,
        "migration_classification": migration_classification,
    }
    receipt_bytes = _canonical_bytes(receipt)
    attempt_bytes = _canonical_bytes(attempt)
    reservation = {
        "reservation_version": RESERVATION_VERSION,
        "attempt_id": attempt_id,
        "receipt_id": receipt_id,
        "outcome": outcome,
        "intent_digest": "sha256:" + hashlib.sha256(attempt_bytes).hexdigest(),
    }
    reservation_path = reservations / f"{attempt_id}.json"
    reservation_bytes = _canonical_bytes(reservation)
    lock_path = store / ".writer.lock"
    lock_flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        lock_descriptor = os.open(lock_path, lock_flags, 0o600)
    except OSError as exc:
        raise PromotionReceiptError("receipt_store_io_failure") from exc
    try:
        lock_info = os.fstat(lock_descriptor)
        if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_nlink != 1:
            raise PromotionReceiptError("unsafe_receipt_store")
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        _fence_receipt_store(store)
        _install_immutable_record(
            reservation_path,
            reservation_bytes,
            code="attempt_conflict",
        )
        existing_reservation = _read_canonical_file(
            reservation_path,
            code="attempt_conflict",
        )
        if set(existing_reservation) != _RESERVATION_FIELDS:
            raise PromotionReceiptError("attempt_conflict")
        if attempt_path.exists():
            _install_content_addressed(receipt_path, receipt_bytes)
            _publish_registry_entry(
                registry_path,
                receipt=receipt,
                issuer_public_key=issuer_public_key,
            )
            _install_immutable_record(
                attempt_path,
                attempt_bytes,
                code="attempt_conflict",
            )
            existing_attempt = _read_canonical_file(
                attempt_path,
                code="attempt_record_corrupt",
            )
            if set(existing_attempt) != _ATTEMPT_FIELDS or existing_attempt != attempt:
                raise PromotionReceiptError("attempt_conflict")
            existing_receipt = _read_canonical_file(
                receipt_path,
                code="receipt_store_corrupt",
            )
            if existing_receipt != receipt:
                raise PromotionReceiptError("receipt_store_corrupt")
            return receipt
        _install_content_addressed(receipt_path, receipt_bytes)
        _publish_registry_entry(
            registry_path,
            receipt=receipt,
            issuer_public_key=issuer_public_key,
        )
        _install_immutable_record(
            attempt_path,
            attempt_bytes,
            code="attempt_conflict",
        )
        _fence_receipt_store(store)
        return receipt
    finally:
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        finally:
            os.close(lock_descriptor)


def _validate_receipt(
    receipt: object,
    registry: object,
    expected_identity: object,
    *,
    now: datetime,
) -> dict[str, object]:
    if receipt is None:
        raise PromotionReceiptError("receipt_missing")
    receipt_mapping = _mapping(receipt, code="receipt_invalid")
    registry_mapping = _mapping(registry, code="registry_missing")
    identity = _validate_identity(expected_identity)
    if set(receipt_mapping) != _RECEIPT_FIELDS:
        raise PromotionReceiptError("receipt_invalid")
    if set(registry_mapping) != _REGISTRY_FIELDS:
        raise PromotionReceiptError("registry_invalid")
    if receipt_mapping.get("receipt_version") != RECEIPT_VERSION:
        raise PromotionReceiptError("receipt_invalid")
    if receipt_mapping.get("outcome") != "PASS":
        raise PromotionReceiptError("receipt_not_pass")
    if receipt_mapping.get("required_checks") != list(REQUIRED_CHECKS):
        raise PromotionReceiptError("required_checks_mismatch")
    for field, expected in identity.items():
        if receipt_mapping.get(field) != expected:
            raise PromotionReceiptError("identity_mismatch")
    receipt_id = receipt_mapping.get("receipt_id")
    expected_receipt_id = "sha256:" + hashlib.sha256(
        _receipt_digest_payload(receipt_mapping)
    ).hexdigest()
    if not isinstance(receipt_id, str) or receipt_id != expected_receipt_id:
        raise PromotionReceiptError("receipt_identity_mismatch")
    if not isinstance(now, datetime):
        raise PromotionReceiptError("validation_time_invalid")
    _timestamp(now, code="validation_time_invalid")
    issued_at = _parse_timestamp(receipt_mapping.get("issued_at"), code="receipt_time_invalid")
    fresh_until = _parse_timestamp(
        receipt_mapping.get("fresh_until"),
        code="receipt_time_invalid",
    )
    if now < issued_at:
        raise PromotionReceiptError("receipt_not_yet_valid")
    if now >= fresh_until:
        raise PromotionReceiptError("receipt_stale")
    issuer_id = receipt_mapping.get("issuer_id")
    issuer_key_id = receipt_mapping.get("issuer_key_id")
    signature_value = receipt_mapping.get("issuer_signature")
    if (
        not isinstance(issuer_id, str)
        or _ISSUER_ID.fullmatch(issuer_id) is None
        or not isinstance(issuer_key_id, str)
        or _ISSUER_ID.fullmatch(issuer_key_id) is None
        or not isinstance(signature_value, str)
        or not signature_value.startswith("ed25519:v1:")
    ):
        raise PromotionReceiptError("issuer_invalid")
    signature = _decode_canonical_b64url(
        signature_value.removeprefix("ed25519:v1:"),
        length=64,
        code="signature_invalid",
    )
    if registry_mapping.get("registry_version") != REGISTRY_VERSION:
        raise PromotionReceiptError("registry_invalid")
    trusted_keys = _mapping(registry_mapping.get("trusted_keys"), code="registry_invalid")
    entries = _mapping(registry_mapping.get("entries"), code="registry_invalid")
    public_key_value = trusted_keys.get(issuer_key_id)
    if public_key_value is None:
        raise PromotionReceiptError("issuer_untrusted")
    public_key_bytes = _decode_canonical_b64url(
        public_key_value,
        length=32,
        code="issuer_key_invalid",
    )
    entry = _mapping(entries.get(receipt_id), code="receipt_unregistered")
    if set(entry) != _REGISTRY_ENTRY_FIELDS:
        raise PromotionReceiptError("registry_entry_invalid")
    if entry.get("status") == "revoked":
        raise PromotionReceiptError("receipt_revoked")
    if entry.get("status") != "issued":
        raise PromotionReceiptError("registry_entry_invalid")
    if (
        entry.get("issuer_id") != issuer_id
        or entry.get("issuer_key_id") != issuer_key_id
        or entry.get("public_key") != public_key_value
        or entry.get("issuer_signature") != signature_value
    ):
        raise PromotionReceiptError("registry_entry_mismatch")
    try:
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
            signature,
            _receipt_unsigned_payload(receipt_mapping),
        )
    except (ValueError, InvalidSignature) as exc:
        raise PromotionReceiptError("signature_invalid") from exc
    return dict(receipt_mapping)


def authorize_prod_activation(
    receipt: object,
    registry: object,
    expected_identity: object,
    *,
    now: datetime,
) -> dict[str, object]:
    """Return admission evidence only after exact prod receipt validation.

    This is the production pre-activation call site.  It has no activation,
    deployment, restart, migration, or emergency-bypass capability.
    """
    validated = _validate_receipt(receipt, registry, expected_identity, now=now)
    return {
        "activation_permitted": True,
        "receipt_id": validated["receipt_id"],
    }


def prepare_prod_activation(
    receipt: object,
    registry: object,
    prod_admission_context: object,
    *,
    now: datetime,
) -> dict[str, object]:
    """Production pre-activation boundary, intentionally without side effects.

    STARTUP-04 ends here: every future topology activation must consume this
    entrypoint immediately before its separately governed side effect.  The
    returned record is evidence that validation ran; this function cannot
    deploy or activate a channel itself.
    """
    authorization = authorize_prod_activation(
        receipt,
        registry,
        prod_admission_context,
        now=now,
    )
    return {
        **authorization,
        "activation_state": "validated_not_activated",
    }


def _read_json(path: Path, *, code: str) -> Mapping[str, Any]:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        info = os.fstat(descriptor)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        named_info = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or (named_info.st_dev, named_info.st_ino) != (info.st_dev, info.st_ino)
        ):
            raise PromotionReceiptError(code)
        value = json.loads(b"".join(chunks), object_pairs_hook=_reject_duplicate_keys)
    except (OSError, json.JSONDecodeError, PromotionReceiptError) as exc:
        raise PromotionReceiptError(code) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return _mapping(value, code=code)


def _read_private_key(path: Path) -> Ed25519PrivateKey:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        info = os.fstat(descriptor)
        encoded_bytes = os.read(descriptor, 257)
        named_info = path.stat(follow_symlinks=False)
        encoded = encoded_bytes.decode("ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise PromotionReceiptError("issuer_private_key_unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
        or len(encoded_bytes) > 256
        or (named_info.st_dev, named_info.st_ino) != (info.st_dev, info.st_ino)
        or info.st_mode & (stat.S_IRWXG | stat.S_IRWXO)
    ):
        raise PromotionReceiptError("issuer_private_key_permissions")
    raw = _decode_canonical_b64url(encoded, length=32, code="issuer_private_key_invalid")
    return Ed25519PrivateKey.from_private_bytes(raw)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.release_channels.promotion_receipt",
        description="Write promotion-test terminal receipts or validate prod admission.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    write = commands.add_parser("promotion-test-verify")
    write.add_argument("--attempt-id", required=True)
    write.add_argument("--rendered", type=Path, required=True)
    write.add_argument("--manifest", type=Path, required=True)
    write.add_argument("--admission-context", type=Path, required=True)
    write.add_argument("--checks", type=Path, required=True)
    write.add_argument("--migration", type=Path, action="append", default=[])
    write.add_argument("--receipt-store", type=Path, required=True)
    write.add_argument("--issuer-id", required=True)
    write.add_argument("--issuer-key-id", required=True)
    write.add_argument("--issuer-private-key", type=Path, required=True)
    write.add_argument("--issued-at", required=True)
    write.add_argument("--fresh-until", required=True)
    validate = commands.add_parser("validate-prod-activation")
    validate.add_argument("--receipt", type=Path, required=True)
    validate.add_argument("--registry", type=Path, required=True)
    validate.add_argument("--admission-context", type=Path, required=True)
    validate.add_argument("--now", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "promotion-test-verify":
            private_key = _read_private_key(args.issuer_private_key)
            public_key = private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            repo_root = Path(__file__).resolve().parents[2]
            result = write_promotion_test_terminal_receipt(
                attempt_id=args.attempt_id,
                rendered=_read_json(args.rendered, code="candidate_unavailable"),
                channel_manifest=_read_json(args.manifest, code="manifest_unavailable"),
                prod_admission_context=_read_json(
                    args.admission_context,
                    code="identity_unavailable",
                ),
                check_report=_read_json(args.checks, code="checks_unavailable"),
                migration_paths=tuple(args.migration),
                issued_at=_parse_timestamp(args.issued_at, code="issued_at_invalid"),
                fresh_until=_parse_timestamp(args.fresh_until, code="fresh_until_invalid"),
                issuer_id=args.issuer_id,
                issuer_key_id=args.issuer_key_id,
                signer=private_key.sign,
                issuer_public_key=public_key,
                receipt_store=args.receipt_store,
                resettable_roots=(repo_root / "tmp-test", repo_root / "vault-test"),
            )
        else:
            result = prepare_prod_activation(
                _read_json(args.receipt, code="receipt_missing"),
                _read_json(args.registry, code="registry_missing"),
                _read_json(args.admission_context, code="identity_unavailable"),
                now=_parse_timestamp(args.now, code="validation_time_invalid"),
            )
    except PromotionReceiptError as exc:
        print(json.dumps(exc.as_dict(), sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PromotionReceiptError",
    "REQUIRED_CHECKS",
    "authorize_prod_activation",
    "build_promotion_test_check_report",
    "prepare_prod_activation",
    "write_promotion_test_terminal_receipt",
]
