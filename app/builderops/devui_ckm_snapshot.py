"""Owner-admitted private CKM snapshot transfer; never a remote CKM query."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import stat
from typing import Any

from app.builderops.ckm.contracts import (
    CkmContractError, CompletenessManifest, ErrorEnvelope, ObjectClassCompleteness,
    ProjectionMarker, ResourceDto, ResultEnvelope, SnapshotManifest, TaggedValue,
    canonical_digest,
)
from app.builderops.control_plane.models import canonical_repository
from app.builderops.devui_composition import _validated_ckm_payload

CONTRACT = "devui_private_ckm_snapshot.v1"
POLICY = "ckm-single-operator-private-devui-v1"
FILENAME = "devui-ckm-capabilities.json"
MAX_BYTES = 8 * 1024 * 1024
MAX_CAPABILITIES = 500
MAX_AGE = timedelta(hours=24)
FIELDS = frozenset({"contract", "policy", "repository", "source_host", "target_host",
                    "component_id", "captured_at", "result", "content_sha256"})


@dataclass(frozen=True)
class PrivateCkmRead:
    result: ResultEnvelope | ErrorEnvelope
    transfer: dict[str, Any] | None = None


def _decode_result(value: Any) -> ResultEnvelope:
    if not isinstance(value, dict) or not isinstance(value.get("resources"), list):
        raise ValueError("unsupported CKM envelope")
    if len(value["resources"]) > MAX_CAPABILITIES:
        raise ValueError("CKM capture bound exceeded")
    resources = [ResourceDto(**{**row, "values": {
        key: TaggedValue(**tag) for key, tag in row["values"].items()
    }}) for row in value["resources"]]
    raw_snapshot = value["snapshot"]
    accounting = raw_snapshot["completeness"]
    snapshot = SnapshotManifest(**{
        **raw_snapshot,
        "completeness": CompletenessManifest(
            object_classes=[ObjectClassCompleteness(**row) for row in accounting["object_classes"]],
            complete=accounting["complete"],
        ),
        "read_set": {"capability": tuple(row.public_id for row in resources)},
    })
    result = ResultEnvelope(**{**value, "snapshot": snapshot, "resources": resources,
                               "projection": ProjectionMarker(**value["projection"])})
    _validated_ckm_payload(result)
    if result.to_dict() != value:
        raise ValueError("CKM envelope changed during decoding")
    return result


def build_private_snapshot(
    result: ResultEnvelope, *, repository: str, captured_at: datetime,
) -> dict[str, Any]:
    """Wrap an already-completed local query without changing its policy or watermarks."""
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ValueError("capture time must be timezone-aware")
    payload = _validated_ckm_payload(result)
    if len(result.resources) > MAX_CAPABILITIES:
        raise ValueError("CKM capture bound exceeded")
    unsigned = {
        "contract": CONTRACT, "policy": POLICY,
        "repository": canonical_repository(repository),
        "source_host": "demerzel", "target_host": "bob-1", "component_id": "devui_projection",
        "captured_at": captured_at.astimezone(timezone.utc).isoformat(), "result": payload,
    }
    return {**unsigned, "content_sha256": "sha256:" + canonical_digest(unsigned)}


def decode_private_snapshot(
    raw: bytes, *, repository: str, now: datetime | None = None,
) -> PrivateCkmRead:
    """Validate the complete transfer and original typed CKM query before use."""
    if len(raw) > MAX_BYTES:
        raise CkmContractError("private_snapshot_oversized", "Private CKM snapshot exceeds its bound")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def invalid_constant(_: str) -> None:
        raise ValueError("non-finite JSON value")

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
        if not isinstance(value, dict) or set(value) != FIELDS:
            raise ValueError("unsupported transfer fields")
        expected = {"contract": CONTRACT, "policy": POLICY,
                    "repository": canonical_repository(repository), "source_host": "demerzel",
                    "target_host": "bob-1", "component_id": "devui_projection"}
        if any(value[key] != item for key, item in expected.items()):
            raise ValueError("private transfer binding differs")
        unsigned = {key: item for key, item in value.items() if key != "content_sha256"}
        if value["content_sha256"] != "sha256:" + canonical_digest(unsigned):
            raise ValueError("private transfer content differs")
        captured = datetime.fromisoformat(value["captured_at"].replace("Z", "+00:00"))
        current = now or datetime.now(timezone.utc)
        if captured.tzinfo is None or captured.utcoffset() is None or current.tzinfo is None:
            raise ValueError("unqualified transfer time")
        age = current - captured
        if age < timedelta(0) or age > MAX_AGE:
            raise CkmContractError("private_snapshot_stale", "Private CKM snapshot requires a fresh export")
        result = _decode_result(value["result"])
        return PrivateCkmRead(result, {
            **expected, "captured_at": captured.isoformat(),
            "expires_at": (captured + MAX_AGE).isoformat(),
            "content_sha256": value["content_sha256"],
            "scope": "captured_local_query_not_live_remote_query",
        })
    except CkmContractError:
        raise
    except Exception as exc:
        raise CkmContractError("private_snapshot_invalid", "Private CKM snapshot is invalid") from exc


def read_private_ckm(
    receipt_dir: Path, *, repository: str | None, now: datetime | None = None,
) -> PrivateCkmRead:
    path = receipt_dir / FILENAME

    def read(fd: int) -> bytes:
        os.lseek(fd, 0, os.SEEK_SET)
        with open(fd, "rb", closefd=False) as stream:
            value = stream.read(MAX_BYTES + 1)
        if len(value) > MAX_BYTES:
            raise CkmContractError("private_snapshot_oversized", "Private CKM snapshot exceeds its bound")
        return value

    def identity(info: os.stat_result) -> tuple[int, ...]:
        return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
                info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    try:
        if repository is None:
            raise CkmContractError("private_snapshot_unconfigured", "Private CKM source is unconfigured")
        if any(parent.is_symlink() for parent in (path, *path.parents)):
            raise CkmContractError("private_snapshot_invalid", "Private CKM source path is invalid")
        if not path.is_file():
            raise CkmContractError("private_snapshot_unavailable", "Private CKM snapshot has not been published")
        directory = os.open(receipt_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(FILENAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode):
                    raise CkmContractError("private_snapshot_invalid", "Private CKM source must be a regular file")
                raw = read(fd)
                result = decode_private_snapshot(raw, repository=repository, now=now)
                if (raw != read(fd)
                        or identity(before) != identity(os.fstat(fd))
                        or identity(before) != identity(os.stat(FILENAME, dir_fd=directory, follow_symlinks=False))):
                    raise CkmContractError("private_snapshot_changed", "Private CKM snapshot changed during read")
                return result
            finally:
                os.close(fd)
        finally:
            os.close(directory)
    except CkmContractError as exc:
        return PrivateCkmRead(ErrorEnvelope(exc))
    except Exception:
        return PrivateCkmRead(ErrorEnvelope(CkmContractError(
            "private_snapshot_unavailable", "Private CKM source could not be read",
        )))
