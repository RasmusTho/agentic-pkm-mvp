#!/usr/bin/env python3
"""Register, heartbeat, inspect, and safely reclaim agent worktrees.

The registry lives beside the repository's shared Git metadata, not in a
checkout.  This makes it visible to every linked worktree on the same
machine while keeping machine-local state out of Git.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
DEFAULT_TTL_HOURS = 24


def git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def common_dir(cwd: Path) -> Path:
    return Path(git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd))


def registry_path(cwd: Path) -> Path:
    return Path(os.environ.get("PKM_WORKTREE_REGISTRY", common_dir(cwd) / "agent-worktrees.json"))


def load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "worktrees": {}}
    data = json.loads(path.read_text())
    if data.get("schema_version") != SCHEMA_VERSION or not isinstance(data.get("worktrees"), dict):
        raise SystemExit(f"Unsupported registry format: {path}")
    return data


def save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp = Path(handle.name)
    temp.replace(path)


@contextmanager
def registry_lock(cwd: Path):
    path = registry_path(cwd)
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield path, load(path)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def parse_worktrees(cwd: Path) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in git(["worktree", "list", "--porcelain"], cwd).splitlines() + [""]:
        if not line:
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    return records


def worktree_record(cwd: Path, path: Path) -> dict[str, str]:
    resolved = path.resolve()
    for record in parse_worktrees(cwd):
        if Path(record.get("worktree", "")).resolve() == resolved:
            return record
    raise SystemExit(f"Not a registered Git worktree: {resolved}")


def now() -> int:
    return int(time.time())


def epoch(timestamp: str) -> int:
    return int(datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp())


def require_non_root(cwd: Path, path: Path) -> None:
    root = Path(git(["rev-parse", "--show-toplevel"], cwd)).resolve()
    if path.resolve() == root:
        raise SystemExit("Refusing to register the shared/root worktree")


def cmd_register(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd).resolve()
    path = Path(args.path).resolve()
    require_non_root(cwd, path)
    worktree_record(cwd, path)
    timestamp = now()
    expiry = epoch(args.expires_at) if args.expires_at else timestamp + max(1, args.ttl_hours) * 3600
    with registry_lock(cwd) as (registry, data):
        existing = data["worktrees"].get(str(path), {})
        data["worktrees"][str(path)] = {
            "task_id": args.task_id,
            "owner": args.owner,
            "machine": args.machine or socket.gethostname(),
            "created_at": existing.get("created_at", timestamp),
            "last_heartbeat": timestamp,
            "expires_at": expiry,
            "status": "active",
            "coordination_mode": args.coordination_mode,
            "dispatcher_lease_id": args.lease_id,
        }
        save(registry, data)
        print(json.dumps(data["worktrees"][str(path)], indent=2, sort_keys=True))
    return 0


def cmd_heartbeat(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd).resolve()
    path = Path(args.path).resolve()
    with registry_lock(cwd) as (registry, data):
        entry = data["worktrees"].get(str(path))
        if not entry:
            raise SystemExit("Worktree is not registered; run register first")
        timestamp = now()
        entry["last_heartbeat"] = timestamp
        if args.lease_id and entry.get("dispatcher_lease_id") not in {None, args.lease_id}:
            raise SystemExit("Dispatcher lease does not match the registered worktree")
        entry["expires_at"] = (
            epoch(args.expires_at)
            if args.expires_at
            else timestamp + max(1, args.ttl_hours) * 3600
        )
        entry["status"] = "active"
        save(registry, data)
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd).resolve()
    path = Path(args.path).resolve()
    with registry_lock(cwd) as (registry, data):
        data["worktrees"].pop(str(path), None)
        save(registry, data)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd).resolve()
    path = Path(args.path).resolve()
    require_non_root(cwd, path)
    worktree_record(cwd, path)
    entry = load(registry_path(cwd))["worktrees"].get(str(path))
    if not entry:
        raise SystemExit(f"Worktree is not registered: {path}")
    if entry.get("expires_at", 0) < now():
        raise SystemExit(f"Worktree registry lease is expired: {path}")
    return 0


def worktree_state(cwd: Path, path: Path) -> str:
    if not path.exists():
        return "missing"
    result = subprocess.run(["git", "status", "--porcelain"], cwd=path, capture_output=True, text=True)
    return "dirty" if result.returncode != 0 or result.stdout.strip() else "clean"


def dispatcher_state(cwd: Path, entry: dict[str, Any]) -> str:
    """Return active, released, or unavailable without failing open."""
    task_id = entry.get("task_id")
    if entry.get("coordination_mode") != "dispatcher-backed" or not task_id:
        return "not_applicable"
    try:
        result = subprocess.run(
            [sys.executable, "-m", "app.dispatcher", "show", str(task_id), "--json"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return "unavailable"
        payload = json.loads(result.stdout)
        task = payload.get("task", {})
        lease_id = task.get("lease_id")
        expires_at = task.get("lease_expires_at")
        if lease_id and expires_at:
            try:
                if epoch(expires_at) > now():
                    return "active"
            except ValueError:
                return "unavailable"
        return "released"
    except (OSError, json.JSONDecodeError):
        return "unavailable"


def cmd_status(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd).resolve()
    data = load(registry_path(cwd))
    timestamp = now()
    rows = []
    registered = data["worktrees"]
    for record in parse_worktrees(cwd):
        path = Path(record["worktree"]).resolve()
        entry = registered.get(str(path))
        rows.append({
            "path": str(path),
            "branch": record.get("branch", "").removeprefix("refs/heads/"),
            "git_state": worktree_state(cwd, path),
            "locked": "locked" in record,
            "registry": entry or None,
            "expired": bool(entry and entry.get("expires_at", 0) < timestamp),
        })
    print(json.dumps({"registry": str(registry_path(cwd)), "worktrees": rows}, indent=2, sort_keys=True))
    return 0


def build_janitor_result(cwd: Path, data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    timestamp = now()
    candidates = []
    preserved = []
    for record in parse_worktrees(cwd):
        path = Path(record["worktree"]).resolve()
        entry = data["worktrees"].get(str(path))
        if not entry:
            preserved.append({"path": str(path), "reason": "unregistered"})
            continue
        dispatcher = dispatcher_state(cwd, entry)
        if dispatcher == "active":
            preserved.append({"path": str(path), "reason": "dispatcher_lease_active"})
            continue
        if dispatcher == "unavailable":
            preserved.append({"path": str(path), "reason": "dispatcher_unavailable"})
            continue
        if "locked" in record:
            preserved.append({"path": str(path), "reason": "git_locked"})
            continue
        if entry.get("expires_at", 0) >= timestamp:
            preserved.append({"path": str(path), "reason": "active_or_not_expired"})
            continue
        state = worktree_state(cwd, path)
        if state != "clean":
            preserved.append({"path": str(path), "reason": f"{state}_worktree"})
            continue
        candidates.append({"path": str(path), "task_id": entry.get("task_id", "")})
    return {"candidates": candidates, "preserved": preserved}, candidates


def cmd_janitor(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd).resolve()
    with registry_lock(cwd) as (registry, data):
        result, candidates = build_janitor_result(cwd, data)
        result["mode"] = "apply" if args.apply else "report"
        if args.apply:
            for candidate in candidates:
                git(["worktree", "remove", candidate["path"]], cwd)
                data["worktrees"].pop(candidate["path"], None)
            save(registry, data)

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--cwd", default=".")
    sub = root.add_subparsers(dest="command", required=True)
    register = sub.add_parser("register")
    register.add_argument("--path", required=True)
    register.add_argument("--task-id", required=True)
    register.add_argument("--owner", required=True)
    register.add_argument("--machine")
    register.add_argument("--ttl-hours", type=int, default=DEFAULT_TTL_HOURS)
    register.add_argument("--expires-at")
    register.add_argument("--lease-id")
    register.add_argument("--coordination-mode", default="local")
    register.set_defaults(func=cmd_register)
    heartbeat = sub.add_parser("heartbeat")
    heartbeat.add_argument("--path", required=True)
    heartbeat.add_argument("--ttl-hours", type=int, default=DEFAULT_TTL_HOURS)
    heartbeat.add_argument("--expires-at")
    heartbeat.add_argument("--lease-id")
    heartbeat.set_defaults(func=cmd_heartbeat)
    release = sub.add_parser("release")
    release.add_argument("--path", required=True)
    release.set_defaults(func=cmd_release)
    verify = sub.add_parser("verify")
    verify.add_argument("--path", required=True)
    verify.set_defaults(func=cmd_verify)
    status = sub.add_parser("status")
    status.set_defaults(func=cmd_status)
    janitor = sub.add_parser("janitor")
    janitor.add_argument("--apply", action="store_true")
    janitor.set_defaults(func=cmd_janitor)
    return root


if __name__ == "__main__":
    args = parser().parse_args()
    raise SystemExit(args.func(args))
