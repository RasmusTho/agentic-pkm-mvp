#!/usr/bin/env python3
"""Registered lifecycle and fail-closed cleanup guard for agent worktrees."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, TypeGuard, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import git_hygiene


REGISTRY_SCHEMA = "agentic-pkm.agent-worktree-registry.v1"
DEFAULT_TTL_SECONDS = 4 * 60 * 60
GENERATION_MARKER = "agent-worktree-generation"
# Bounds the path->branch history carried across worktree-path reuse, trading a
# bounded record size against completeness. No reuse count can guarantee every
# live lease is covered -- lease liveness is time-bound, and `expires_at: None`
# never expires -- so this is a pragmatic depth, not a proof. A branch displaced
# more than this many reuses back from the same canonical path loses its
# `worktree:<path>` preservation; the blast radius is the same bounded one this
# carry exists to fix (a merged branch ref deleted early, recoverable from the
# remote), and this repo randomizes worktree paths, so repeated reuse of one
# canonical path is not the normal shape.
MAX_PRIOR_BINDINGS = 8
# Transfer and move snapshots live inside the existing lifecycle record. Refuse
# rather than silently truncate an ownership chain that exceeds this bound.
MAX_TRANSFER_HISTORY = 32


class WorktreeLifecycleError(RuntimeError):
    """A worktree lifecycle operation is not safe or authorized."""


def _canonical(path: Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _same_worktree_path_identity(left: Path | str, right: Path | str) -> bool:
    """Conservatively match filesystem path aliases used by lifecycle policy."""

    return bool(
        git_hygiene._path_identities(str(left))
        & git_hygiene._path_identities(str(right))
    )


def _default_registry_path(cwd: Path) -> Path:
    raw = git_hygiene.run_git(["rev-parse", "--git-common-dir"], cwd)
    common_dir = Path(raw)
    if not common_dir.is_absolute():
        common_dir = cwd / common_dir
    return common_dir.resolve(strict=False) / "agent-worktrees.json"


def _worktree_identity(cwd: Path, worktree: Path) -> tuple[Path, str]:
    target = _canonical(worktree)
    entries = git_hygiene._parse_worktrees(
        git_hygiene.run_git(["worktree", "list", "--porcelain"], cwd)
    )
    if not entries:
        raise WorktreeLifecycleError("git reported no worktrees")
    root = _canonical(Path(entries[0]["worktree"]))
    for entry in entries:
        path = entry.get("worktree")
        if path is None or _canonical(Path(path)) != target:
            continue
        branch = entry.get("branch", "").removeprefix("refs/heads/")
        if not branch:
            raise WorktreeLifecycleError("detached worktrees cannot be registered")
        if target == root:
            raise WorktreeLifecycleError(
                "the shared root checkout cannot be registered as an agent worktree"
            )
        return target, branch
    raise WorktreeLifecycleError("worktree is not registered with git")


def _empty_registry() -> dict[str, Any]:
    return {"schema": REGISTRY_SCHEMA, "worktrees": {}}


def _read_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _empty_registry()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise WorktreeLifecycleError("worktree lifecycle registry is invalid") from exc
    if payload.get("schema") != REGISTRY_SCHEMA or not isinstance(
        payload.get("worktrees"), dict
    ):
        raise WorktreeLifecycleError("worktree lifecycle registry is invalid")
    return payload


def _write_registry(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _valid_generation(value: object) -> TypeGuard[str]:
    if not isinstance(value, str):
        return False
    try:
        return uuid.UUID(hex=value).hex == value
    except ValueError:
        return False


def _worktree_generation(cwd: Path, worktree: Path, *, create: bool) -> str:
    raw = git_hygiene.run_git(
        ["-C", str(worktree), "rev-parse", "--git-path", GENERATION_MARKER],
        cwd,
    )
    marker = Path(raw)
    if not marker.is_absolute():
        marker = worktree / marker
    marker = marker.resolve(strict=False)
    if marker.exists():
        generation = marker.read_text(encoding="utf-8").strip()
        if not _valid_generation(generation):
            raise WorktreeLifecycleError("worktree generation marker is invalid")
        return generation
    if not create:
        raise WorktreeLifecycleError("worktree generation marker is missing")

    # Creation must stay outside the shared lifecycle-registry lock, but it
    # still needs a per-checkout serialization boundary. Otherwise concurrent
    # fresh registrations or legacy migrations can each create a generation,
    # and the losing registry writer can replace the marker after the winner
    # commits, leaving the durable registry immediately inconsistent with the
    # live checkout.
    marker.parent.mkdir(parents=True, exist_ok=True)
    lock_path = marker.with_name(f"{marker.name}.lock")
    lock_descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    os.fchmod(lock_descriptor, 0o600)
    with os.fdopen(lock_descriptor, "a+b", closefd=True) as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            if marker.exists():
                generation = marker.read_text(encoding="utf-8").strip()
                if not _valid_generation(generation):
                    raise WorktreeLifecycleError(
                        "worktree generation marker is invalid"
                    )
                return generation

            generation = uuid.uuid4().hex
            descriptor, temporary_name = tempfile.mkstemp(
                dir=marker.parent,
                prefix=f".{marker.name}.",
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(
                    descriptor, "w", encoding="utf-8", closefd=True
                ) as handle:
                    os.fchmod(handle.fileno(), 0o600)
                    handle.write(f"{generation}\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, marker)
                _fsync_directory(marker.parent)
            finally:
                temporary.unlink(missing_ok=True)
            return generation
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _registry_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "a+b", closefd=True) as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _locked_registry(path: Path) -> Iterator[dict[str, Any]]:
    with _registry_lock(path):
        payload = _read_registry(path)
        yield payload
        _write_registry(path, payload)


def _lifecycle_records(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(key): dict(value)
        for key, value in payload["worktrees"].items()
        if isinstance(key, str) and isinstance(value, dict)
    }


def _locked_lifecycle_snapshot(path: Path) -> dict[str, dict[str, Any]]:
    with _registry_lock(path):
        return _lifecycle_records(_read_registry(path))


def _mark_generation_removed(record: dict[str, Any], *, removed_at: float) -> None:
    record["status"] = "removed"
    record["removed_at"] = removed_at
    record.pop("removal_pending_at", None)
    record.pop("removal_pending_from_status", None)


def _carried_prior_bindings(
    existing: Any,
    *,
    new_branch: str | None,
    timestamp: float,
) -> list[dict[str, Any]]:
    """Path->branch bindings this path held before the incoming registration.

    The registry is keyed by path, so re-registering a path replaces whatever
    record it held — including a removal tombstone. Dropping that record would
    strip the former branch's ``worktree:<path>`` lease authority and let cleanup
    reclassify it as an ordinary local branch, which is exactly the guarantee
    `git_hygiene._lifecycle_worktree_paths_for_branch` depends on. Carrying the
    displaced binding forward keeps that association durable across path reuse.

    Bindings are deduplicated by branch, most-recent-first, and bounded by
    ``MAX_PRIOR_BINDINGS`` so a heavily reused path cannot grow the registry
    without limit.
    """
    if not isinstance(existing, dict):
        return []
    carried: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _append(branch: object, removed_at: object) -> None:
        if not isinstance(branch, str) or not branch or branch == new_branch:
            return
        if branch in seen:
            return
        seen.add(branch)
        stamp = removed_at if isinstance(removed_at, (int, float)) else timestamp
        if isinstance(stamp, bool) or not math.isfinite(stamp):
            stamp = timestamp
        carried.append({"branch": branch, "removed_at": float(stamp)})

    _append(existing.get("branch"), existing.get("removed_at"))
    prior = existing.get("prior_bindings")
    if isinstance(prior, list):
        for entry in prior:
            if isinstance(entry, dict):
                _append(entry.get("branch"), entry.get("removed_at"))
    return carried[:MAX_PRIOR_BINDINGS]


def _restore_pending_generation(record: dict[str, Any]) -> None:
    previous_status = record.get("removal_pending_from_status")
    if previous_status not in {"active", "released", "complete"}:
        raise WorktreeLifecycleError("pending removal lifecycle state is invalid")
    record["status"] = previous_status
    record.pop("removal_pending_at", None)
    record.pop("removal_pending_from_status", None)


def _reconcile_removed_generations(cwd: Path, path: Path) -> None:
    """Durably retire generations whose checkout vanished before tombstoning."""

    with _registry_lock(path):
        payload = _read_registry(path)
        entries = git_hygiene._parse_worktrees(
            git_hygiene.run_git(["worktree", "list", "--porcelain"], cwd)
        )
        if not entries:
            raise WorktreeLifecycleError("git reported no worktrees")
        live_paths = {
            str(_canonical(Path(entry["worktree"]))): entry
            for entry in entries
            if isinstance(entry.get("worktree"), str)
        }
        removed_at = time.time()
        registry_changed = False
        for key, value in payload["worktrees"].items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            generation = value.get("generation")
            if value.get("status") != "removal_pending":
                continue
            if not _valid_generation(generation):
                continue
            if value.get("removal_pending_from_status") not in {
                "active",
                "released",
                "complete",
            }:
                continue
            live_entry = live_paths.get(str(_canonical(Path(key))))
            if live_entry is not None:
                try:
                    live_generation = _worktree_generation(
                        cwd,
                        Path(key),
                        create=False,
                    )
                except (OSError, RuntimeError, subprocess.SubprocessError):
                    # A present checkout without a trustworthy generation marker
                    # is indeterminate and must remain preserved.
                    continue
                if live_generation == generation:
                    _restore_pending_generation(value)
                    registry_changed = True
                    continue
            _mark_generation_removed(value, removed_at=removed_at)
            registry_changed = True
        if registry_changed:
            _write_registry(path, payload)


def _bind_live_generations(
    cwd: Path,
    records: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Invalidate planning copies that do not match the current checkout generation."""

    bound = {key: dict(value) for key, value in records.items()}
    missing_preserved = [
        (key, record)
        for key, record in bound.items()
        if record.get("status") == "missing_preserved"
    ]
    if missing_preserved:
        live_entries = _live_worktree_entries(cwd)
        for key, record in missing_preserved:
            _validate_missing_preserved_binding(
                cwd,
                key,
                record,
                live_entries=live_entries,
            )
    for key, record in bound.items():
        if record.get("status") in {"removed", "missing_preserved"}:
            # A tombstone's checkout is gone by construction, so the probe below
            # always fails and is always caught. No consumer reads a tombstone's
            # generation — `_lifecycle_worktree_paths_for_branch` reads only
            # path/branch and `_worktree_lifecycle_skip_reason` rejects on
            # `status` first — and tombstones are never pruned, so probing them
            # costs one subprocess per removed worktree on every report and
            # janitor run, forever.
            # `missing_preserved` is also terminal, but its dedicated validator
            # above requires both filesystem and Git registration absence.
            continue
        generation = record.get("generation")
        if not _valid_generation(generation):
            continue
        try:
            live_generation = _worktree_generation(cwd, Path(key), create=False)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            record["generation"] = None
            continue
        if live_generation != generation:
            record["generation"] = None
    return bound


