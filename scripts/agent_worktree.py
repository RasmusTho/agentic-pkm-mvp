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
            if value.get("status") not in {"active", "released", "complete"}:
                continue
            if not _valid_generation(generation):
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
        authorized: list[tuple[str, str]] = []
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
            authorized.append((str(canonical), generation))
        command_succeeded = False

        def mark_succeeded() -> None:
            nonlocal command_succeeded
            command_succeeded = True

        yield mark_succeeded
        if command_succeeded:
            removed_at = time.time()
            for canonical_path, generation in authorized:
                record = payload["worktrees"].get(canonical_path)
                if (
                    not isinstance(record, dict)
                    or record.get("generation") != generation
                ):
                    raise WorktreeLifecycleError(
                        "cleanup target generation changed before retirement"
                    )
                _mark_generation_removed(record, removed_at=removed_at)
            _write_registry(path, payload)


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
) -> dict[str, Any]:
    path = _canonical(registry_path or _default_registry_path(cwd))
    _reconcile_removed_generations(cwd, path)
    records = _bind_live_generations(cwd, _locked_lifecycle_snapshot(path))
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
