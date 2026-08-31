#!/usr/bin/env python3
"""Qualify one explicitly supplied vault root without mutating it.

This is a diagnostic boundary adapter, not a runtime vault selector.  It uses
descriptor-relative, no-follow filesystem operations so that a bounded probe
cannot follow a symlink out of the supplied root.  iCloud/File Provider
hydration and convergence are deliberately reported as unknown: a successful
local read is not evidence for those properties.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import platform
import stat
import sys
from pathlib import Path
from typing import Any, Iterable


PROBE_VERSION = "mac-vault-bridge-probe.v1"
MARKER_PATH = "settings/vault.md"
DEFAULT_PATHS = (MARKER_PATH,)
MAX_PATHS = 32
MAX_RELATIVE_PATH_BYTES = 240
MAX_READ_BYTES = 64 * 1024

UNKNOWN_REASONS = (
    "icloud_hydration_not_observable",
    "file_provider_state_not_observable",
    "atomic_replacement_not_observable",
    "global_serializability_not_provable",
    "conflict_free_convergence_not_provable",
)


class ProbeInputError(ValueError):
    """Raised for an unsafe or unbounded probe input."""


class ProbeAccessError(OSError):
    """Raised when a bounded target cannot be observed safely."""


def _digest(*parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _file_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _identity_digest(metadata: os.stat_result) -> str:
    """Return identity evidence without exposing a path or raw inode values."""

    return _digest(
        "filesystem-identity-v1",
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
    )


def _validate_relative_path(value: str) -> str:
    if not value or "\x00" in value:
        raise ProbeInputError("relative path is empty or contains NUL")
    if len(value.encode("utf-8")) > MAX_RELATIVE_PATH_BYTES:
        raise ProbeInputError("relative path exceeds the bounded length")
    if value.startswith("/") or value.startswith("\\"):
        raise ProbeInputError("absolute paths are not accepted")
    if "\\" in value:
        raise ProbeInputError("backslash path separators are not accepted")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ProbeInputError("path must be a normalized relative path")
    return "/".join(parts)


def _bounded_paths(paths: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    for raw_path in paths:
        path = _validate_relative_path(raw_path)
        if path not in result:
            result.append(path)
    if len(result) > MAX_PATHS:
        raise ProbeInputError(f"at most {MAX_PATHS} paths may be probed")
    return tuple(result)


def _no_follow_flag() -> int:
    return getattr(os, "O_NOFOLLOW", 0)


def _open_root(root: Path) -> tuple[int, os.stat_result]:
    try:
        root_lstat = os.lstat(root)
    except FileNotFoundError as exc:
        raise ProbeAccessError("root_missing") from exc
    except OSError as exc:
        raise ProbeAccessError("root_unreadable") from exc
    if stat.S_ISLNK(root_lstat.st_mode):
        raise ProbeAccessError("root_symlink_rejected")
    if not stat.S_ISDIR(root_lstat.st_mode):
        raise ProbeAccessError("root_not_directory")
    if root_lstat.st_mode & 0o555 == 0:
        raise ProbeAccessError("root_unreadable")

    try:
        fd = os.open(
            root,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _no_follow_flag(),
        )
    except FileNotFoundError as exc:
        raise ProbeAccessError("root_missing") from exc
    except OSError as exc:
        raise ProbeAccessError("root_unreadable") from exc
    try:
        metadata = os.fstat(fd)
    except OSError:
        os.close(fd)
        raise ProbeAccessError("root_unreadable")
    return fd, metadata


def _open_relative(root_fd: int, relative_path: str) -> tuple[int, os.stat_result]:
    components = relative_path.split("/")
    current_fd = os.dup(root_fd)
    try:
        for index, component in enumerate(components):
            final = index == len(components) - 1
            flags = os.O_RDONLY | _no_follow_flag()
            if not final:
                flags |= getattr(os, "O_DIRECTORY", 0)
            try:
                entry_metadata = os.lstat(component, dir_fd=current_fd)
                if stat.S_ISLNK(entry_metadata.st_mode):
                    raise ProbeAccessError("symlink_component_rejected")
                if final and not (
                    stat.S_ISREG(entry_metadata.st_mode)
                    or stat.S_ISDIR(entry_metadata.st_mode)
                ):
                    raise ProbeAccessError("unsupported_special_file")
                if not final and not stat.S_ISDIR(entry_metadata.st_mode):
                    raise ProbeAccessError("target_not_directory")
                next_fd = os.open(component, flags, dir_fd=current_fd)
            except ProbeAccessError:
                raise
            except FileNotFoundError as exc:
                raise ProbeAccessError("target_missing") from exc
            except PermissionError as exc:
                raise ProbeAccessError("target_unreadable") from exc
            except OSError as exc:
                if exc.errno == errno.ELOOP:
                    raise ProbeAccessError("symlink_component_rejected") from exc
                raise ProbeAccessError("target_unreadable") from exc
            os.close(current_fd)
            current_fd = next_fd
        metadata = os.fstat(current_fd)
        if metadata.st_mode & 0o444 == 0:
            raise ProbeAccessError("target_unreadable")
        return current_fd, metadata
    except BaseException:
        os.close(current_fd)
        raise


def _read_descriptor(fd: int, metadata: os.stat_result) -> tuple[bytes, bool]:
    if not stat.S_ISREG(metadata.st_mode):
        return b"", False
    chunks: list[bytes] = []
    remaining = MAX_READ_BYTES + 1
    while remaining:
        chunk = os.read(fd, min(16 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    data = b"".join(chunks)
    return data[:MAX_READ_BYTES], len(data) > MAX_READ_BYTES


def _unknown_observation(path: str, reason: str) -> dict[str, Any]:
    status = "missing" if reason == "target_missing" else "unknown"
    return {
        "relative_path": path,
        "status": status,
        "reason": reason,
        "hydration": {"status": "unknown", "reason": UNKNOWN_REASONS[0]},
    }


def _observe_path(root_fd: int, path: str) -> dict[str, Any]:
    try:
        fd, metadata = _open_relative(root_fd, path)
    except ProbeAccessError as exc:
        return _unknown_observation(path, str(exc))

    try:
        result: dict[str, Any] = {
            "relative_path": path,
            "status": "observed",
            "kind": (
                "file"
                if stat.S_ISREG(metadata.st_mode)
                else "directory"
                if stat.S_ISDIR(metadata.st_mode)
                else "other"
            ),
            "filesystem_identity_digest": _identity_digest(metadata),
            "hydration": {"status": "unknown", "reason": UNKNOWN_REASONS[0]},
            "file_provider_state": {"status": "unknown", "reason": UNKNOWN_REASONS[1]},
        }
        if stat.S_ISREG(metadata.st_mode):
            try:
                data, truncated = _read_descriptor(fd, metadata)
            except OSError:
                return _unknown_observation(path, "target_read_failed")
            result.update(
                {
                    "bytes_read": len(data),
                    "truncated": truncated,
                    "content_digest": _file_digest(data),
                }
            )
        else:
            result["bytes_read"] = 0
            result["truncated"] = False
        return result
    finally:
        os.close(fd)


def _invalid_report(reason: str, paths: tuple[str, ...], *, platform_status: str) -> dict[str, Any]:
    return {
        "probe_version": PROBE_VERSION,
        "read_only": True,
        "runtime_selector": False,
        "platform": {
            "name": platform.system().lower(),
            "status": platform_status,
            "reason": None if platform_status == "supported" else "mac_only_observations_unsupported",
        },
        "root": {"valid": False, "reason": reason},
        "valid_root": {"status": "false", "reason": reason},
        "marker": {"relative_path": MARKER_PATH, "status": "unknown", "reason": reason},
        "observations": [_unknown_observation(path, reason) for path in paths],
        "unknown_reasons": [reason, *UNKNOWN_REASONS],
    }


def probe(root: Path | str, paths: Iterable[str] = DEFAULT_PATHS) -> dict[str, Any]:
    """Return a redacted report for one root and bounded relative paths."""

    bounded_paths = _bounded_paths(paths)
    platform_status = "supported" if platform.system() == "Darwin" else "unsupported"
    root_path = Path(root).expanduser()
    try:
        root_fd, root_metadata = _open_root(root_path)
    except ProbeAccessError as exc:
        return _invalid_report(str(exc), bounded_paths, platform_status=platform_status)

    try:
        marker = _observe_path(root_fd, MARKER_PATH)
        marker_status = (
            "present"
            if marker["status"] == "observed" and marker.get("kind") == "file"
            else marker["status"]
        )
        report: dict[str, Any] = {
            "probe_version": PROBE_VERSION,
            "read_only": True,
            "runtime_selector": False,
            "platform": {
                "name": platform.system().lower(),
                "status": platform_status,
                "reason": None if platform_status == "supported" else "mac_only_observations_unsupported",
            },
            "root": {
                "valid": True,
                "identity_digest": _identity_digest(root_metadata),
            },
            "valid_root": {"status": "true"},
            "marker": {
                "relative_path": MARKER_PATH,
                "status": marker_status,
                **(
                    {"reason": marker["reason"]}
                    if marker_status != "present" and "reason" in marker
                    else {}
                ),
            },
            "observations": [_observe_path(root_fd, path) for path in bounded_paths],
            "unknown_reasons": list(UNKNOWN_REASONS),
        }
        return report
    finally:
        os.close(root_fd)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only qualification probe for one explicit vault root."
    )
    parser.add_argument("--root", required=True, type=Path, help="explicit root to inspect")
    parser.add_argument(
        "--path",
        action="append",
        dest="paths",
        metavar="RELATIVE_PATH",
        help="bounded normalized relative path; may be repeated",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        paths = _bounded_paths(args.paths or DEFAULT_PATHS)
        report = probe(args.root, paths)
    except ProbeInputError as exc:
        parser.error(str(exc))
    print(json.dumps(report, sort_keys=True))
    return (
        0
        if report["root"]["valid"]
        and report["marker"]["status"] == "present"
        and all(item["status"] == "observed" for item in report["observations"])
        else 2
    )


if __name__ == "__main__":
    sys.exit(main())
