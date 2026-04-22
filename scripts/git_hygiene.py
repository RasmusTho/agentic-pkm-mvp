#!/usr/bin/env python3
"""
Report-only git hygiene checks for multi-agent repo workflows.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any


DEFAULT_PROTECTED_BRANCHES = {"main", "master", "develop", "dev"}
IN_PROGRESS_MARKERS = {
    "MERGE_HEAD": "merge",
    "CHERRY_PICK_HEAD": "cherry-pick",
    "REVERT_HEAD": "revert",
}


def run_git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def load_active_leases(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    return json.loads(Path(path).read_text(encoding="utf-8"))


def lease_is_active(lease: dict[str, Any], now: float | None = None) -> bool:
    expires_at = lease.get("expires_at")
    if expires_at is None:
        return True
    return float(expires_at) > (time.time() if now is None else now)


def lease_conflicts(
    leases: list[dict[str, Any]],
    resource_ids: set[str],
    execution_id: str | None,
    now: float | None = None,
) -> list[dict[str, Any]]:
    conflicts = []
    for lease in leases:
        resource_id = str(lease.get("resource_id", ""))
        if resource_id not in resource_ids:
            continue
        if execution_id and lease.get("execution_id") == execution_id:
            continue
        if not lease_is_active(lease, now=now):
            continue
        conflicts.append(lease)
    return conflicts


def _git_dir(cwd: Path) -> Path:
    raw = run_git(["rev-parse", "--git-dir"], cwd)
    git_dir = Path(raw)
    if not git_dir.is_absolute():
        git_dir = cwd / git_dir
    return git_dir


def _in_progress_operations(cwd: Path) -> list[str]:
    git_dir = _git_dir(cwd)
    operations = [
        name for marker, name in IN_PROGRESS_MARKERS.items() if (git_dir / marker).exists()
    ]
    if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
        operations.append("rebase")
    return sorted(operations)


def preflight_report(
    cwd: Path,
    *,
    expected_branch: str | None = None,
    expected_worktree: str | None = None,
    active_leases: list[dict[str, Any]] | None = None,
    resource_ids: set[str] | None = None,
    execution_id: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    active_leases = active_leases or []
    resource_ids = resource_ids or set()
    status = run_git(["status", "--porcelain"], cwd)
    branch = run_git(["branch", "--show-current"], cwd)
    worktree = run_git(["rev-parse", "--show-toplevel"], cwd)
    operations = _in_progress_operations(cwd)
    conflicts = lease_conflicts(active_leases, resource_ids, execution_id, now=now)

    checks = {
        "dirty_tree": bool(status),
        "in_progress_operations": operations,
        "branch": branch,
        "branch_mismatch": bool(expected_branch and branch != expected_branch),
        "worktree": worktree,
        "worktree_mismatch": bool(
            expected_worktree and Path(worktree).resolve() != Path(expected_worktree).resolve()
        ),
        "lease_conflicts": conflicts,
    }
    ok = not (
        checks["dirty_tree"]
        or checks["in_progress_operations"]
        or checks["branch_mismatch"]
        or checks["worktree_mismatch"]
        or checks["lease_conflicts"]
    )
    return {"ok": ok, "checks": checks}


def _parse_worktrees(output: str) -> list[dict[str, str]]:
    worktrees: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in output.splitlines():
        if not line.strip():
            if current:
                worktrees.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        worktrees.append(current)
    return worktrees


def _lease_resources(active_leases: list[dict[str, Any]], now: float | None = None) -> set[str]:
    return {
        str(lease.get("resource_id"))
        for lease in active_leases
        if lease.get("resource_id") and lease_is_active(lease, now=now)
    }


def janitor_report(
    cwd: Path,
    *,
    active_leases: list[dict[str, Any]] | None = None,
    stale_after_days: int = 14,
    now: float | None = None,
) -> dict[str, Any]:
    active_leases = active_leases or []
    active_resources = _lease_resources(active_leases, now=now)
    current_branch = run_git(["branch", "--show-current"], cwd)
    merged_output = run_git(["branch", "--merged"], cwd)
    stale_merged_branches = []
    for line in merged_output.splitlines():
        branch = line.replace("*", "", 1).strip()
        if not branch or branch == current_branch or branch in DEFAULT_PROTECTED_BRANCHES:
            continue
        if f"branch:{branch}" in active_resources:
            continue
        stale_merged_branches.append(branch)

    worktrees = _parse_worktrees(run_git(["worktree", "list", "--porcelain"], cwd))
    orphaned_worktrees = []
    for worktree in worktrees:
        path = worktree.get("worktree")
        branch = worktree.get("branch", "").removeprefix("refs/heads/")
        if not path or Path(path).exists():
            continue
        if f"worktree:{path}" in active_resources or f"branch:{branch}" in active_resources:
            continue
        orphaned_worktrees.append({"path": path, "branch": branch})

    cutoff = (time.time() if now is None else now) - stale_after_days * 24 * 60 * 60
    old_stashes = []
    stash_output = run_git(["stash", "list", "--date=unix"], cwd)
    for line in stash_output.splitlines():
        match = re.search(r"(\d{10})", line)
        if match and int(match.group(1)) < cutoff:
            old_stashes.append(line)

    prune_candidates = {
        "worktree": run_git(["worktree", "prune", "--dry-run"], cwd).splitlines(),
        "remote": run_git(["remote", "prune", "origin", "--dry-run"], cwd).splitlines(),
    }
    return {
        "mode": "report-only",
        "destructive_actions": [],
        "stale_merged_branches": stale_merged_branches,
        "orphaned_worktrees": orphaned_worktrees,
        "old_stashes": old_stashes,
        "prune_candidates": prune_candidates,
        "active_leases_respected": sorted(active_resources),
    }


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--lease-file", help="Read-only JSON list of active lease claims")
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--expected-branch")
    preflight.add_argument("--expected-worktree")
    preflight.add_argument("--resource-id", action="append", default=[])
    preflight.add_argument("--execution-id")

    janitor = subparsers.add_parser("janitor")
    janitor.add_argument("--stale-after-days", type=int, default=14)

    args = parser.parse_args(argv)
    cwd = Path(args.cwd).resolve()
    leases = load_active_leases(args.lease_file)
    if args.command == "preflight":
        report = preflight_report(
            cwd,
            expected_branch=args.expected_branch,
            expected_worktree=args.expected_worktree,
            active_leases=leases,
            resource_ids=set(args.resource_id),
            execution_id=args.execution_id,
        )
        _print_json(report)
        return 0 if report["ok"] else 1

    report = janitor_report(
        cwd,
        active_leases=leases,
        stale_after_days=args.stale_after_days,
    )
    _print_json(report)
    return 0


def main_with_default_command(command: str, argv: list[str] | None = None) -> int:
    """Run a compatibility entrypoint while preserving global CLI options."""

    raw_args = list(argv or [])
    if command in raw_args:
        return main(raw_args)

    global_args: list[str] = []
    remaining: list[str] = []
    index = 0
    while index < len(raw_args):
        arg = raw_args[index]
        if arg in {"--cwd", "--lease-file"} and index + 1 < len(raw_args):
            global_args.extend([arg, raw_args[index + 1]])
            index += 2
            continue
        remaining.append(arg)
        index += 1
    return main([*global_args, command, *remaining])


if __name__ == "__main__":
    raise SystemExit(main())
