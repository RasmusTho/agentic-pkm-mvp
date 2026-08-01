#!/usr/bin/env python3
"""Registered lifecycle and fail-closed cleanup guard for agent worktrees."""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

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


class WorktreeLifecycleError(RuntimeError):
    """A worktree lifecycle operation is not safe or authorized."""


def _canonical(path: Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


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


def _valid_generation(value: object) -> bool:
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

    generation = uuid.uuid4().hex
    marker.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=marker.parent,
        prefix=f".{marker.name}.",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=True) as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(f"{generation}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, marker)
        _fsync_directory(marker.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return generation


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
    for key, record in bound.items():
        if record.get("status") == "removed":
            # A tombstone's checkout is gone by construction, so the probe below
            # always fails and is always caught. No consumer reads a tombstone's
            # generation — `_lifecycle_worktree_paths_for_branch` reads only
            # path/branch and `_worktree_lifecycle_skip_reason` rejects on
            # `status` first — and tombstones are never pruned, so probing them
            # costs one subprocess per removed worktree on every report and
            # janitor run, forever.
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


def load_lifecycle_records(
    cwd: Path,
    *,
    registry_path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    path = _canonical(registry_path or _default_registry_path(cwd))
    return _lifecycle_records(_read_registry(path))


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
    with _locked_registry(path) as payload:
        canonical, branch = _worktree_identity(cwd, worktree)
        worktrees = payload["worktrees"]
        existing = worktrees.get(str(canonical))
        existing_expiry = (
            existing.get("expires_at") if isinstance(existing, dict) else None
        )
        existing_active_for_other_owner = (
            isinstance(existing, dict)
            and existing.get("owner") != owner
            and existing.get("status") == "active"
            and (
                not isinstance(existing_expiry, (int, float))
                or isinstance(existing_expiry, bool)
                or not math.isfinite(existing_expiry)
                or existing_expiry > timestamp
            )
        )
        if existing_active_for_other_owner:
            raise WorktreeLifecycleError("worktree has an active lifecycle owner")
        generation = _worktree_generation(cwd, canonical, create=True)
        prior_bindings = _carried_prior_bindings(
            existing, new_branch=branch, timestamp=timestamp
        )
        record = {
            "path": str(canonical),
            "branch": branch,
            "generation": generation,
            "owner": owner,
            "status": "active",
            "registered_at": timestamp,
            "heartbeat_at": timestamp,
            "expires_at": timestamp + ttl_seconds,
        }
        if prior_bindings:
            record["prior_bindings"] = prior_bindings
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
    with _locked_registry(path) as payload:
        canonical, branch = _worktree_identity(cwd, worktree)
        record = payload["worktrees"].get(str(canonical))
        if (
            not isinstance(record, dict)
            or record.get("owner") != owner
            or record.get("branch") != branch
            or record.get("status") != "active"
        ):
            raise WorktreeLifecycleError("active matching lifecycle registration is required")
        recorded_generation = record.get("generation")
        generation = _worktree_generation(
            cwd,
            canonical,
            create=recorded_generation is None,
        )
        if recorded_generation is not None and recorded_generation != generation:
            raise WorktreeLifecycleError("active matching lifecycle registration is required")
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
    with _locked_registry(path) as payload:
        canonical, branch = _worktree_identity(cwd, worktree)
        record = payload["worktrees"].get(str(canonical))
        if (
            not isinstance(record, dict)
            or record.get("owner") != owner
            or record.get("branch") != branch
            or record.get("status") not in {"active", "released", "complete"}
        ):
            raise WorktreeLifecycleError("matching lifecycle registration is required")
        recorded_generation = record.get("generation")
        generation = _worktree_generation(
            cwd,
            canonical,
            create=recorded_generation is None,
        )
        if recorded_generation is not None and recorded_generation != generation:
            raise WorktreeLifecycleError("matching lifecycle registration is required")
        record["generation"] = generation
        record["status"] = status
        record[f"{status}_at"] = timestamp
        record["expires_at"] = timestamp
        return dict(record)


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
                    generation=target_generation,
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
        else:
            if bool(args.target_worktree) != bool(args.target_generation):
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
