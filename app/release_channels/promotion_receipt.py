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

from app.release_channels.reversibility import (
    MigrationMarkerError,
    check_all_migrations,
)


RECEIPT_VERSION = "promotion-receipt.v1"
REGISTRY_VERSION = "promotion-receipt-registry.v1"
ATTEMPT_VERSION = "promotion-test-attempt.v1"
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
    "receipt_id",
    "outcome",
    "identity",
    "check_results",
    "migration_classification",
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


def _prepare_store(receipt_store: Path, resettable_roots: Sequence[Path]) -> tuple[Path, Path, Path]:
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
        receipt_store.mkdir(mode=0o700, parents=True, exist_ok=True)
        receipts = receipt_store / "receipts"
        attempts = receipt_store / "attempts"
        receipts.mkdir(mode=0o700, exist_ok=True)
        attempts.mkdir(mode=0o700, exist_ok=True)
    except OSError as exc:
        raise PromotionReceiptError("receipt_store_unavailable") from exc
    for directory in (receipt_store, receipts, attempts):
        if directory.resolve(strict=True) != directory:
            raise PromotionReceiptError("unsafe_receipt_store")
        _validate_private_directory(directory)
    return receipt_store, receipts, attempts


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


def _read_canonical_file(path: Path, *, code: str) -> dict[str, object]:
    try:
        info = path.stat(follow_symlinks=False)
        data = path.read_bytes()
        value = json.loads(data, object_pairs_hook=_reject_duplicate_keys)
    except (OSError, json.JSONDecodeError, PromotionReceiptError) as exc:
        raise PromotionReceiptError(code) from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
        or _canonical_bytes(value) != data
        or not isinstance(value, dict)
    ):
        raise PromotionReceiptError(code)
    return value


def _install_content_addressed(path: Path, data: bytes) -> None:
    if path.exists():
        if _read_canonical_file(path, code="receipt_store_corrupt") != json.loads(data):
            raise PromotionReceiptError("receipt_store_corrupt")
        return
    temp = _write_temp(path, data)
    try:
        try:
            os.link(temp, path, follow_symlinks=False)
        except FileExistsError:
            if _read_canonical_file(path, code="receipt_store_corrupt") != json.loads(data):
                raise PromotionReceiptError("receipt_store_corrupt")
        _fsync_directory(path.parent)
    except OSError as exc:
        raise PromotionReceiptError("receipt_store_io_failure") from exc
    finally:
        temp.unlink(missing_ok=True)


def _replace_pointer(path: Path, data: bytes) -> None:
    temp = _write_temp(path, data)
    try:
        os.replace(temp, path)
        _fsync_directory(path.parent)
    except OSError as exc:
        raise PromotionReceiptError("receipt_store_io_failure") from exc
    finally:
        temp.unlink(missing_ok=True)


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
    identity: Mapping[str, str],
    check_results: Mapping[str, bool],
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
    validated_identity = _validate_identity(identity)
    validated_checks = _validate_checks(check_results)
    if not isinstance(migration_paths, Sequence) or isinstance(
        migration_paths,
        (str, bytes),
    ) or any(not isinstance(path, Path) for path in migration_paths):
        raise PromotionReceiptError("migration_paths_invalid")
    try:
        migration_classification: dict[str, object] = check_all_migrations(
            migration_paths
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
    store, receipts, attempts = _prepare_store(receipt_store, resettable_roots)
    receipt_id = str(receipt["receipt_id"])
    receipt_path = receipts / f"{receipt_id.removeprefix('sha256:')}.json"
    attempt_path = attempts / f"{attempt_id}.json"
    attempt = {
        "attempt_version": ATTEMPT_VERSION,
        "attempt_id": attempt_id,
        "receipt_id": receipt_id,
        "outcome": outcome,
        "identity": validated_identity,
        "check_results": terminal_checks,
        "migration_classification": migration_classification,
    }
    receipt_bytes = _canonical_bytes(receipt)
    attempt_bytes = _canonical_bytes(attempt)
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
        if attempt_path.exists():
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
        _replace_pointer(attempt_path, attempt_bytes)
        _fsync_directory(store)
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


def _read_json(path: Path, *, code: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_bytes(), object_pairs_hook=_reject_duplicate_keys)
    except (OSError, json.JSONDecodeError, PromotionReceiptError) as exc:
        raise PromotionReceiptError(code) from exc
    return _mapping(value, code=code)


def _read_private_key(path: Path) -> Ed25519PrivateKey:
    try:
        info = path.stat(follow_symlinks=False)
        encoded = path.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise PromotionReceiptError("issuer_private_key_unavailable") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
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
                identity=_read_json(args.admission_context, code="identity_unavailable"),
                check_results=_read_json(args.checks, code="checks_unavailable"),
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
            result = authorize_prod_activation(
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
    "write_promotion_test_terminal_receipt",
]