@contextmanager
def _locked_lifecycle_authority(
    cwd: Path,
    path: Path,
    targets: list[dict[str, Any]],
) -> Iterator[Callable[[], None]]:
    """Revalidate target lifecycle records and hold authority through one Git action."""

    with _registry_lock(path):
        payload = _read_registry(path)
        records = _lifecycle_records(payload)
        authorized: list[tuple[str, str, str]] = []
        for target in targets:
            worktree = target.get("path")
            branch = target.get("branch")
            if not isinstance(worktree, str) or not isinstance(branch, str):
                raise WorktreeLifecycleError("cleanup target lifecycle identity is invalid")
            canonical, live_branch = _worktree_identity(cwd, Path(worktree))
            if str(canonical) != str(_canonical(Path(worktree))) or live_branch != branch:
                raise WorktreeLifecycleError("cleanup target checkout identity changed")
            if git_hygiene._worktree_dirty(str(canonical)) is not False:
                raise WorktreeLifecycleError("cleanup target worktree is dirty or unavailable")
            live_entries = git_hygiene._parse_worktrees(
                git_hygiene.run_git(["worktree", "list", "--porcelain"], cwd)
            )
            live_entry = next(
                (
                    entry
                    for entry in live_entries
                    if entry.get("worktree")
                    and _canonical(Path(entry["worktree"])) == canonical
                ),
                None,
            )
            if live_entry is None or "locked" in live_entry:
                raise WorktreeLifecycleError("cleanup target is missing or locked")
            expected_head = target.get("head")
            if (
                not isinstance(expected_head, str)
                or not expected_head
                or live_entry.get("HEAD") != expected_head
            ):
                raise WorktreeLifecycleError("cleanup target HEAD changed")
            reason = git_hygiene._worktree_lifecycle_skip_reason(
                worktree,
                branch,
                records,
                now=None,
            )
            if reason is not None:
                raise WorktreeLifecycleError(
                    f"cleanup target lifecycle authority changed: {reason}"
                )
            record = records[str(canonical)]
            generation = record.get("generation")
            if (
                not _valid_generation(generation)
                or _worktree_generation(cwd, canonical, create=False) != generation
            ):
                raise WorktreeLifecycleError("cleanup target generation changed")
            status = record.get("status")
            if status not in {"active", "released", "complete"}:
                raise WorktreeLifecycleError("cleanup target lifecycle state changed")
            authorized.append((str(canonical), generation, status))
        pending_at = time.time()
        for canonical_path, generation, status in authorized:
            record = payload["worktrees"].get(canonical_path)
            if (
                not isinstance(record, dict)
                or record.get("generation") != generation
                or record.get("status") != status
            ):
                raise WorktreeLifecycleError(
                    "cleanup target generation changed before pending transition"
                )
            record["status"] = "removal_pending"
            record["removal_pending_from_status"] = status
            record["removal_pending_at"] = pending_at
        _write_registry(path, payload)
        command_succeeded = False

        def mark_succeeded() -> None:
            nonlocal command_succeeded
            command_succeeded = True

        try:
            yield mark_succeeded
        finally:
            removed_at = time.time()
            for canonical_path, generation, _status in authorized:
                record = payload["worktrees"].get(canonical_path)
                if (
                    not isinstance(record, dict)
                    or record.get("generation") != generation
                    or record.get("status") != "removal_pending"
                ):
                    raise WorktreeLifecycleError(
                        "cleanup target generation changed before retirement"
                    )
                if command_succeeded:
                    _mark_generation_removed(record, removed_at=removed_at)
                else:
                    _restore_pending_generation(record)
            _write_registry(path, payload)


