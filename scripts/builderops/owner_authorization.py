#!/usr/bin/env python3
"""Validate the durable owner delegation used by unattended BuilderOps updates.

The profile is deliberately a small policy artifact, not a replacement for
candidate attestation or deployment preflight.  It removes the need for a
human prompt on every update while keeping the scope, target and expiry
machine-checkable and fail-closed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import errno
import hashlib
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any


EXPECTED_REPOSITORY = "RasmusTho/agentic-pkm-mvp"
EXPECTED_SOURCE_REF = "refs/heads/main"
EXPECTED_WORKFLOW = "RasmusTho/agentic-pkm-mvp/.github/workflows/app-image-build.yml"
EXPECTED_CONTEXT = "builderops"
EXPECTED_SOCKET = "unix:///run/docker-builderops.sock"
EXPECTED_PROJECT = "builderops-control-plane"
EXPECTED_VM_ID = 102


class AuthorizationError(ValueError):
    """The owner profile is absent, malformed or outside its delegated scope."""


def _validate_ancestor_custody(path: Path) -> None:
    if not path.is_absolute():
        raise AuthorizationError("secure owner authorization paths must be absolute")
    current = path.parent
    while True:
        try:
            metadata = current.lstat()
        except FileNotFoundError as exc:
            raise AuthorizationError("owner authorization parent directory is missing") from exc
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0:
            raise AuthorizationError("owner authorization parent directory must be root-owned")
        if metadata.st_mode & 0o022:
            raise AuthorizationError("owner authorization parent directory must not be group/other writable")
        if current == Path("/"):
            return
        current = current.parent


def _parse_timestamp(value: Any, field: str) -> dt.datetime:
    if not isinstance(value, str) or not value.strip():
        raise AuthorizationError(f"{field} must be a non-empty timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuthorizationError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise AuthorizationError(f"{field} must include a timezone")
    return parsed.astimezone(dt.timezone.utc)


def _read_secure_bytes(path: Path, *, label: str) -> bytes:
    _validate_ancestor_custody(path)
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
    except FileNotFoundError as exc:
        raise AuthorizationError("owner authorization profile is missing") from exc
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise AuthorizationError(f"{label} must be a regular file") from exc
        raise AuthorizationError(f"{label} is not readable") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise AuthorizationError(f"{label} must be a regular file")
        if metadata.st_uid != 0:
            raise AuthorizationError(f"{label} must be root-owned")
        if metadata.st_mode & 0o027:
            raise AuthorizationError(f"{label} permissions must be 0600 or 0640")
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = -1
            return stream.read().encode("utf-8")
    except OSError as exc:
        raise AuthorizationError(f"{label} is not readable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _read_secure_profile(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(_read_secure_bytes(path, label="owner authorization profile").decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AuthorizationError("owner authorization profile is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise AuthorizationError("owner authorization profile must be a JSON object")
    return payload


def validate_profile(
    path: Path,
    *,
    action: str,
    observed_hostname: str,
    now: dt.datetime | None = None,
) -> tuple[dict[str, Any], str]:
    payload = _read_secure_profile(path)
    if payload.get("authorization_version") != 1:
        raise AuthorizationError("unsupported owner authorization version")
    if payload.get("mode") != "unattended":
        raise AuthorizationError("owner authorization mode is not unattended")
    if payload.get("repository") != EXPECTED_REPOSITORY:
        raise AuthorizationError("owner authorization repository is not the admitted repository")
    if payload.get("source_ref") != EXPECTED_SOURCE_REF:
        raise AuthorizationError("owner authorization source ref is not refs/heads/main")
    if payload.get("attestation_workflow") != EXPECTED_WORKFLOW:
        raise AuthorizationError("owner authorization workflow is not the admitted workflow")
    if payload.get("project") != EXPECTED_PROJECT:
        raise AuthorizationError("owner authorization project is not the admitted project")
    if payload.get("docker_context") != EXPECTED_CONTEXT:
        raise AuthorizationError("owner authorization Docker context is not builderops")
    if payload.get("engine_socket") != EXPECTED_SOCKET:
        raise AuthorizationError("owner authorization Docker socket is not the VM-102 socket")
    if payload.get("vm_id") != EXPECTED_VM_ID:
        raise AuthorizationError("owner authorization VM id is not 102")
    principal = payload.get("authorized_by")
    if not isinstance(principal, str) or not principal.strip():
        raise AuthorizationError("owner authorization must name the authorizing owner")
    actions = payload.get("allowed_actions")
    if not isinstance(actions, list) or set(actions) != {"deploy", "rollback"}:
        raise AuthorizationError("owner authorization must allow exactly deploy and rollback")
    if action not in actions:
        raise AuthorizationError(f"owner authorization does not allow {action}")

    expected_hostname = payload.get("guest_hostname")
    if not isinstance(expected_hostname, str) or not expected_hostname.strip():
        raise AuthorizationError("owner authorization must name the guest hostname")
    if observed_hostname != expected_hostname:
        raise AuthorizationError(
            f"deployment guest hostname {observed_hostname!r} does not match the authorized target"
        )

    authorized_at = _parse_timestamp(payload.get("authorized_at"), "authorized_at")
    expires_at = _parse_timestamp(payload.get("expires_at"), "expires_at")
    current = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    if expires_at <= authorized_at:
        raise AuthorizationError("owner authorization expiry must follow authorization time")
    if expires_at <= current:
        raise AuthorizationError("owner authorization has expired")
    if authorized_at > current + dt.timedelta(minutes=5):
        raise AuthorizationError("owner authorization is future-dated")
    if expires_at - authorized_at > dt.timedelta(days=90):
        raise AuthorizationError("owner authorization may not exceed a 90-day review window")

    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload, fingerprint


def _command_validate(args: argparse.Namespace) -> int:
    try:
        _, fingerprint = validate_profile(
            Path(args.file),
            action=args.action,
            observed_hostname=args.hostname,
        )
    except AuthorizationError as exc:
        print(str(exc), file=sys.stderr)
        return 78
    print(fingerprint)
    return 0


def _command_fingerprint(args: argparse.Namespace) -> int:
    try:
        payload = _read_secure_profile(Path(args.file))
    except AuthorizationError as exc:
        print(str(exc), file=sys.stderr)
        return 78
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    print(hashlib.sha256(canonical.encode("utf-8")).hexdigest())
    return 0


def _command_secure_file(args: argparse.Namespace) -> int:
    try:
        _read_secure_bytes(Path(args.file), label="secure file")
    except AuthorizationError as exc:
        print(str(exc), file=sys.stderr)
        return 78
    return 0


def _command_verify_candidate(args: argparse.Namespace) -> int:
    path = Path(args.file)
    try:
        raw = _read_secure_bytes(path, label="candidate receipt")
        fingerprint = hashlib.sha256(raw).hexdigest()
        if fingerprint != args.receipt_sha:
            raise AuthorizationError("candidate receipt fingerprint does not match the pin")
        payload = json.loads(raw.decode("utf-8"))
        expected = {
            "receipt_version": 1,
            "repository": EXPECTED_REPOSITORY,
            "workflow": ".github/workflows/app-image-build.yml",
            "event_name": "push",
            "source_ref": EXPECTED_SOURCE_REF,
            "durability_posture": "rebuildable",
            "platform": "linux/amd64",
            "source_sha": args.source_sha,
            "control_plane_image_digest": args.image_digest,
            "postgres_image_digest": args.postgres_digest,
        }
        if not isinstance(payload, dict) or any(payload.get(key) != value for key, value in expected.items()):
            raise AuthorizationError("candidate receipt provenance does not match the previous pin")
    except (AuthorizationError, OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 78
    return 0


def _command_issue(args: argparse.Namespace) -> int:
    if os.geteuid() != 0:
        print("owner authorization profile must be installed by root", file=sys.stderr)
        return 77
    if args.confirm != "AUTHORIZE BOB-1 BUILDEROPS UPDATES":
        print("explicit owner authorization confirmation is required", file=sys.stderr)
        return 77
    output = Path(args.file)
    try:
        _validate_ancestor_custody(output)
    except AuthorizationError as exc:
        print(str(exc), file=sys.stderr)
        return 77
    if output.exists() and not args.replace:
        print("refusing to replace an existing owner authorization profile", file=sys.stderr)
        return 77
    authorized_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    payload: dict[str, Any] = {
        "authorization_version": 1,
        "mode": "unattended",
        "authorized_by": args.authorized_by,
        "authorized_at": authorized_at.isoformat().replace("+00:00", "Z"),
        "expires_at": args.expires_at,
        "repository": EXPECTED_REPOSITORY,
        "source_ref": EXPECTED_SOURCE_REF,
        "attestation_workflow": EXPECTED_WORKFLOW,
        "project": EXPECTED_PROJECT,
        "docker_context": EXPECTED_CONTEXT,
        "engine_socket": EXPECTED_SOCKET,
        "vm_id": EXPECTED_VM_ID,
        "guest_hostname": args.hostname,
        "allowed_actions": ["deploy", "rollback"],
    }
    if not args.authorized_by.strip():
        print("authorized-by must be non-empty", file=sys.stderr)
        return 77
    try:
        expires_at = _parse_timestamp(payload["expires_at"], "expires_at")
    except AuthorizationError as exc:
        print(str(exc), file=sys.stderr)
        return 77
    if expires_at <= authorized_at:
        print("expires-at must follow the current authorization time", file=sys.stderr)
        return 77
    if expires_at - authorized_at > dt.timedelta(days=90):
        print("owner authorization may not exceed a 90-day review window", file=sys.stderr)
        return 77
    serialized = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=output.parent,
        prefix=f".{output.name}.tmp.",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o640)
        os.fchown(descriptor, 0, 0)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    print(output)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--file", required=True)
    validate.add_argument("--action", choices=("deploy", "rollback"), required=True)
    validate.add_argument("--hostname", required=True)
    validate.set_defaults(handler=_command_validate)
    fingerprint = subparsers.add_parser("fingerprint")
    fingerprint.add_argument("--file", required=True)
    fingerprint.set_defaults(handler=_command_fingerprint)
    secure_file = subparsers.add_parser("secure-file")
    secure_file.add_argument("--file", required=True)
    secure_file.set_defaults(handler=_command_secure_file)
    candidate = subparsers.add_parser("verify-candidate")
    candidate.add_argument("--file", required=True)
    candidate.add_argument("--receipt-sha", required=True)
    candidate.add_argument("--source-sha", required=True)
    candidate.add_argument("--image-digest", required=True)
    candidate.add_argument("--postgres-digest", required=True)
    candidate.set_defaults(handler=_command_verify_candidate)
    issue = subparsers.add_parser("issue")
    issue.add_argument("--file", required=True)
    issue.add_argument("--authorized-by", required=True)
    issue.add_argument("--expires-at", required=True)
    issue.add_argument("--hostname", default="builder-system")
    issue.add_argument("--confirm", required=True)
    issue.add_argument("--replace", action="store_true")
    issue.set_defaults(handler=_command_issue)
    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
