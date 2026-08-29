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
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
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


RECEIPT_VERSION = "promotion-receipt.v2"
REGISTRY_VERSION = "promotion-receipt-registry.v1"
ATTEMPT_VERSION = "promotion-test-attempt.v1"
RESERVATION_VERSION = "promotion-test-reservation.v1"
REPORT_VERSION = "promotion-test-check-report.v1"
PROD_REPOSITORY_URL = "https://github.com/RasmusTho/agentic-pkm-mvp.git"
PROD_PROMOTION_REF = "refs/heads/main"
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
    "migration_baseline_identity",
    "migration_set_identity",
    "check_report_identity",
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
_ADMISSION_CONTEXT_FIELDS = _IDENTITY_FIELDS | {"migration_baseline_identity"}
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
    "migration_baseline_identity",
}
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SOURCE_SHA = re.compile(r"[0-9a-f]{40}\Z")
_MIGRATION_GIT_PATH = re.compile(
    r"app/alembic/versions/[A-Za-z0-9][A-Za-z0-9_.-]*\.py\Z"
)
_ATTEMPT_ID = re.compile(r"pt-[0-9a-f]{32}\Z")
_TEST_IDENTITY = re.compile(r"promotion-test:[0-9]{8}\Z")
_VAULT_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_SCHEMA_IDENTITY = re.compile(r"alembic:[A-Za-z0-9._-]+\Z")
_ISSUER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_B64URL = re.compile(r"[A-Za-z0-9_-]+\Z")
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
_TRUSTED_GIT_PATHS = (Path("/usr/bin/git"), Path("/bin/git"))


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


def _validate_admission_context(value: object) -> tuple[dict[str, str], str]:
    context = _mapping(value, code="identity_invalid")
    if set(context) != _ADMISSION_CONTEXT_FIELDS:
        raise PromotionReceiptError("identity_invalid")
    identity = _validate_identity(
        {field: context[field] for field in _IDENTITY_FIELDS}
    )
    baseline_identity = context.get("migration_baseline_identity")
    if (
        not isinstance(baseline_identity, str)
        or not baseline_identity.startswith("git:")
        or _SOURCE_SHA.fullmatch(baseline_identity.removeprefix("git:")) is None
    ):
        raise PromotionReceiptError("identity_invalid")
    return identity, baseline_identity.removeprefix("git:")


def _validate_checks(value: object) -> dict[str, bool]:
    checks = _mapping(value, code="check_results_invalid")
    if set(checks) != set(_OBSERVED_CHECKS) or any(
        type(result) is not bool for result in checks.values()
    ):
        raise PromotionReceiptError("check_results_invalid")
    return {name: bool(checks[name]) for name in _OBSERVED_CHECKS}


def _git_environment() -> dict[str, str]:
    """Run Git with only the environment required by the trusted boundary."""
    return {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }


def _trusted_git_executable() -> str:
    for candidate in _TRUSTED_GIT_PATHS:
        try:
            info = candidate.stat()
        except OSError:
            continue
        if (
            stat.S_ISREG(info.st_mode)
            and info.st_uid == 0
            and info.st_mode & stat.S_IXUSR
            and not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            return str(candidate)
    raise PromotionReceiptError("git_unavailable")


def _trusted_git_authority_cwd() -> str:
    authority_cwd = Path("/")
    try:
        info = authority_cwd.stat()
        git_marker = authority_cwd / ".git"
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != 0
            or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or git_marker.exists()
            or git_marker.is_symlink()
        ):
            raise PromotionReceiptError("git_authority_unavailable")
    except OSError as exc:
        raise PromotionReceiptError("git_authority_unavailable") from exc
    return str(authority_cwd)