@contextmanager
def _locked_removed_generation_branch_authority(
    cwd: Path,
    path: Path,
    *,
    worktree: str,
    branch: str,
    generation: str,
) -> Iterator[None]:
    """Hold the exact tombstone authority through its resumed branch deletion."""

    canonical = _canonical(Path(worktree))
    with _registry_lock(path):
        payload = _read_registry(path)
        record = payload["worktrees"].get(str(canonical))
        if (
            not isinstance(record, dict)
            or record.get("generation") != generation
            or record.get("branch") != branch
            or record.get("status") != "removed"
        ):
            raise WorktreeLifecycleError(
                "cleanup target removed lifecycle authority changed"
            )
        reservation = canonical / ".agent-worktree-cleanup-reservation"
        parent_created = False
        try:
            try:
                canonical.parent.mkdir(mode=0o700)
                parent_created = True
            except FileExistsError:
                pass
            canonical.mkdir(mode=0o700)
            descriptor = os.open(
                reservation,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            os.close(descriptor)
        except FileExistsError as exc:
            raise WorktreeLifecycleError("cleanup target worktree was recreated") from exc
        try:
            live_entries = git_hygiene._parse_worktrees(
                git_hygiene.run_git(["worktree", "list", "--porcelain"], cwd)
            )
            if any(
                entry.get("worktree")
                and _canonical(Path(entry["worktree"])) == canonical
                for entry in live_entries
            ):
                raise WorktreeLifecycleError("cleanup target worktree was recreated")
            yield
        finally:
            try:
                reservation.unlink()
                canonical.rmdir()
            except OSError as exc:
                raise WorktreeLifecycleError(
                    "cleanup target path reservation could not be released"
                ) from exc
            if parent_created:
                try:
                    canonical.parent.rmdir()
                except OSError:
                    pass


def _assert_worktree_path_not_registered(
    cwd: Path,
    worktree: Path,
    *,
    live_entries: list[dict[str, str]] | None = None,
) -> None:
    target = _canonical(worktree)
    entries = live_entries if live_entries is not None else _live_worktree_entries(cwd)
    if any(
        isinstance(entry.get("worktree"), str)
        and _same_worktree_path_identity(entry["worktree"], target)
        for entry in entries
    ):
        raise WorktreeLifecycleError("worktree path is still registered with Git")


@contextmanager
def _reserve_absent_worktree_path(cwd: Path, worktree: Path) -> Iterator[None]:
    """Reserve an absent path so a concurrent Git worktree add cannot win."""

    target = _canonical(worktree)
    if os.path.lexists(target):
        raise WorktreeLifecycleError("worktree path was recreated")
    _assert_worktree_path_not_registered(cwd, target)

    missing_parents: list[Path] = []
    parent = target.parent
    while not os.path.lexists(parent):
        missing_parents.append(parent)
        next_parent = parent.parent
        if next_parent == parent:
            raise WorktreeLifecycleError("worktree path parent is unavailable")
        parent = next_parent

    created_parents: list[Path] = []
    reservation_identity: tuple[int, int] | None = None
    try:
        for missing_parent in reversed(missing_parents):
            try:
                missing_parent.mkdir(mode=0o700)
                created_parents.append(missing_parent)
            except FileExistsError:
                if missing_parent.is_symlink() or not missing_parent.is_dir():
                    raise WorktreeLifecycleError(
                        "worktree path parent changed during reservation"
                    )
        if _canonical(target) != target or os.path.lexists(target):
            raise WorktreeLifecycleError("worktree path was recreated")
        try:
            # Git's worktree-add path check accepts an absent candidate before
            # it creates the directory. An exclusive file at the target makes
            # that later mkdir fail even if Git passed its earlier check.
            descriptor = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError as exc:
            raise WorktreeLifecycleError("worktree path was recreated") from exc
        try:
            os.fchmod(descriptor, 0o600)
            stat_result = os.fstat(descriptor)
            reservation_identity = (stat_result.st_dev, stat_result.st_ino)
        finally:
            os.close(descriptor)
        current = os.lstat(target)
        if (
            (current.st_dev, current.st_ino) != reservation_identity
            or not stat.S_ISREG(current.st_mode)
        ):
            raise WorktreeLifecycleError(
                "missing-preserved path reservation changed during creation"
            )
        _assert_worktree_path_not_registered(cwd, target)
        yield
    finally:
        release_error: WorktreeLifecycleError | None = None
        if reservation_identity is not None:
            try:
                current = os.lstat(target)
                if (
                    (current.st_dev, current.st_ino) != reservation_identity
                    or not stat.S_ISREG(current.st_mode)
                ):
                    raise WorktreeLifecycleError(
                        "missing-preserved path reservation changed before release"
                    )
                target.unlink()
            except (OSError, WorktreeLifecycleError) as exc:
                release_error = WorktreeLifecycleError(
                    "missing-preserved path reservation could not be released"
                )
                release_error.__cause__ = exc
        for created_parent in reversed(created_parents):
            try:
                created_parent.rmdir()
            except OSError:
                pass
        if release_error is not None:
            raise release_error


def load_lifecycle_records(
    cwd: Path,
    *,
    registry_path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    path = _canonical(registry_path or _default_registry_path(cwd))
    return _lifecycle_records(_read_registry(path))


def _valid_authority_timestamp(value: object) -> TypeGuard[int | float]:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _validate_registration_snapshot(value: object, *, branch: object, depth: int,
                                    allow_unreleased: bool = False) -> None:
    fields = {"path", "branch", "generation", "owner", "registered_at",
              "authority_since", "authority_until", "released_at"}
    if (depth > MAX_TRANSFER_HISTORY or not isinstance(value, dict)
            or not fields <= value.keys()
            or set(value) - (fields | {"transfer_registration", "previous_registration"})
            or not isinstance(value.get("path"), str) or not Path(value["path"]).is_absolute()
            or value.get("branch") != branch or not isinstance(value.get("owner"), str)
            or not value["owner"] or not _valid_generation(value.get("generation"))
            or any(not _valid_authority_timestamp(value.get(key))
                   and not (allow_unreleased and value.get(key) is None)
                   for key in ("registered_at", "authority_since", "authority_until", "released_at"))):
        raise WorktreeLifecycleError("worktree lifecycle predecessor evidence is invalid")
    transfer = value.get("transfer_registration")
    if transfer is not None:
        _validate_transfer_registration(transfer, branch=branch, owner=value["owner"], depth=depth + 1)
    previous = value.get("previous_registration")
    if previous is not None:
        _validate_registration_snapshot(previous, branch=branch, depth=depth + 1)
        if previous["owner"] != value["owner"]:
            raise WorktreeLifecycleError("worktree lifecycle predecessor move evidence is invalid")


def _validate_transfer_registration(value: object, *, branch: object, owner: object, depth: int = 0) -> None:
    """Screen the bounded historical anchor independently of the live epoch."""
    required = {"state", "issue", "pending_comment_id", "pending_digest", "epoch", "path", "branch",
                "generation", "owner", "authority_since", "registration_read_at", "candidate_readback"}
    pinned_fields = {"ack_comment_id", "ack_digest", "ack_at", "verified_through"}
    if (depth > MAX_TRANSFER_HISTORY or not isinstance(value, dict) or value.get("state") not in {"prepared", "pinned"}
            or not required <= value.keys()
            or set(value) - (required | {"predecessor_registration"}
                             | (pinned_fields if value.get("state") == "pinned" else set()))
            or (value.get("state") == "pinned" and not pinned_fields <= value.keys())
            or type(value.get("issue")) is not int or value["issue"] < 1
            or type(value.get("pending_comment_id")) is not int or value["pending_comment_id"] < 1
            or not isinstance(value.get("pending_digest"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["pending_digest"])
            or not _valid_generation(value.get("epoch"))
            or not _valid_generation(value.get("generation"))
            or not isinstance(value.get("path"), str) or len(value["path"]) > 4096
            or not Path(value["path"]).is_absolute()
            or value.get("branch") != branch or value.get("owner") != owner
            or not _valid_authority_timestamp(value.get("authority_since"))
            or not _valid_authority_timestamp(value.get("registration_read_at"))
            or not isinstance(value.get("candidate_readback"), dict)):
        raise WorktreeLifecycleError("worktree transfer registration is invalid")
    candidate = value["candidate_readback"]
    if (set(candidate) != {"branch", "base", "base_sha", "head", "changed_files", "clean", "observed_at"}
            or candidate.get("branch") != branch or candidate.get("clean") is not True
            or not _valid_authority_timestamp(candidate.get("observed_at"))
            or not value["authority_since"] <= candidate["observed_at"] <= value["registration_read_at"]
            or not isinstance(candidate.get("base"), str)
            or any(not isinstance(candidate.get(k), str) or not re.fullmatch(r"[0-9a-f]{40,64}", candidate[k])
                   for k in ("base_sha", "head"))
            or not isinstance(candidate.get("changed_files"), list)
            or len(candidate["changed_files"]) > 4096
            or not all(isinstance(p, str) and 0 < len(p) <= 4096 for p in candidate["changed_files"])
            or sorted(set(candidate["changed_files"])) != candidate["changed_files"]):
        raise WorktreeLifecycleError("worktree transfer candidate is invalid")
    predecessor = value.get("predecessor_registration")
    if predecessor is not None:
        _validate_registration_snapshot(predecessor, branch=branch, depth=depth + 1)
    if value["state"] == "pinned":
        if (type(value.get("ack_comment_id")) is not int or value["ack_comment_id"] < 1
                or value["ack_comment_id"] == value["pending_comment_id"]
                or not isinstance(value.get("ack_digest"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", value["ack_digest"])
                or not _valid_authority_timestamp(value.get("ack_at"))
                or not _valid_authority_timestamp(value.get("verified_through"))
                or value["authority_since"] > value["registration_read_at"]
                or max(value["registration_read_at"], candidate["observed_at"]) >= value["ack_at"]
                or value["ack_at"] + 1 > value["verified_through"]):
            raise WorktreeLifecycleError("worktree transfer pin is invalid")


def _validate_authority_record(key: str, record: object) -> dict[str, object]:
    if not isinstance(record, dict):
        raise WorktreeLifecycleError("worktree lifecycle record is invalid")
    path = record.get("path")
    branch = record.get("branch")
    owner = record.get("owner")
    status = record.get("status")
    registered_at = record.get("registered_at")
    heartbeat_at = record.get("heartbeat_at")
    expires_at = record.get("expires_at")
    if (
        not isinstance(path, str)
        or str(_canonical(Path(path))) != key
        or path != key
        or not isinstance(branch, str)
        or not branch
        or not isinstance(owner, str)
        or not owner.strip()
        or not _valid_generation(record.get("generation"))
        or status
        not in {
            "active",
            "released",
            "complete",
            "removal_pending",
            "removed",
            "missing_preserved",
        }
        or not _valid_authority_timestamp(registered_at)
        or not _valid_authority_timestamp(heartbeat_at)
        or not _valid_authority_timestamp(expires_at)
        or registered_at > heartbeat_at
        or heartbeat_at > expires_at
    ):
        raise WorktreeLifecycleError("worktree lifecycle record is invalid")
    if status in {"released", "complete"}:
        terminal = record.get(f"{status}_at")
        if not _valid_authority_timestamp(terminal) or terminal != expires_at:
            raise WorktreeLifecycleError("worktree lifecycle record is invalid")
    for field in ("authority_since", "owner_since", "authority_until"):
        if field in record and not _valid_authority_timestamp(record[field]):
            raise WorktreeLifecycleError("worktree lifecycle validity evidence is invalid")
    if "authority_since" in record and record["authority_since"] > heartbeat_at:
        raise WorktreeLifecycleError("worktree lifecycle validity evidence is invalid")
    if "authority_until" in record and record["authority_until"] > expires_at:
        raise WorktreeLifecycleError("worktree lifecycle validity evidence is invalid")
    if "registration_epoch" in record and not _valid_generation(record["registration_epoch"]):
        raise WorktreeLifecycleError("worktree registration epoch is invalid")
    if "transfer_registration" in record:
        _validate_transfer_registration(record["transfer_registration"], branch=branch, owner=owner)
    for prior_owner in (record.get("prior_owner"), record.get("previous_registration")):
        if prior_owner is not None:
            _validate_registration_snapshot(prior_owner, branch=branch, depth=0, allow_unreleased=True)
    if status == "removal_pending":
        if (
            record.get("removal_pending_from_status")
            not in {"active", "released", "complete"}
            or not _valid_authority_timestamp(record.get("removal_pending_at"))
        ):
            raise WorktreeLifecycleError("worktree lifecycle record is invalid")
    if status == "removed" and not _valid_authority_timestamp(record.get("removed_at")):
        raise WorktreeLifecycleError("worktree lifecycle record is invalid")
    if status == "missing_preserved" and (
        not _valid_authority_timestamp(record.get("missing_preserved_at"))
        or record["missing_preserved_at"] < expires_at
        or record.get("missing_preserved_by") != owner
        or record.get("missing_preserved_disposition") != "retain-branch"
        or not isinstance(record.get("missing_preserved_branch_head"), str)
        or not re.fullmatch(r"[0-9a-f]{40,64}", record["missing_preserved_branch_head"])
        or any(
            name in record
            for name in (
                "removed_at",
                "removal_pending_at",
                "removal_pending_from_status",
                "released_at",
                "complete_at",
            )
        )
    ):
        raise WorktreeLifecycleError("worktree lifecycle record is invalid")
    prior = record.get("prior_bindings", [])
    if not isinstance(prior, list) or len(prior) > MAX_PRIOR_BINDINGS:
        raise WorktreeLifecycleError("worktree lifecycle record is invalid")
    prior_branches: set[str] = set()
    for binding in prior:
        if (
            not isinstance(binding, dict)
            or set(binding) != {"branch", "removed_at"}
            or not isinstance(binding.get("branch"), str)
            or not binding["branch"]
            or binding["branch"] == branch
            or binding["branch"] in prior_branches
            or not _valid_authority_timestamp(binding.get("removed_at"))
        ):
            raise WorktreeLifecycleError("worktree lifecycle record is invalid")
        prior_branches.add(binding["branch"])
    return dict(record)


def _live_worktree_entries(cwd: Path) -> list[dict[str, str]]:
    entries = git_hygiene._parse_worktrees(
        git_hygiene.run_git(["worktree", "list", "--porcelain"], cwd)
    )
    if not entries or any(
        not isinstance(entry.get("worktree"), str)
        or not Path(entry["worktree"]).is_absolute()
        or (
            "bare" not in entry
            and (
                not re.fullmatch(r"[0-9a-f]{40,64}", entry.get("HEAD", ""))
                or not (
                    "detached" in entry
                    or entry.get("branch", "").startswith("refs/heads/")
                )
            )
        )
        for entry in entries
    ):
        raise WorktreeLifecycleError("git worktree census is invalid")
    return entries


def _validate_missing_preserved_binding(
    cwd: Path,
    key: str,
    record: object,
    *,
    live_entries: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    """Validate a terminal preservation record while its checkout stays absent."""

    validated = _validate_authority_record(key, record)
    if validated.get("status") != "missing_preserved":
        return validated
    canonical = _canonical(Path(key))
    if str(canonical) != key or os.path.lexists(key):
        raise WorktreeLifecycleError("missing-preserved lifecycle path was recreated")
    entries = live_entries if live_entries is not None else _live_worktree_entries(cwd)
    if any(
        isinstance(entry.get("worktree"), str)
        and _same_worktree_path_identity(entry["worktree"], canonical)
        for entry in entries
    ):
        raise WorktreeLifecycleError("missing-preserved Git worktree was recreated")
    branch = validated.get("branch")
    if not isinstance(branch, str):
        raise WorktreeLifecycleError("missing-preserved lifecycle record is invalid")
    head = git_hygiene.run_git(
        ["rev-parse", "--verify", f"refs/heads/{branch}"], cwd
    )
    if not re.fullmatch(r"[0-9a-f]{40,64}", head):
        raise WorktreeLifecycleError("missing-preserved branch ref is unavailable")
    return validated


def _select_authority_records(
    raw_records: object,
    *,
    candidate_branch: str | None,
    candidate_paths: set[str] | None = None,
) -> dict[str, dict[str, object]]:
    """Select records whose branch identity can affect one cleanup candidate.

    Targeted cleanup must not turn an old, unrelated checkout into a global
    availability dependency.  Branch and prior-binding identity are therefore
    inspected first.  A record that cannot prove it is unrelated remains
    fail-closed; a relevant record still receives the complete authority and
    live-generation validation below.
    """

    if not isinstance(raw_records, dict):
        raise WorktreeLifecycleError("worktree lifecycle registry is invalid")
    selected: dict[str, dict[str, object]] = {}
    for key, value in raw_records.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise WorktreeLifecycleError("worktree lifecycle record is invalid")
        branch = value.get("branch")
        prior = value.get("prior_bindings", [])
        if not isinstance(branch, str) or not branch or not isinstance(prior, list):
            raise WorktreeLifecycleError("worktree lifecycle record is invalid")
        prior_branches: list[str] = []
        for binding in prior:
            if (
                not isinstance(binding, dict)
                or not isinstance(binding.get("branch"), str)
                or not binding["branch"]
            ):
                raise WorktreeLifecycleError("worktree lifecycle record is invalid")
            prior_branches.append(binding["branch"])
        relevant = (
            candidate_branch is None
            or candidate_branch in {branch, *prior_branches}
            or key in (candidate_paths or set())
            or value.get("path") in (candidate_paths or set())
        )
        if relevant:
            selected[key] = _validate_authority_record(key, value)
    return selected


def load_lifecycle_authority(
    cwd: Path,
    *,
    candidate_branch: str | None = None,
    registry_path: Path | None = None,
) -> dict[str, dict[str, object]]:
    """Return a generation-bound, fail-closed lifecycle authority snapshot.

    Unlike report-mode ``load_lifecycle_records``, destructive consumers may
    not interpret a missing registry or filtered malformed row as an empty
    authority set. Slow Git/marker reads stay outside the shared registry lock;
    a second locked read proves that the optimistic snapshot did not change.
    """

    path = _canonical(registry_path or _default_registry_path(cwd))
    initial_live_entries = (
        git_hygiene._parse_worktrees(
            git_hygiene.run_git(["worktree", "list", "--porcelain"], cwd)
        )
        if candidate_branch is not None
        else []
    )
    candidate_paths = {
        str(_canonical(Path(entry["worktree"])))
        for entry in initial_live_entries
        if candidate_branch is not None
        and isinstance(entry.get("worktree"), str)
        and entry.get("branch", "").removeprefix("refs/heads/") == candidate_branch
    }
    if not path.is_file() or path.is_symlink():
        raise WorktreeLifecycleError("worktree lifecycle registry is missing")
    with _registry_lock(path):
        if not path.is_file() or path.is_symlink():
            raise WorktreeLifecycleError("worktree lifecycle registry is missing")
        payload = _read_registry(path)
        snapshot = _select_authority_records(
            payload.get("worktrees"),
            candidate_branch=candidate_branch,
            candidate_paths=candidate_paths,
        )

    bound = _bind_live_generations(cwd, snapshot)
    live_entries = git_hygiene._parse_worktrees(
        git_hygiene.run_git(["worktree", "list", "--porcelain"], cwd)
    )
    live_by_path = {
        str(_canonical(Path(entry["worktree"]))): entry
        for entry in live_entries
        if isinstance(entry.get("worktree"), str)
    }
    current_candidate_paths = {
        key
        for key, entry in live_by_path.items()
        if candidate_branch is not None
        and entry.get("branch", "").removeprefix("refs/heads/") == candidate_branch
    }
    if current_candidate_paths != candidate_paths:
        raise WorktreeLifecycleError("worktree lifecycle authority changed")
    if any(
        record.get("status") != "removed"
        and not _valid_generation(record.get("generation"))
        for record in bound.values()
    ):
        raise WorktreeLifecycleError("worktree lifecycle generation is unavailable")
    for key, record in bound.items():
        entry = live_by_path.get(key)
        if record.get("status") == "missing_preserved":
            _validate_missing_preserved_binding(
                cwd,
                key,
                record,
                live_entries=live_entries,
            )
            if entry is not None:
                raise WorktreeLifecycleError("preserved lifecycle path is live")
            continue
        if record.get("status") == "removed":
            if entry is not None:
                raise WorktreeLifecycleError("preserved lifecycle path is live")
            continue
        if (
            entry is None
            or entry.get("branch", "").removeprefix("refs/heads/")
            != record.get("branch")
        ):
            raise WorktreeLifecycleError("worktree lifecycle identity is unavailable")

    with _registry_lock(path):
        if not path.is_file() or path.is_symlink():
            raise WorktreeLifecycleError("worktree lifecycle registry is missing")
        current = _select_authority_records(
            _read_registry(path).get("worktrees"),
            candidate_branch=candidate_branch,
            candidate_paths=current_candidate_paths,
        )
        if current != snapshot:
            raise WorktreeLifecycleError("worktree lifecycle authority changed")
    return {key: dict(value) for key, value in bound.items()}


def _lifecycle_authority_under_registry_lock(
    cwd: Path,
    path: Path,
    *,
    candidate_branch: str,
    allow_released_history: bool = False,
) -> dict[str, dict[str, object]]:
    """Read complete candidate authority while the caller holds the registry lock."""

    if not path.is_file() or path.is_symlink():
        raise WorktreeLifecycleError("worktree lifecycle registry is missing")
    initial_live_entries = git_hygiene._parse_worktrees(
        git_hygiene.run_git(["worktree", "list", "--porcelain"], cwd)
    )
    candidate_paths = {
        str(_canonical(Path(entry["worktree"])))
        for entry in initial_live_entries
        if isinstance(entry.get("worktree"), str)
        and entry.get("branch", "").removeprefix("refs/heads/") == candidate_branch
    }
    snapshot = _select_authority_records(
        _read_registry(path).get("worktrees"),
        candidate_branch=candidate_branch,
        candidate_paths=candidate_paths,
    )
    live_entries = git_hygiene._parse_worktrees(
        git_hygiene.run_git(["worktree", "list", "--porcelain"], cwd)
    )
    live_by_path = {
        str(_canonical(Path(entry["worktree"]))): entry
        for entry in live_entries
        if isinstance(entry.get("worktree"), str)
    }
    current_candidate_paths = {
        key
        for key, entry in live_by_path.items()
        if entry.get("branch", "").removeprefix("refs/heads/") == candidate_branch
    }
    if current_candidate_paths != candidate_paths:
        raise WorktreeLifecycleError("worktree lifecycle authority changed")
    ignored_history: set[str] = set()
    if allow_released_history:
        active = [row for key, row in snapshot.items() if key in current_candidate_paths
                  and row.get("status") == "active"]
        previous = active[0].get("previous_registration") if len(active) == 1 else None
        if isinstance(previous, dict) and _valid_authority_timestamp(previous.get("released_at")):
            for key, row in snapshot.items():
                if (key not in current_candidate_paths and row.get("status") == "released"
                        and key not in live_by_path and not Path(key).exists()
                        and _valid_authority_timestamp(row.get("released_at"))
                        and row["released_at"] <= previous["released_at"]):
                    if row["released_at"] == previous["released_at"]:
                        if any(row.get(field) != value for field, value in previous.items()):
                            raise WorktreeLifecycleError("released predecessor registration conflicts")
                    ignored_history.add(key)
    bound = _bind_live_generations(cwd, {key: row for key, row in snapshot.items() if key not in ignored_history})
    if any(
        record.get("status") != "removed"
        and not _valid_generation(record.get("generation"))
        for record in bound.values()
    ):
        raise WorktreeLifecycleError("worktree lifecycle generation is unavailable")
    for key, record in bound.items():
        entry = live_by_path.get(key)
        if record.get("status") == "missing_preserved":
            _validate_missing_preserved_binding(
                cwd,
                key,
                record,
                live_entries=live_entries,
            )
            if entry is not None:
                raise WorktreeLifecycleError("preserved lifecycle path is live")
            continue
        if record.get("status") == "removed":
            if entry is not None:
                raise WorktreeLifecycleError("preserved lifecycle path is live")
            continue
        if (
            entry is None
            or entry.get("branch", "").removeprefix("refs/heads/")
            != record.get("branch")
        ):
            raise WorktreeLifecycleError("worktree lifecycle identity is unavailable")
    current = _select_authority_records(
        _read_registry(path).get("worktrees"),
        candidate_branch=candidate_branch,
        candidate_paths=current_candidate_paths,
    )
    if current != snapshot:
        raise WorktreeLifecycleError("worktree lifecycle authority changed")
    return {key: dict(value) for key, value in bound.items()}


@contextmanager
def locked_lifecycle_authority(
    cwd: Path,
    *,
    candidate_branch: str,
    registry_path: Path | None = None,
    allow_released_history: bool = False,
) -> Iterator[Callable[[], dict[str, dict[str, object]]]]:
    """Fence lifecycle writers and yield a repeatable candidate authority reader."""

    path = _canonical(registry_path or _default_registry_path(cwd))
    with _registry_lock(path):
        yield lambda: _lifecycle_authority_under_registry_lock(
            cwd,
            path,
            candidate_branch=candidate_branch,
            allow_released_history=allow_released_history,
        )


def _assert_registration_available(
    record: dict[str, Any] | None,
    *,
    owner: str,
    now: float,
) -> None:
    expiry = record.get("expires_at") if record is not None else None
    active_for_other_owner = (
        record is not None
        and record.get("owner") != owner
        and record.get("status") == "active"
        and (
            not isinstance(expiry, (int, float))
            or isinstance(expiry, bool)
            or not math.isfinite(expiry)
            or expiry > now
        )
    )
    if active_for_other_owner:
        raise WorktreeLifecycleError("worktree has an active lifecycle owner")
    if record is not None and record.get("status") == "missing_preserved":
        raise WorktreeLifecycleError(
            "missing-preserved worktree path cannot be reused"
        )


def _assert_no_missing_preserved_path_alias(
    worktrees: dict[str, Any], requested: Path
) -> None:
    """Reject case/normalisation aliases of terminally preserved paths."""

    requested_identities = git_hygiene._path_identities(str(requested))
    for key, record in worktrees.items():
        if not isinstance(record, dict) or record.get("status") != "missing_preserved":
            continue
        recorded_path = record.get("path")
        if not isinstance(key, str) or not isinstance(recorded_path, str):
            raise WorktreeLifecycleError("missing-preserved lifecycle record is invalid")
        preserved_identities = git_hygiene._path_identities(key)
        preserved_identities |= git_hygiene._path_identities(recorded_path)
        if requested_identities & preserved_identities:
            raise WorktreeLifecycleError(
                "missing-preserved worktree path cannot be reused"
            )


def _lifecycle_update_snapshot(
    registry_path: Path,
    *,
    worktree: Path,
    owner: str,
    statuses: set[str],
    error: str,
) -> tuple[Path, dict[str, Any]]:
    """Capture target authority under a short lock for optimistic revalidation."""

    requested = _canonical(worktree)
    with _registry_lock(registry_path):
        payload = _read_registry(registry_path)
        value = payload["worktrees"].get(str(requested))
        record = dict(value) if isinstance(value, dict) else None
        if (
            record is None
            or record.get("path") != str(requested)
            or record.get("owner") != owner
            or record.get("status") not in statuses
        ):
            raise WorktreeLifecycleError(error)
        return requested, record


def _transfer_comment(comment: object, *, issue: int, pr: int | None) -> tuple[dict[str, Any], float, str]:
    """Validate a fresh controller-supplied GitHub comment readback."""
    import yaml

    class UniqueLoader(yaml.SafeLoader):
        pass

    def unique_mapping(loader: Any, node: Any) -> dict[Any, Any]:
        result: dict[Any, Any] = {}
        for key, value in loader.construct_pairs(node):
            if key in result:
                raise ValueError("duplicate field")
            result[key] = value
        return result

    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)
    allowed = {f"https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/issues/{number}"
               for number in (issue, pr) if number is not None}
    if (not isinstance(comment, dict) or type(comment.get("id")) is not int or comment["id"] < 1
            or comment.get("author_association") not in {"OWNER", "MEMBER", "COLLABORATOR"}
            or not isinstance(comment.get("user"), dict) or comment["user"].get("login") != "RasmusTho"
            or comment.get("issue_url") not in allowed or not isinstance(comment.get("body"), str)
            or len(comment["body"].encode()) > 65536
            or not isinstance(comment.get("created_at"), str)
            or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", comment["created_at"])
            or comment.get("updated_at") != comment["created_at"]):
        raise WorktreeLifecycleError("handoff comment is missing, edited or unauthenticated")
    try:
        at = datetime.strptime(comment["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        body = comment["body"]
        match = re.fullmatch(r"\s*```(?:yaml|yml|json)\s*\n(.*?)\n```\s*", body, re.S)
        parsed = yaml.load(match.group(1) if match else body, Loader=UniqueLoader)
    except (ValueError, TypeError, yaml.YAMLError, RecursionError) as exc:
        raise WorktreeLifecycleError("handoff comment is malformed") from exc
    receipt = parsed.get("lifecycle_handoff_receipt.v1") if isinstance(parsed, dict) else None
    if not isinstance(receipt, dict):
        raise WorktreeLifecycleError("handoff comment is malformed")
    return receipt, at, hashlib.sha256(body.encode()).hexdigest()


def _transfer_candidate(cwd: Path, *, worktree: Path, receipt: dict[str, Any], base_sha: str,
                        observed_at: float, verify_base_ref: bool = True) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40,64}", base_sha):
        raise WorktreeLifecycleError("transfer base SHA is invalid")
    base = receipt.get("base")
    if base not in ("main", base_sha):
        raise WorktreeLifecycleError("transfer base is invalid")
    try:
        git = git_hygiene.run_git
        head = git(["-C", str(worktree), "rev-parse", "--verify", "HEAD^{commit}"], cwd)
        base_to_check = base if verify_base_ref else base_sha
        resolved_base = git(["-C", str(worktree), "rev-parse", "--verify", f"{base_to_check}^{{commit}}"], cwd)
        dirty = git(["-C", str(worktree), "status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd)
        changed = git(["-C", str(worktree), "diff", "--name-only", "--find-renames", "-z", f"{base_sha}...{head}"], cwd)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise WorktreeLifecycleError("transfer candidate readback is unavailable") from exc
    files = sorted(p for p in changed.split("\0") if p)
    if (dirty or resolved_base != base_sha or head != receipt.get("unpublished_candidate_head")
            or files != receipt.get("changed_files")):
        raise WorktreeLifecycleError("transfer candidate is dirty or differs from the receipt")
    return {"branch": receipt["branch"], "base": base, "base_sha": base_sha, "head": head,
            "changed_files": files, "clean": True, "observed_at": observed_at}


def _assert_local_history_precedes_remote(prior: object, receipt: dict[str, Any]) -> None:
    """Admit this host's last owner only as history before a remote predecessor.

    The trusted coordinator's reconciled remote readback names the immediate
    predecessor of a cross-host transfer. A local owner that was not released,
    or whose release does not precede the remote claim, is unresolved history.
    """
    remote = receipt.get("predecessor_dispatcher")
    value = remote.get("claimed_at") if isinstance(remote, dict) else None
    try:
        claimed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else None
    except ValueError:
        claimed = None
    if claimed is None or claimed.tzinfo is None:
        raise WorktreeLifecycleError("remote predecessor claim time is invalid")
    if prior is not None and (not isinstance(prior, dict)
            or not _valid_authority_timestamp(prior.get("released_at"))
            or not _valid_authority_timestamp(prior.get("authority_until"))
            or prior["authority_until"] > prior["released_at"]
            or prior["released_at"] >= claimed.timestamp()):
        raise WorktreeLifecycleError(
            "local predecessor history is unreleased or overlaps the remote predecessor; reconcile through maintenance")


def _screen_transfer_workspace(cwd: Path, worktree: Path, workspace_root: Path) -> None:
    """Never run host Git against a checkout inside the model workspace root."""
    if not workspace_root.is_absolute() or _canonical(workspace_root) == Path("/"):
        raise WorktreeLifecycleError("controller workspace root is invalid")
    root = _canonical(workspace_root)
    if _canonical(cwd).is_relative_to(root) or _canonical(worktree).is_relative_to(root):
        raise WorktreeLifecycleError("transfer checkout must be outside model workspaces")


def prepare_transfer_registration(cwd: Path, *, worktree: Path, owner: str, issue: int,
                                  pending_comment: dict[str, Any], base_sha: str,
                                  workspace_root: Path,
                                  pr: int | None = None, registry_path: Path | None = None,
                                  now: float | None = None) -> dict[str, Any]:
    """Read H1 and reserve the existing row before the successor posts its ACK."""
    receipt, pending_at, digest = _transfer_comment(pending_comment, issue=issue, pr=pr)
    _screen_transfer_workspace(cwd, worktree, workspace_root)
    path = _canonical(registry_path or _default_registry_path(cwd))
    if path != _canonical(_default_registry_path(cwd)):
        raise WorktreeLifecycleError("transfer requires the repository's existing lifecycle registry")
    requested, snapshot = _lifecycle_update_snapshot(path, worktree=worktree, owner=owner,
                        statuses={"active"}, error="active successor registration is required")
    canonical, branch = _worktree_identity(cwd, worktree)
    generation = _worktree_generation(cwd, canonical, create=False)
    predecessor = snapshot.get("prior_owner")
    remote_dispatcher = receipt.get("predecessor_dispatcher")
    if remote_dispatcher is not None:
        if not isinstance(remote_dispatcher, dict) or remote_dispatcher.get("history_reconciled") is not True:
            raise WorktreeLifecycleError("remote predecessor history is unreconciled")
        # The reconciled remote readback is the immediate predecessor; this
        # host's own last owner is older history and is not recorded as one.
        _assert_local_history_precedes_remote(predecessor, receipt)
        predecessor = None
    elif isinstance(predecessor, dict):
        if ("transfer_registration" in predecessor
                and (not isinstance(predecessor["transfer_registration"], dict)
                     or predecessor["transfer_registration"].get("state") != "pinned")):
            raise WorktreeLifecycleError("predecessor transfer history is unproved; reconcile through maintenance")
        if not _valid_authority_timestamp(predecessor.get("released_at")):
            raise WorktreeLifecycleError("predecessor registration ended without release; reconcile through maintenance")
    if (canonical != requested or receipt.get("issue") != issue or receipt.get("branch") != branch
            or receipt.get("writable_worktree") != str(canonical)
            or receipt.get("successor_acknowledgment") is not None
            or not isinstance(receipt.get("successor"), dict)
            or receipt["successor"].get("session") != owner):
        raise WorktreeLifecycleError("pending handoff does not bind the successor registration")
    candidate = _transfer_candidate(cwd, worktree=canonical, receipt=receipt, base_sha=base_sha,
                                    observed_at=time.time() if now is None else now)
    candidate["observed_at"] = time.time() if now is None else now
    with _locked_registry(path) as payload:
        timestamp = time.time() if now is None else now
        record = payload["worktrees"].get(str(canonical))
        if (record != snapshot or not isinstance(record, dict) or record.get("status") != "active"
                or record.get("branch") != branch or record.get("generation") != generation
                or not _valid_generation(record.get("registration_epoch"))
                or not _valid_authority_timestamp(record.get("authority_since"))
                or not _valid_authority_timestamp(record.get("expires_at"))
                or not _valid_authority_timestamp(record.get("heartbeat_at")) or timestamp < record["heartbeat_at"]
                or candidate["observed_at"] > timestamp
                or timestamp >= record["expires_at"] or pending_at + 1 > timestamp
                or (isinstance(record.get("transfer_registration"), dict)
                    and record["transfer_registration"].get("state") == "pinned")):
            raise WorktreeLifecycleError("successor registration or pending transfer changed")
        existing = record.get("transfer_registration")
        if (isinstance(existing, dict) and existing.get("state") == "prepared"
                and existing.get("epoch") == record["registration_epoch"]
                and existing.get("pending_comment_id") == pending_comment["id"]
                and existing.get("pending_digest") == digest):
            _validate_transfer_registration(existing, branch=branch, owner=owner)
            if ({k: v for k, v in candidate.items() if k != "observed_at"}
                    != {k: v for k, v in existing["candidate_readback"].items() if k != "observed_at"}):
                raise WorktreeLifecycleError("prepared transfer candidate changed")
            return {"successor_registration": {"path": existing["path"], "branch": branch, "owner": owner,
                    "generation": generation, "epoch": existing["epoch"],
                    "observed_at": existing["registration_read_at"]},
                    "candidate_readback": existing["candidate_readback"]}
        proof = {"state": "prepared", "issue": issue, "pending_comment_id": pending_comment["id"],
                 "pending_digest": digest, "epoch": record["registration_epoch"], "path": str(canonical),
                 "branch": branch, "generation": generation, "owner": owner,
                 "authority_since": record["authority_since"], "registration_read_at": timestamp,
                 "candidate_readback": candidate}
        if isinstance(predecessor, dict):
            # Preserve the locked predecessor snapshot, including its earlier
            # pinned transfer and moves, as part of this immutable proof.
            proof["predecessor_registration"] = dict(predecessor)
        _validate_transfer_registration(proof, branch=branch, owner=owner)
        record["transfer_registration"] = proof
        return {"successor_registration": {"path": str(canonical), "branch": branch, "owner": owner,
                "generation": generation, "epoch": proof["epoch"], "observed_at": timestamp},
                "candidate_readback": candidate}


def pin_transfer_registration(cwd: Path, *, worktree: Path, owner: str, issue: int,
                              pending_comment: dict[str, Any], ack_comment: dict[str, Any],
                              workspace_root: Path,
                              pr: int | None = None, registry_path: Path | None = None,
                              now: float | None = None) -> dict[str, Any]:
    """Pin the ACK only after its entire server second within the same live epoch."""
    pending, pending_at, pending_digest = _transfer_comment(pending_comment, issue=issue, pr=pr)
    receipt, ack_at, ack_digest = _transfer_comment(ack_comment, issue=issue, pr=pr)
    _screen_transfer_workspace(cwd, worktree, workspace_root)
    path = _canonical(registry_path or _default_registry_path(cwd))
    if path != _canonical(_default_registry_path(cwd)):
        raise WorktreeLifecycleError("transfer requires the repository's existing lifecycle registry")
    requested, snapshot = _lifecycle_update_snapshot(path, worktree=worktree, owner=owner,
                        statuses={"active"}, error="active successor registration is required")
    proof = snapshot.get("transfer_registration")
    if not isinstance(proof, dict) or proof.get("state") not in {"prepared", "pinned"}:
        raise WorktreeLifecycleError("prepared transfer is unavailable")
    _validate_transfer_registration(proof, branch=snapshot.get("branch"), owner=owner)
    if proof["state"] == "pinned":
        if (proof.get("pending_comment_id") != pending_comment["id"]
                or proof.get("pending_digest") != pending_digest
                or proof.get("ack_comment_id") != ack_comment["id"]
                or proof.get("ack_digest") != ack_digest or proof.get("ack_at") != ack_at):
            raise WorktreeLifecycleError("pinned transfer cannot be replaced")
        return dict(proof)
    ack = receipt.get("successor_acknowledgment")
    expected_registration = {"path": proof["path"], "branch": proof["branch"], "owner": owner,
                             "generation": proof["generation"], "epoch": proof["epoch"],
                             "observed_at": proof["registration_read_at"]}
    if (pending_comment["id"] != proof["pending_comment_id"] or pending_digest != proof["pending_digest"]
            or pending_at + 1 > ack_at or pending != {k: v for k, v in receipt.items() if k != "successor_acknowledgment"}
            or not isinstance(ack, dict) or ack.get("successor_registration") != expected_registration
            or ack.get("candidate_readback") != proof["candidate_readback"]
            or max(proof["registration_read_at"], proof["candidate_readback"]["observed_at"]) >= ack_at):
        raise WorktreeLifecycleError("acknowledgment differs from the prepared readbacks")
    canonical, branch = _worktree_identity(cwd, worktree)
    generation = _worktree_generation(cwd, canonical, create=False)
    candidate = _transfer_candidate(cwd, worktree=canonical, receipt=pending,
                                    base_sha=proof["candidate_readback"]["base_sha"],
                                    observed_at=proof["candidate_readback"]["observed_at"], verify_base_ref=False)
    if canonical != requested or candidate != proof["candidate_readback"]:
        raise WorktreeLifecycleError("transfer candidate changed before pin")
    with _locked_registry(path) as payload:
        timestamp = time.time() if now is None else now
        record = payload["worktrees"].get(str(canonical))
        if (record != snapshot or not isinstance(record, dict) or record.get("status") != "active"
                or record.get("registration_epoch") != proof["epoch"] or record.get("generation") != generation
                or record.get("branch") != branch or record.get("authority_since") != proof["authority_since"]
                or not _valid_authority_timestamp(record.get("expires_at"))
                or not _valid_authority_timestamp(record.get("heartbeat_at")) or timestamp < record["heartbeat_at"]
                or timestamp >= record["expires_at"] or ack_at + 1 > timestamp
                or ack_at + 1 > record["expires_at"]):
            raise WorktreeLifecycleError("successor epoch was not live through the acknowledgment")
        pinned = {**proof, "state": "pinned", "ack_comment_id": ack_comment["id"],
                  "ack_digest": ack_digest, "ack_at": ack_at, "verified_through": timestamp}
        _validate_transfer_registration(pinned, branch=branch, owner=owner)
        record["transfer_registration"] = pinned
        return dict(pinned)


def register_worktree(
    cwd: Path,
    *,
    worktree: Path,
    owner: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    registry_path: Path | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    if not owner.strip() or ttl_seconds < 1:
        raise WorktreeLifecycleError("owner and positive ttl are required")
    timestamp = time.time() if now is None else now
    path = _canonical(registry_path or _default_registry_path(cwd))
    requested = _canonical(worktree)
    with _registry_lock(path):
        initial_payload = _read_registry(path)
        _assert_no_missing_preserved_path_alias(
            initial_payload["worktrees"], requested
        )
        initial = initial_payload["worktrees"].get(str(requested))
        initial_record = dict(initial) if isinstance(initial, dict) else None
        _assert_registration_available(initial_record, owner=owner, now=timestamp)

    # Git subprocesses and generation-marker IO can be arbitrarily slow. Keep
    # them outside the shared registry lock, then compare the target record to
    # the snapshot again at the atomic write boundary below.
    canonical, branch = _worktree_identity(cwd, worktree)
    if canonical != requested:
        raise WorktreeLifecycleError("worktree identity changed before lifecycle write")
    if initial_record is not None and initial_record.get("branch") != branch:
        raise WorktreeLifecycleError(
            "worktree path retains another branch's ownership history; "
            "move the checkout to a replacement path and register it, or reconcile the existing lifecycle record"
        )
    generation = _worktree_generation(cwd, canonical, create=True)
    with _locked_registry(path) as payload:
        # Git and marker reads can block past expiry. Establish continuity at
        # the actual registry write, not at the earlier optimistic snapshot.
        timestamp = time.time() if now is None else now
        worktrees = payload["worktrees"]
        _assert_no_missing_preserved_path_alias(worktrees, canonical)
        existing = worktrees.get(str(canonical))
        current_record = dict(existing) if isinstance(existing, dict) else None
        _assert_registration_available(current_record, owner=owner, now=timestamp)
        if current_record != initial_record:
            raise WorktreeLifecycleError(
                "worktree lifecycle registration changed before commit"
            )
        if current_record is not None and current_record.get("branch") != branch:
            raise WorktreeLifecycleError(
                "worktree path retains another branch's ownership history; "
                "move the checkout to a replacement path and register it, or reconcile the existing lifecycle record"
            )
        if (current_record is not None and _valid_authority_timestamp(current_record.get("heartbeat_at"))
                and timestamp < current_record["heartbeat_at"]):
            raise WorktreeLifecycleError("worktree lifecycle clock moved backwards")
        prior_bindings = _carried_prior_bindings(
            current_record, new_branch=branch, timestamp=timestamp
        )
        same_identity = (current_record is not None and current_record.get("owner") == owner
                         and current_record.get("branch") == branch
                         and current_record.get("generation") == generation)
        continuous = (current_record is not None and same_identity and current_record.get("status") == "active"
                      and _valid_authority_timestamp(current_record.get("expires_at"))
                      and timestamp < current_record["expires_at"]
                      and _valid_authority_timestamp(current_record.get("authority_since"))
                      and _valid_generation(current_record.get("registration_epoch")))
        # The immediate predecessor is the latest ended ownership of this branch,
        # however it ended. Expiry and completion are not releases: their
        # snapshots carry no release time, so they can never satisfy a handoff,
        # and a returning earlier session cannot erase the later owner's anchor.
        # The branch can have moved paths, so the choice is made under the same
        # registry lock as this registration.
        history = []
        for key, row in worktrees.items():
            if isinstance(row, dict) and row.get("branch") == branch:
                _validate_authority_record(key, row)
                if row.get("status") in ("active", "released", "complete", "removal_pending", "removed", "missing_preserved"):
                    history.append(row)
        ended = [row for row in history if row["expires_at"] <= timestamp]
        ended.sort(key=lambda row: row["expires_at"], reverse=True)
        predecessor = None if continuous else (ended[0] if ended else None)
        same_owner = (current_record is not None and same_identity and (predecessor is None or
                      (predecessor.get("path") == str(canonical)
                       and predecessor.get("registered_at") == current_record.get("registered_at"))))
        tied = predecessor is not None and len(ended) > 1 and ended[0]["expires_at"] == ended[1]["expires_at"]
        if tied:
            raise WorktreeLifecycleError("ambiguous ended lifecycle predecessors; reconcile the registry")
        record: dict[str, Any] = {
            "path": str(canonical),
            "branch": branch,
            "generation": generation,
            "owner": owner,
            "status": "active",
            "registered_at": timestamp,
            "heartbeat_at": timestamp,
            "expires_at": timestamp + ttl_seconds,
            "authority_since": current_record["authority_since"] if continuous and current_record is not None else timestamp,
            "registration_epoch": current_record["registration_epoch"] if continuous and current_record is not None else uuid.uuid4().hex,
            "owner_since": (current_record.get("owner_since", current_record["registered_at"])
                            if same_owner and current_record is not None else timestamp),
        }
        if same_owner and current_record is not None:
            if "prior_owner" in current_record:
                record["prior_owner"] = current_record["prior_owner"]
            if "previous_registration" in current_record:
                record["previous_registration"] = current_record["previous_registration"]
            if "transfer_registration" in current_record:
                record["transfer_registration"] = current_record["transfer_registration"]
        elif predecessor is not None and predecessor.get("owner") == owner:
            if "prior_owner" in predecessor:
                record["prior_owner"] = predecessor["prior_owner"]
            if "transfer_registration" in predecessor:
                record["transfer_registration"] = predecessor["transfer_registration"]
            record["previous_registration"] = {key: predecessor.get(key) for key in (
                "path", "branch", "generation", "owner", "registered_at",
                "authority_since", "authority_until", "released_at")}
            if (isinstance(predecessor.get("previous_registration"), dict)
                    and predecessor["previous_registration"].get("owner") == owner):
                record["previous_registration"]["previous_registration"] = predecessor["previous_registration"]
        elif predecessor is not None:
            # Capture only fields needed to bind a transfer, including the
            # validity window recorded before release shortened expires_at.
            # An owner that expired or completed keeps a null release time.
            predecessor_snapshot: dict[str, Any] = {key: predecessor.get(key) for key in (
                "path", "branch", "generation", "owner", "registered_at",
                "authority_since", "authority_until", "released_at")}
            terminal = predecessor.get("status")
            if terminal == "removal_pending":
                terminal = predecessor.get("removal_pending_from_status")
            if (terminal not in ("released", "removed")
                    or predecessor.get("released_at") != predecessor.get("expires_at")
                    or (_valid_authority_timestamp(predecessor.get("complete_at"))
                        and predecessor["complete_at"] >= predecessor["expires_at"])):
                predecessor_snapshot["released_at"] = None
            if "transfer_registration" in predecessor:
                predecessor_snapshot["transfer_registration"] = predecessor["transfer_registration"]
                previous = predecessor.get("previous_registration")
                if isinstance(previous, dict) and previous.get("owner") == predecessor.get("owner"):
                    predecessor_snapshot["previous_registration"] = previous
            elif "prior_owner" in predecessor:
                # A null anchor records an unknown earlier transfer without
                # inventing proof when this row is overwritten by a new owner.
                predecessor_snapshot["transfer_registration"] = None
            record["prior_owner"] = predecessor_snapshot
            record["previous_registration"] = {key: predecessor.get(key) for key in (
                "path", "branch", "generation", "owner", "registered_at",
                "authority_since", "authority_until", "released_at")}
            record["previous_registration"]["released_at"] = predecessor_snapshot["released_at"]
        if prior_bindings:
            record["prior_bindings"] = prior_bindings
        _validate_authority_record(str(canonical), record)
        worktrees[str(canonical)] = record
        return dict(record)


def heartbeat_worktree(
    cwd: Path,
    *,
    worktree: Path,
    owner: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    registry_path: Path | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    if ttl_seconds < 1:
        raise WorktreeLifecycleError("positive ttl is required")
    timestamp = time.time() if now is None else now
    path = _canonical(registry_path or _default_registry_path(cwd))
    requested, snapshot = _lifecycle_update_snapshot(
        path,
        worktree=worktree,
        owner=owner,
        statuses={"active"},
        error="active matching lifecycle registration is required",
    )
    canonical, branch = _worktree_identity(cwd, worktree)
    if canonical != requested:
        raise WorktreeLifecycleError("active matching lifecycle registration is required")
    recorded_generation = snapshot.get("generation")
    generation = _worktree_generation(
        cwd,
        canonical,
        create=recorded_generation is None,
    )
    with _locked_registry(path) as payload:
        timestamp = time.time() if now is None else now
        record = payload["worktrees"].get(str(canonical))
        if (
            not isinstance(record, dict)
            or record != snapshot
            or record.get("owner") != owner
            or record.get("branch") != branch
            or record.get("status") != "active"
        ):
            raise WorktreeLifecycleError("active matching lifecycle registration is required")
        if recorded_generation is not None and recorded_generation != generation:
            raise WorktreeLifecycleError("active matching lifecycle registration is required")
        if (not _valid_authority_timestamp(record.get("heartbeat_at"))
                or timestamp < record["heartbeat_at"]):
            raise WorktreeLifecycleError("worktree lifecycle clock moved backwards")
        if (not _valid_authority_timestamp(record.get("expires_at"))
                or timestamp >= record["expires_at"]
                or not _valid_authority_timestamp(record.get("authority_since"))
                or not _valid_generation(record.get("registration_epoch"))):
            # A late heartbeat may revive an owner, but cannot prove that it
            # remained continuously authoritative during the expired gap.
            record["authority_since"] = timestamp
            record["registration_epoch"] = uuid.uuid4().hex
        record["generation"] = generation
        record["heartbeat_at"] = timestamp
        record["expires_at"] = timestamp + ttl_seconds
        return dict(record)


def _finish_worktree(
    cwd: Path,
    *,
    worktree: Path,
    owner: str,
    status: str,
    registry_path: Path | None,
    now: float | None,
) -> dict[str, Any]:
    timestamp = time.time() if now is None else now
    path = _canonical(registry_path or _default_registry_path(cwd))
    requested, snapshot = _lifecycle_update_snapshot(
        path,
        worktree=worktree,
        owner=owner,
        statuses={"active", "released", "complete"},
        error="matching lifecycle registration is required",
    )
    canonical, branch = _worktree_identity(cwd, worktree)
    if canonical != requested:
        raise WorktreeLifecycleError("matching lifecycle registration is required")
    recorded_generation = snapshot.get("generation")
    generation = _worktree_generation(
        cwd,
        canonical,
        create=recorded_generation is None,
    )
    with _locked_registry(path) as payload:
        timestamp = time.time() if now is None else now
        record = payload["worktrees"].get(str(canonical))
        if (
            not isinstance(record, dict)
            or record != snapshot
            or record.get("owner") != owner
            or record.get("branch") != branch
            or record.get("status") not in {"active", "released", "complete"}
        ):
            raise WorktreeLifecycleError("matching lifecycle registration is required")
        if recorded_generation is not None and recorded_generation != generation:
            raise WorktreeLifecycleError("matching lifecycle registration is required")
        if (not _valid_authority_timestamp(record.get("heartbeat_at"))
                or timestamp < record["heartbeat_at"]):
            raise WorktreeLifecycleError("worktree lifecycle clock moved backwards")
        if record.get("status") == "active":
            expiry = record.get("expires_at")
            record["authority_until"] = min(expiry, timestamp) if _valid_authority_timestamp(expiry) else None
        record["generation"] = generation
        record["status"] = status
        record[f"{status}_at"] = timestamp
        record["expires_at"] = timestamp
        return dict(record)


def preserve_missing_worktree(
    cwd: Path,
    *,
    worktree: Path,
    branch: str,
    generation: str,
    owner: str,
    disposition: str,
    registry_path: Path | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Record an explicit branch-preserving disposition for one lost checkout."""

    if (
        not owner
        or owner != owner.strip()
        or not branch
        or branch != branch.strip()
        or not _valid_generation(generation)
        or disposition != "retain-branch"
    ):
        raise WorktreeLifecycleError("exact missing-worktree disposition is required")
    if git_hygiene.run_git_result(
        ["check-ref-format", f"refs/heads/{branch}"], cwd
    ).returncode != 0:
        raise WorktreeLifecycleError("missing-worktree branch identity is invalid")

    registry = _canonical(registry_path or _default_registry_path(cwd))
    requested = _canonical(worktree)
    key = str(requested)
    with _registry_lock(registry):
        payload = _read_registry(registry)
        value = payload["worktrees"].get(key)
        snapshot = dict(value) if isinstance(value, dict) else None
        if snapshot is None:
            raise WorktreeLifecycleError("matching lifecycle registration is required")
        validated = _validate_authority_record(key, snapshot)
        if (
            validated.get("owner") != owner
            or validated.get("branch") != branch
            or validated.get("generation") != generation
        ):
            raise WorktreeLifecycleError("missing-worktree lifecycle identity changed")
        if validated.get("status") == "missing_preserved":
            if validated.get("missing_preserved_disposition") != disposition:
                raise WorktreeLifecycleError("missing-worktree disposition changed")
            return dict(
                _validate_missing_preserved_binding(cwd, key, validated)
            )
        if validated.get("status") != "active":
            raise WorktreeLifecycleError("expired active lifecycle registration is required")

    initial_now = time.time() if now is None else now
    if not _valid_authority_timestamp(initial_now):
        raise WorktreeLifecycleError("missing-worktree disposition time is invalid")
    initial_expiry = validated.get("expires_at")
    if not _valid_authority_timestamp(initial_expiry) or initial_expiry > initial_now:
        raise WorktreeLifecycleError("active lifecycle registration has not expired")
    if os.path.lexists(requested):
        raise WorktreeLifecycleError("missing-worktree path was recreated")
    _assert_worktree_path_not_registered(cwd, requested)
    branch_head = git_hygiene.run_git(
        ["rev-parse", "--verify", f"refs/heads/{branch}"], cwd
    )
    if not re.fullmatch(r"[0-9a-f]{40,64}", branch_head):
        raise WorktreeLifecycleError("missing-worktree branch head is invalid")

    with _registry_lock(registry):
        payload = _read_registry(registry)
        current = payload["worktrees"].get(key)
        if not isinstance(current, dict) or current != snapshot:
            raise WorktreeLifecycleError("missing-worktree lifecycle authority changed")
        validated = _validate_authority_record(key, current)
        final_now = time.time() if now is None else now
        if not _valid_authority_timestamp(final_now):
            raise WorktreeLifecycleError("missing-worktree disposition time is invalid")
        if (
            validated.get("status") != "active"
            or validated.get("owner") != owner
            or validated.get("branch") != branch
            or validated.get("generation") != generation
            or not _valid_authority_timestamp(validated.get("expires_at"))
            or cast(float, validated["expires_at"]) > final_now
        ):
            raise WorktreeLifecycleError("expired active lifecycle registration is required")
        with _reserve_absent_worktree_path(cwd, requested):
            current_branch_head = git_hygiene.run_git(
                ["rev-parse", "--verify", f"refs/heads/{branch}"], cwd
            )
            if current_branch_head != branch_head:
                raise WorktreeLifecycleError("missing-worktree branch head changed")
            updated = dict(current)
            updated["status"] = "missing_preserved"
            updated["missing_preserved_at"] = final_now
            updated["missing_preserved_by"] = owner
            updated["missing_preserved_disposition"] = disposition
            updated["missing_preserved_branch_head"] = branch_head
            payload["worktrees"][key] = updated
            _write_registry(registry, payload)
            readback = _read_registry(registry)["worktrees"].get(key)
            if readback != updated:
                raise WorktreeLifecycleError(
                    "missing-worktree disposition readback changed"
                )
            final_branch_head = git_hygiene.run_git(
                ["rev-parse", "--verify", f"refs/heads/{branch}"], cwd
            )
            if final_branch_head != branch_head:
                raise WorktreeLifecycleError(
                    "missing-worktree branch head changed during disposition"
                )
            return dict(updated)


def release_worktree(
    cwd: Path,
    *,
    worktree: Path,
    owner: str,
    registry_path: Path | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    return _finish_worktree(
        cwd,
        worktree=worktree,
        owner=owner,
        status="released",
        registry_path=registry_path,
        now=now,
    )


def complete_worktree(
    cwd: Path,
    *,
    worktree: Path,
    owner: str,
    registry_path: Path | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    return _finish_worktree(
        cwd,
        worktree=worktree,
        owner=owner,
        status="complete",
        registry_path=registry_path,
        now=now,
    )


def janitor_report(
    cwd: Path,
    *,
    registry_path: Path | None = None,
    pr_states: dict[str, dict[str, Any]] | None = None,
    active_leases: list[dict[str, Any]] | None = None,
    stale_after_days: int = 14,
    now: float | None = None,
) -> dict[str, Any]:
    records = _bind_live_generations(
        cwd,
        load_lifecycle_records(cwd, registry_path=registry_path),
    )
    report = git_hygiene.build_janitor_plan(
        cwd,
        active_leases=active_leases,
        stale_after_days=stale_after_days,
        pr_states=pr_states,
        lifecycle_records=records,
        now=now,
    )
    report["mode"] = "report-only"
    report["lifecycle_registry"] = str(
        _canonical(registry_path or _default_registry_path(cwd))
    )
    return report


def janitor_apply(
    cwd: Path,
    *,
    registry_path: Path | None = None,
    pr_states: dict[str, dict[str, Any]] | None,
    lease_path: Path,
    stale_after_days: int = 14,
    target_worktree: Path | None = None,
    target_generation: str | None = None,
) -> dict[str, Any]:
    if (target_worktree is None) != (target_generation is None):
        raise WorktreeLifecycleError(
            "targeted cleanup requires both worktree path and lifecycle generation"
        )
    if target_generation is not None and not _valid_generation(target_generation):
        raise WorktreeLifecycleError("targeted cleanup generation is invalid")
    path = _canonical(registry_path or _default_registry_path(cwd))
    if not path.exists():
        # Absence is not "nothing was ever registered": the registry is the only
        # durable path->branch association behind a removed checkout, so losing
        # it (operator cleanup, fresh clone, `.git` surgery) would silently
        # reclassify a tombstoned branch as an ordinary cleanup candidate and
        # delete it while its former path is leased. A corrupt registry already
        # fails closed in `_read_registry`; absence must fail closed too rather
        # than authorize destruction from unknown lifecycle state.
        raise WorktreeLifecycleError("worktree lifecycle registry is missing")
    _reconcile_removed_generations(cwd, path)
    records = _bind_live_generations(cwd, _locked_lifecycle_snapshot(path))
    target_path: str | None = None
    target_branch: str | None = None
    if target_worktree is not None:
        target = _canonical(target_worktree)
        record = records.get(str(target))
        if (
            not isinstance(record, dict)
            or record.get("generation") != target_generation
        ):
            raise WorktreeLifecycleError(
                "targeted cleanup lifecycle generation does not match"
            )
        target_path = str(target)
        if record.get("status") == "removed":
            branch = record.get("branch")
            if not isinstance(branch, str) or not branch:
                raise WorktreeLifecycleError(
                    "targeted cleanup removed lifecycle binding is invalid"
                )
            if target.exists():
                raise WorktreeLifecycleError("targeted cleanup worktree was recreated")
            target_branch = branch
        elif record.get("status") not in {"active", "released", "complete"}:
            raise WorktreeLifecycleError(
                "targeted cleanup lifecycle generation does not match"
            )
    return git_hygiene.janitor_apply(
        cwd,
        active_lease_loader=lambda: _load_active_lease_snapshot(lease_path),
        lifecycle_authority_guard=lambda targets: _locked_lifecycle_authority(
            cwd,
            path,
            targets,
        ),
        stale_after_days=stale_after_days,
        pr_states=pr_states,
        lifecycle_records=records,
        target_worktree=target_path,
        target_branch=target_branch,
        branch_lifecycle_authority_guard=(
            (
                lambda target: _locked_removed_generation_branch_authority(
                    cwd,
                    path,
                    worktree=str(target["path"]),
                    branch=str(target["branch"]),
                    generation=cast(str, target_generation),
                )
            )
            if target_branch is not None
            else None
        ),
    )


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _load_active_lease_snapshot(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise WorktreeLifecycleError("active lease snapshot is invalid") from exc
    if not isinstance(payload, list) or any(
        not isinstance(item, dict) for item in payload
    ):
        raise WorktreeLifecycleError("active lease snapshot is invalid")
    return [dict(item) for item in payload]


def _read_github_transfer_comment(comment_id: int, *, cwd: Path) -> dict[str, Any]:
    """Read the authenticated host comment without passing credentials to a worker."""
    if comment_id < 1:
        raise WorktreeLifecycleError("handoff comment identity is invalid")
    try:
        identity = subprocess.run(["gh", "api", "--hostname", "github.com", "user", "--jq", ".login"],
                                  cwd=cwd, capture_output=True, text=True, timeout=30, check=False)
        result = subprocess.run(["gh", "api", "--hostname", "github.com",
                                 f"repos/RasmusTho/agentic-pkm-mvp/issues/comments/{comment_id}"],
                                cwd=cwd, capture_output=True, text=True, timeout=30, check=False)
        value = json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise WorktreeLifecycleError("authenticated handoff comment readback is unavailable") from exc
    if identity.returncode or identity.stdout.strip() != "RasmusTho" or not isinstance(value, dict) or value.get("id") != comment_id:
        raise WorktreeLifecycleError("authenticated handoff comment readback is unavailable")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--registry-file")
    parser.add_argument("--lease-file")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("register", "heartbeat"):
        operation = subparsers.add_parser(command)
        operation.add_argument("--worktree", required=True)
        operation.add_argument("--owner", required=True)
        operation.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
    for command in ("release", "complete"):
        operation = subparsers.add_parser(command)
        operation.add_argument("--worktree", required=True)
        operation.add_argument("--owner", required=True)
    for command in ("prepare-transfer", "pin-transfer"):
        operation = subparsers.add_parser(command)
        operation.add_argument("--worktree", required=True)
        operation.add_argument("--owner", required=True)
        operation.add_argument("--workspace-root", required=True)
        operation.add_argument("--issue", required=True, type=int)
        operation.add_argument("--pr", type=int)
        operation.add_argument("--pending-comment-id", required=True, type=int)
        if command == "prepare-transfer":
            operation.add_argument("--base-sha", required=True)
        else:
            operation.add_argument("--ack-comment-id", required=True, type=int)
    operation = subparsers.add_parser("preserve-missing")
    operation.add_argument("--worktree", required=True)
    operation.add_argument("--branch", required=True)
    operation.add_argument("--generation", required=True)
    operation.add_argument("--owner", required=True)
    operation.add_argument(
        "--disposition",
        choices=("retain-branch",),
        required=True,
    )
    for command in ("report", "janitor"):
        operation = subparsers.add_parser(command)
        operation.add_argument("--mode", choices=("report", "apply"), default="report")
        operation.add_argument("--stale-after-days", type=int, default=14)
        operation.add_argument("--pr-state-file")
        operation.add_argument("--target-worktree")
        operation.add_argument("--target-generation")

    args = parser.parse_args(argv)
    cwd = _canonical(Path(args.cwd))
    registry_path = (
        _canonical(Path(args.registry_file)) if args.registry_file else None
    )
    try:
        lease_path = (
            _canonical(Path(args.lease_file)) if args.lease_file else None
        )
        if args.command == "register":
            result = register_worktree(
                cwd,
                worktree=Path(args.worktree),
                owner=args.owner,
                ttl_seconds=args.ttl_seconds,
                registry_path=registry_path,
            )
        elif args.command == "heartbeat":
            result = heartbeat_worktree(
                cwd,
                worktree=Path(args.worktree),
                owner=args.owner,
                ttl_seconds=args.ttl_seconds,
                registry_path=registry_path,
            )
        elif args.command == "release":
            result = release_worktree(
                cwd,
                worktree=Path(args.worktree),
                owner=args.owner,
                registry_path=registry_path,
            )
        elif args.command == "complete":
            result = complete_worktree(
                cwd,
                worktree=Path(args.worktree),
                owner=args.owner,
                registry_path=registry_path,
            )
        elif args.command in {"prepare-transfer", "pin-transfer"}:
            if args.issue < 1 or (args.pr is not None and args.pr < 1):
                raise WorktreeLifecycleError("handoff issue or PR identity is invalid")
            pending_comment = _read_github_transfer_comment(args.pending_comment_id, cwd=cwd)
            if args.command == "prepare-transfer":
                result = prepare_transfer_registration(cwd, worktree=Path(args.worktree), owner=args.owner,
                         issue=args.issue, pr=args.pr, pending_comment=pending_comment,
                         base_sha=args.base_sha, workspace_root=Path(args.workspace_root), registry_path=registry_path)
            else:
                ack_comment = _read_github_transfer_comment(args.ack_comment_id, cwd=cwd)
                result = pin_transfer_registration(cwd, worktree=Path(args.worktree), owner=args.owner,
                         issue=args.issue, pr=args.pr, pending_comment=pending_comment,
                         ack_comment=ack_comment, workspace_root=Path(args.workspace_root), registry_path=registry_path)
        elif args.command == "preserve-missing":
            result = preserve_missing_worktree(
                cwd,
                worktree=Path(args.worktree),
                branch=args.branch,
                generation=args.generation,
                owner=args.owner,
                disposition=args.disposition,
                registry_path=registry_path,
            )
        else:
            if (args.mode == "apply" and not (args.target_worktree and args.target_generation)) or (
                bool(args.target_worktree) != bool(args.target_generation)
            ):
                raise WorktreeLifecycleError(
                    "targeted cleanup requires both worktree path and lifecycle generation"
                )
            if args.mode == "report" and args.target_worktree:
                raise WorktreeLifecycleError("target selectors are only valid for apply mode")
            pr_states = None
            if args.pr_state_file:
                pr_states = json.loads(
                    Path(args.pr_state_file).read_text(encoding="utf-8")
                )
            if args.mode == "apply":
                if pr_states is None:
                    raise WorktreeLifecycleError(
                        "janitor apply requires --pr-state-file"
                    )
                if lease_path is None:
                    raise WorktreeLifecycleError(
                        "janitor apply requires --lease-file"
                    )
                result = janitor_apply(
                    cwd,
                    registry_path=registry_path,
                    pr_states=pr_states,
                    lease_path=lease_path,
                    stale_after_days=args.stale_after_days,
                    target_worktree=(
                        Path(args.target_worktree)
                        if args.target_worktree is not None
                        else None
                    ),
                    target_generation=args.target_generation,
                )
            else:
                active_leases = (
                    _load_active_lease_snapshot(lease_path)
                    if lease_path is not None
                    else None
                )
                result = janitor_report(
                    cwd,
                    registry_path=registry_path,
                    pr_states=pr_states,
                    active_leases=active_leases,
                    stale_after_days=args.stale_after_days,
                )
    except WorktreeLifecycleError as exc:
        _print_json({"ok": False, "error": str(exc)})
        return 1
    _print_json(result)
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