def _run_git(repo: Path, *args: str, code: str) -> bytes:
    environment = _git_environment()
    try:
        completed = subprocess.run(
            [_trusted_git_executable(), "-C", str(repo), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PromotionReceiptError(code) from exc
    if completed.returncode != 0:
        raise PromotionReceiptError(code)
    return completed.stdout


def _validated_source_repo(source_repo: Path, *, code: str) -> Path:
    if not source_repo.is_absolute():
        raise PromotionReceiptError(code)
    try:
        repo = source_repo.resolve(strict=True)
        repo_info = repo.stat()
        top_level = _run_git(
            repo,
            "rev-parse",
            "--show-toplevel",
            code=code,
        ).decode("utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise PromotionReceiptError(code) from exc
    if (
        not stat.S_ISDIR(repo_info.st_mode)
        or repo_info.st_uid != os.geteuid()
        or Path(top_level).resolve(strict=True) != repo
    ):
        raise PromotionReceiptError(code)
    return repo


def _resolve_authoritative_prod_baseline(source_repo: Path) -> str:
    _validated_source_repo(
        source_repo,
        code="migration_baseline_unavailable",
    )
    try:
        baseline = _fetch_authoritative_prod_baseline()
    except UnicodeDecodeError as exc:
        raise PromotionReceiptError("migration_baseline_unavailable") from exc
    if _SOURCE_SHA.fullmatch(baseline) is None:
        raise PromotionReceiptError("migration_baseline_invalid")
    return baseline


def _fetch_authoritative_prod_baseline() -> str:
    environment = _git_environment()
    try:
        completed = subprocess.run(
            [
                _trusted_git_executable(),
                "ls-remote",
                "--refs",
                PROD_REPOSITORY_URL,
                PROD_PROMOTION_REF,
            ],
            cwd=_trusted_git_authority_cwd(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PromotionReceiptError("migration_baseline_unavailable") from exc
    if completed.returncode != 0:
        raise PromotionReceiptError("migration_baseline_unavailable")
    try:
        rows = completed.stdout.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise PromotionReceiptError("migration_baseline_unavailable") from exc
    if len(rows) != 1:
        raise PromotionReceiptError("migration_baseline_invalid")
    fields = rows[0].split("\t")
    if len(fields) != 2 or fields[1] != PROD_PROMOTION_REF:
        raise PromotionReceiptError("migration_baseline_invalid")
    baseline = fields[0]
    if _SOURCE_SHA.fullmatch(baseline) is None:
        raise PromotionReceiptError("migration_baseline_invalid")
    return baseline


def _verified_git_object(
    repo: Path,
    *,
    object_id: str,
    object_type: str,
) -> bytes:
    if _SOURCE_SHA.fullmatch(object_id) is None or object_type not in {
        "blob",
        "commit",
        "tree",
    }:
        raise PromotionReceiptError("migration_delta_invalid")
    content = _run_git(
        repo,
        "cat-file",
        object_type,
        object_id,
        code="migration_delta_invalid",
    )
    header = f"{object_type} {len(content)}\0".encode("ascii")
    actual_id = hashlib.sha1(header + content, usedforsecurity=False).hexdigest()
    if actual_id != object_id:
        raise PromotionReceiptError("migration_delta_invalid")
    return content


def _verified_commit(
    repo: Path,
    object_id: str,
) -> tuple[str, tuple[str, ...]]:
    content = _verified_git_object(
        repo,
        object_id=object_id,
        object_type="commit",
    )
    headers = content.partition(b"\n\n")[0].splitlines()
    tree_ids: list[str] = []
    parent_ids: list[str] = []
    try:
        for line in headers:
            if line.startswith(b"tree "):
                tree_ids.append(line.removeprefix(b"tree ").decode("ascii"))
            elif line.startswith(b"parent "):
                parent_ids.append(line.removeprefix(b"parent ").decode("ascii"))
    except UnicodeDecodeError as exc:
        raise PromotionReceiptError("migration_delta_invalid") from exc
    if (
        len(tree_ids) != 1
        or _SOURCE_SHA.fullmatch(tree_ids[0]) is None
        or any(_SOURCE_SHA.fullmatch(parent) is None for parent in parent_ids)
    ):
        raise PromotionReceiptError("migration_delta_invalid")
    return tree_ids[0], tuple(parent_ids)


def _verified_ancestry_trees(
    repo: Path,
    *,
    baseline_sha: str,
    target_sha: str,
) -> tuple[str, str]:
    stack = [target_sha]
    visited: set[str] = set()
    target_tree: str | None = None
    while stack:
        commit_id = stack.pop()
        if commit_id in visited:
            continue
        visited.add(commit_id)
        if len(visited) > 10_000:
            raise PromotionReceiptError("migration_delta_invalid")
        tree_id, parents = _verified_commit(repo, commit_id)
        if commit_id == target_sha:
            target_tree = tree_id
        if commit_id == baseline_sha:
            if target_tree is None:
                raise PromotionReceiptError("migration_delta_invalid")
            return tree_id, target_tree
        stack.extend(reversed(parents))
    raise PromotionReceiptError("migration_delta_invalid")


def _verified_tree_entries(repo: Path, object_id: str) -> dict[bytes, tuple[str, str]]:
    content = _verified_git_object(
        repo,
        object_id=object_id,
        object_type="tree",
    )
    entries: dict[bytes, tuple[str, str]] = {}
    cursor = 0
    while cursor < len(content):
        space = content.find(b" ", cursor)
        terminator = content.find(b"\0", space + 1)
        object_start = terminator + 1
        object_end = object_start + 20
        if space <= cursor or terminator <= space + 1 or object_end > len(content):
            raise PromotionReceiptError("migration_delta_invalid")
        try:
            mode = content[cursor:space].decode("ascii")
        except UnicodeDecodeError as exc:
            raise PromotionReceiptError("migration_delta_invalid") from exc
        name = content[space + 1 : terminator]
        child_id = content[object_start:object_end].hex()
        if (
            re.fullmatch(r"[0-7]{5,6}", mode) is None
            or not name
            or b"/" in name
            or name in entries
            or _SOURCE_SHA.fullmatch(child_id) is None
        ):
            raise PromotionReceiptError("migration_delta_invalid")
        entries[name] = (mode, child_id)
        cursor = object_end
    return entries


def _verified_tree_at_path(
    repo: Path,
    *,
    root_tree: str,
    components: Sequence[bytes],
) -> dict[bytes, tuple[str, str]]:
    tree_id = root_tree
    for component in components:
        entries = _verified_tree_entries(repo, tree_id)
        entry = entries.get(component)
        if entry is None or entry[0] != "40000":
            raise PromotionReceiptError("migration_delta_invalid")
        tree_id = entry[1]
    return _verified_tree_entries(repo, tree_id)


def _capture_candidate_migration_snapshots(
    *,
    source_repo: Path,
    baseline_sha: str,
    target_sha: str,
) -> tuple[tuple[str, bytes], ...]:
    if (
        not source_repo.is_absolute()
        or _SOURCE_SHA.fullmatch(baseline_sha) is None
        or _SOURCE_SHA.fullmatch(target_sha) is None
    ):
        raise PromotionReceiptError("migration_delta_invalid")
    repo = _validated_source_repo(
        source_repo,
        code="migration_delta_unavailable",
    )
    baseline_tree, target_tree = _verified_ancestry_trees(
        repo,
        baseline_sha=baseline_sha,
        target_sha=target_sha,
    )
    components = (b"app", b"alembic", b"versions")
    baseline_entries = _verified_tree_at_path(
        repo,
        root_tree=baseline_tree,
        components=components,
    )
    target_entries = _verified_tree_at_path(
        repo,
        root_tree=target_tree,
        components=components,
    )
    changed_names = sorted(
        name
        for name in baseline_entries.keys() | target_entries.keys()
        if baseline_entries.get(name) != target_entries.get(name)
    )
    snapshots: list[tuple[str, bytes]] = []
    for raw_name in changed_names:
        try:
            name = raw_name.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PromotionReceiptError("migration_delta_invalid") from exc
        path = f"app/alembic/versions/{name}"
        entry = target_entries.get(raw_name)
        if entry is None or _MIGRATION_GIT_PATH.fullmatch(path) is None:
            raise PromotionReceiptError("migration_delta_invalid")
        mode, object_id = entry
        if mode not in {"100644", "100755"}:
            raise PromotionReceiptError("migration_delta_invalid")
        content = _verified_git_object(
            repo,
            object_id=object_id,
            object_type="blob",
        )
        snapshots.append((name, content))
    return tuple(snapshots)


def _migration_set_identity(snapshots: Sequence[tuple[str, bytes]]) -> str:
    records: list[dict[str, str]] = []
    for name, content in snapshots:
        digest = hashlib.sha256(content).hexdigest()
        records.append({"migration": name, "digest": f"sha256:{digest}"})
    return "sha256:" + hashlib.sha256(
        _canonical_bytes(sorted(records, key=lambda record: record["migration"]))
    ).hexdigest()


def _derive_candidate_identity(
    *,
    rendered: Mapping[str, object],
    channel_manifest: Mapping[str, object],
    prod_admission_context: Mapping[str, str],
    source_repo: Path,
) -> tuple[dict[str, object], dict[str, str], str]:
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
    candidate_bound_identity, requested_baseline_sha = _validate_admission_context(
        prod_admission_context
    )
    migration_baseline_sha = _resolve_authoritative_prod_baseline(source_repo)
    if requested_baseline_sha != migration_baseline_sha:
        raise PromotionReceiptError("migration_baseline_mismatch")
    for field, expected in (
        ("artifact_digest", image_index.rsplit("@", 1)[1]),
        ("config_identity", config_identity),
        ("schema_identity", schema_identity),
    ):
        if candidate_bound_identity[field] != expected:
            raise PromotionReceiptError("candidate_identity_mismatch")
    return candidate, candidate_bound_identity, migration_baseline_sha


def build_promotion_test_check_report(
    *,
    rendered: Mapping[str, object],
    channel_manifest: Mapping[str, object],
    prod_admission_context: Mapping[str, str],
    check_results: Mapping[str, bool],
    source_repo: Path,
) -> dict[str, object]:
    """Bind runner observations to one immutable candidate and migration set."""
    candidate, identity, migration_baseline_sha = _derive_candidate_identity(
        rendered=rendered,
        channel_manifest=channel_manifest,
        prod_admission_context=prod_admission_context,
        source_repo=source_repo,
    )
    graph = _mapping(candidate.get("artifact_graph"), code="candidate_invalid")
    source_identity = graph.get("source_identity")
    if not isinstance(source_identity, str) or not source_identity.startswith("git:"):
        raise PromotionReceiptError("candidate_invalid")
    migration_snapshots = _capture_candidate_migration_snapshots(
        source_repo=source_repo,
        baseline_sha=migration_baseline_sha,
        target_sha=source_identity.removeprefix("git:"),
    )
    return {
        "report_version": REPORT_VERSION,
        "candidate_identity": candidate["candidate_identity"],
        "identity": identity,
        "check_results": _validate_checks(check_results),
        "migration_set_identity": _migration_set_identity(migration_snapshots),
        "migration_baseline_identity": f"git:{migration_baseline_sha}",
    }


def _bind_promotion_test_report(
    *,
    rendered: Mapping[str, object],
    channel_manifest: Mapping[str, object],
    prod_admission_context: Mapping[str, str],
    check_report: Mapping[str, object],
    source_repo: Path,
) -> tuple[
    dict[str, str],
    dict[str, bool],
    dict[str, object],
    tuple[tuple[str, bytes], ...],
]:
    (
        candidate,
        candidate_bound_identity,
        migration_baseline_sha,
    ) = _derive_candidate_identity(
        rendered=rendered,
        channel_manifest=channel_manifest,
        prod_admission_context=prod_admission_context,
        source_repo=source_repo,
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
    graph = _mapping(candidate.get("artifact_graph"), code="candidate_invalid")
    source_identity = graph.get("source_identity")
    if not isinstance(source_identity, str) or not source_identity.startswith("git:"):
        raise PromotionReceiptError("candidate_invalid")
    migration_snapshots = _capture_candidate_migration_snapshots(
        source_repo=source_repo,
        baseline_sha=migration_baseline_sha,
        target_sha=source_identity.removeprefix("git:"),
    )
    if report.get("migration_baseline_identity") != f"git:{migration_baseline_sha}":
        raise PromotionReceiptError("check_report_migration_mismatch")
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
        "migration_baseline_identity": f"git:{migration_baseline_sha}",
    }
    return candidate_bound_identity, validated_checks, validated_report, migration_snapshots


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
    check_report: Mapping[str, object],
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
    migration_baseline_identity = check_report.get("migration_baseline_identity")
    migration_set_identity = check_report.get("migration_set_identity")
    if (
        not isinstance(migration_baseline_identity, str)
        or not migration_baseline_identity.startswith("git:")
        or _SOURCE_SHA.fullmatch(
            migration_baseline_identity.removeprefix("git:")
        )
        is None
        or not isinstance(migration_set_identity, str)
        or _DIGEST.fullmatch(migration_set_identity) is None
    ):
        raise PromotionReceiptError("check_report_invalid")
    check_report_identity = "sha256:" + hashlib.sha256(
        _canonical_bytes(check_report)
    ).hexdigest()
    receipt: dict[str, object] = {
        "receipt_version": RECEIPT_VERSION,
        "outcome": outcome,
        **identity,
        "migration_baseline_identity": migration_baseline_identity,
        "migration_set_identity": migration_set_identity,
        "check_report_identity": check_report_identity,
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


def _load_trusted_registry(
    path: Path,
    *,
    issuer_key_id: str,
    issuer_public_key: bytes,
) -> dict[str, object]:
    if not path.exists():
        raise PromotionReceiptError("registry_missing")
    _recover_linked_temp(path, code="registry_corrupt")
    existing = _read_canonical_file(path, code="registry_corrupt")
    _validate_registry_update_shape(existing)
    trusted_keys = _mapping(existing["trusted_keys"], code="registry_corrupt")
    current_key = trusted_keys.get(issuer_key_id)
    if current_key is None:
        raise PromotionReceiptError("issuer_untrusted")
    if current_key != _canonical_b64url(issuer_public_key):
        raise PromotionReceiptError("registry_key_conflict")
    return existing


@contextmanager
def _receipt_store_writer_lock(store: Path) -> Iterator[None]:
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
        yield
    finally:
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        finally:
            os.close(lock_descriptor)


def _replace_registry(path: Path, updated: Mapping[str, object]) -> None:
    temp = _write_temp(path, _canonical_bytes(updated))
    try:
        os.replace(temp, path)
        _fsync_directory(path.parent)
    except OSError as exc:
        raise PromotionReceiptError("receipt_store_io_failure") from exc
    finally:
        _unlink_temp(temp)


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
    existing = _load_trusted_registry(
        path,
        issuer_key_id=issuer_key_id,
        issuer_public_key=issuer_public_key,
    )
    trusted_keys = dict(
        _mapping(existing["trusted_keys"], code="registry_corrupt")
    )
    entries = dict(_mapping(existing["entries"], code="registry_corrupt"))
    current_entry = entries.get(receipt_id)
    if current_entry is not None:
        if current_entry != entry:
            raise PromotionReceiptError("registry_entry_conflict")
        try:
            _fsync_directory(path.parent)
        except OSError as exc:
            raise PromotionReceiptError("receipt_store_io_failure") from exc
        return existing

    entries[receipt_id] = entry
    updated: dict[str, object] = {
        "registry_version": REGISTRY_VERSION,
        "trusted_keys": trusted_keys,
        "entries": entries,
    }
    try:
        if _read_canonical_file(path, code="registry_conflict") != existing:
            raise PromotionReceiptError("registry_conflict")
        _replace_registry(path, updated)
    except OSError as exc:
        raise PromotionReceiptError("receipt_store_io_failure") from exc
    return updated


def revoke_promotion_test_receipt(
    *,
    receipt_id: str,
    issuer_key_id: str,
    issuer_public_key: bytes,
    receipt_store: Path,
    resettable_roots: Sequence[Path],
) -> dict[str, object]:
    """Revoke one issued receipt through the serialized registry writer."""
    if _DIGEST.fullmatch(receipt_id) is None:
        raise PromotionReceiptError("receipt_identity_invalid")
    store, _, _, _ = _prepare_store(receipt_store, resettable_roots)
    registry_path = store / "registry.json"
    with _receipt_store_writer_lock(store):
        existing = _load_trusted_registry(
            registry_path,
            issuer_key_id=issuer_key_id,
            issuer_public_key=issuer_public_key,
        )
        entries = dict(_mapping(existing["entries"], code="registry_corrupt"))
        raw_entry = entries.get(receipt_id)
        if raw_entry is None:
            raise PromotionReceiptError("receipt_unregistered")
        entry = dict(_mapping(raw_entry, code="registry_corrupt"))
        if entry["status"] == "revoked":
            return existing
        if entry["status"] != "issued":
            raise PromotionReceiptError("registry_entry_invalid")
        entry["status"] = "revoked"
        entries[receipt_id] = entry
        updated: dict[str, object] = {
            "registry_version": REGISTRY_VERSION,
            "trusted_keys": dict(
                _mapping(existing["trusted_keys"], code="registry_corrupt")
            ),
            "entries": entries,
        }
        _replace_registry(registry_path, updated)
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
    source_repo: Path,
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
    (
        validated_identity,
        validated_checks,
        validated_report,
        migration_snapshots,
    ) = _bind_promotion_test_report(
        rendered=rendered,
        channel_manifest=channel_manifest,
        prod_admission_context=prod_admission_context,
        check_report=check_report,
        source_repo=source_repo,
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
        check_report=validated_report,
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
        "check_report_identity": receipt["check_report_identity"],
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
    with _receipt_store_writer_lock(store):
        _load_trusted_registry(
            registry_path,
            issuer_key_id=issuer_key_id,
            issuer_public_key=issuer_public_key,
        )
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
        _install_content_addressed(receipt_path, receipt_bytes)
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
        _publish_registry_entry(
            registry_path,
            receipt=receipt,
            issuer_public_key=issuer_public_key,
        )
        _fence_receipt_store(store)
        return receipt


def _validate_receipt(
    receipt: object,
    registry: object,
    expected_identity: object,
    check_report: object,
    source_repo: Path,
    *,
    now: datetime,
) -> dict[str, object]:
    if receipt is None:
        raise PromotionReceiptError("receipt_missing")
    receipt_mapping = _mapping(receipt, code="receipt_invalid")
    registry_mapping = _mapping(registry, code="registry_missing")
    identity, requested_baseline_sha = _validate_admission_context(expected_identity)
    migration_baseline_sha = _resolve_authoritative_prod_baseline(source_repo)
    if requested_baseline_sha != migration_baseline_sha:
        raise PromotionReceiptError("migration_baseline_mismatch")
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
    expected_baseline_identity = f"git:{migration_baseline_sha}"
    if receipt_mapping.get("migration_baseline_identity") != expected_baseline_identity:
        raise PromotionReceiptError("migration_baseline_mismatch")
    report = _mapping(check_report, code="check_report_invalid")
    if set(report) != _REPORT_FIELDS or report.get("report_version") != REPORT_VERSION:
        raise PromotionReceiptError("check_report_invalid")
    report_identity = _validate_identity(report.get("identity"))
    if report_identity != identity:
        raise PromotionReceiptError("check_report_identity_mismatch")
    if report.get("migration_baseline_identity") != expected_baseline_identity:
        raise PromotionReceiptError("migration_baseline_mismatch")
    migration_set_identity = report.get("migration_set_identity")
    if (
        not isinstance(migration_set_identity, str)
        or _DIGEST.fullmatch(migration_set_identity) is None
        or receipt_mapping.get("migration_set_identity") != migration_set_identity
    ):
        raise PromotionReceiptError("migration_set_mismatch")
    candidate_identity = report.get("candidate_identity")
    if not isinstance(candidate_identity, str) or _DIGEST.fullmatch(candidate_identity) is None:
        raise PromotionReceiptError("check_report_invalid")
    if not all(_validate_checks(report.get("check_results")).values()):
        raise PromotionReceiptError("check_report_not_pass")
    expected_report_identity = "sha256:" + hashlib.sha256(
        _canonical_bytes(report)
    ).hexdigest()
    if receipt_mapping.get("check_report_identity") != expected_report_identity:
        raise PromotionReceiptError("check_report_mismatch")
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
    check_report: object,
    source_repo: Path,
    now: datetime,
) -> dict[str, object]:
    """Return admission evidence only after exact prod receipt validation.

    This is the production pre-activation call site.  It has no activation,
    deployment, restart, migration, or emergency-bypass capability.
    """
    validated = _validate_receipt(
        receipt,
        registry,
        expected_identity,
        check_report,
        source_repo,
        now=now,
    )
    return {
        "activation_permitted": True,
        "receipt_id": validated["receipt_id"],
    }


def prepare_prod_activation(
    receipt: object,
    registry: object,
    prod_admission_context: object,
    *,
    check_report: object,
    source_repo: Path,
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
        check_report=check_report,
        source_repo=source_repo,
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
    validate.add_argument("--check-report", type=Path, required=True)
    validate.add_argument("--now", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    try:
        if args.command == "promotion-test-verify":
            private_key = _read_private_key(args.issuer_private_key)
            public_key = private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            result = write_promotion_test_terminal_receipt(
                attempt_id=args.attempt_id,
                rendered=_read_json(args.rendered, code="candidate_unavailable"),
                channel_manifest=_read_json(args.manifest, code="manifest_unavailable"),
                prod_admission_context=_read_json(
                    args.admission_context,
                    code="identity_unavailable",
                ),
                check_report=_read_json(args.checks, code="checks_unavailable"),
                source_repo=repo_root,
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
                check_report=_read_json(
                    args.check_report,
                    code="check_report_unavailable",
                ),
                source_repo=repo_root,
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
    "revoke_promotion_test_receipt",
    "write_promotion_test_terminal_receipt",
]
