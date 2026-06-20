#!/usr/bin/env python3
"""
Git hygiene checks and cleanup for multi-agent repo workflows.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any


DEFAULT_PROTECTED_BRANCHES = {"main", "master", "develop", "dev", "stable"}
DEFAULT_REMOTE_POLICY = "merged-and-closed-with-rescue"
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


def run_git_result(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def run_git_check(args: list[str], cwd: Path) -> str:
    result = run_git_result(args, cwd)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            ["git", *args],
            output=result.stdout,
            stderr=result.stderr,
        )
    return result.stdout.strip()


def run_command(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=False, capture_output=True, text=True)


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


def _base_branch_status(cwd: Path, base_branch: str | None) -> dict[str, Any]:
    if not base_branch:
        return {"base_branch": None, "remote_ref": None, "status": "not_checked", "mismatch": False}

    remote_ref = f"origin/{base_branch}"
    try:
        local_sha = run_git(["rev-parse", base_branch], cwd)
        remote_sha = run_git(["rev-parse", remote_ref], cwd)
    except subprocess.CalledProcessError as exc:
        return {
            "base_branch": base_branch,
            "remote_ref": remote_ref,
            "status": "unavailable",
            "mismatch": True,
            "error": str(exc),
        }

    head_contains_remote: bool | None = None
    if local_sha == remote_sha:
        status = "current"
    else:
        local_ancestor = _is_ancestor(cwd, base_branch, remote_ref)
        remote_ancestor = _is_ancestor(cwd, remote_ref, base_branch)
        if local_ancestor and not remote_ancestor:
            status = "behind"
            # A stale local base ref cannot be fast-forwarded from a dedicated
            # worktree while the base branch is checked out elsewhere. What the
            # publication boundary actually requires is that HEAD already
            # contains the remote head, so a stale local ref alone is advisory.
            head_contains_remote = _is_ancestor(cwd, remote_ref, "HEAD")
        elif remote_ancestor and not local_ancestor:
            status = "ahead"
        else:
            status = "diverged"

    if status == "current":
        mismatch = False
    elif status == "behind":
        mismatch = not head_contains_remote
    else:
        mismatch = True

    result: dict[str, Any] = {
        "base_branch": base_branch,
        "remote_ref": remote_ref,
        "local_sha": local_sha,
        "remote_sha": remote_sha,
        "status": status,
    }
    # Surface a distinct reason label for 'behind' so operators can differentiate a
    # blocking case (HEAD missing origin/main → rebase required) from an advisory one
    # (HEAD already contains origin/main → stale local ref, but gate passes).
    # No reason key is added for other statuses (current, ahead, diverged, unavailable).
    if status == "behind":
        result["reason"] = (
            "rebase_required" if mismatch else "advisory_stale_local_ref"
        )
    result["head_contains_remote"] = head_contains_remote
    result["mismatch"] = mismatch
    return result


def _is_ancestor(cwd: Path, ancestor: str, descendant: str) -> bool:
    result = run_git_result(["merge-base", "--is-ancestor", ancestor, descendant], cwd)
    return result.returncode == 0


def in_shared_root(cwd: str | None = None) -> bool:
    """Return True when *cwd* is the PRIMARY (shared root) worktree.

    Detection: ``git rev-parse --git-dir`` and ``git rev-parse --git-common-dir``
    return the SAME path in the primary worktree and DIFFER in a linked worktree
    created by ``git worktree add``.  Both paths are normalised with
    ``Path.resolve()`` before comparison so relative outputs (e.g. ``.git``) and
    absolute outputs are treated identically.

    Returns False on any subprocess error rather than raising, so a missing or
    broken git repo is treated as "not the shared root" and never blocks the
    caller.
    """
    run_cwd = Path(cwd) if cwd is not None else Path.cwd()
    try:
        git_dir_result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=run_cwd,
            check=False,
            capture_output=True,
            text=True,
        )
        common_dir_result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=run_cwd,
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:  # noqa: BLE001
        return False
    if git_dir_result.returncode != 0 or common_dir_result.returncode != 0:
        return False
    raw_git = git_dir_result.stdout.strip()
    raw_common = common_dir_result.stdout.strip()
    if not raw_git or not raw_common:
        return False

    def _resolve(raw: str) -> Path:
        p = Path(raw)
        if not p.is_absolute():
            p = run_cwd / p
        return p.resolve()

    return _resolve(raw_git) == _resolve(raw_common)


def preflight_report(
    cwd: Path,
    *,
    expected_branch: str | None = None,
    expected_worktree: str | None = None,
    base_branch: str | None = None,
    active_leases: list[dict[str, Any]] | None = None,
    resource_ids: set[str] | None = None,
    execution_id: str | None = None,
    allow_dirty: bool = False,
    now: float | None = None,
    require_dedicated_worktree: bool = False,
) -> dict[str, Any]:
    active_leases = active_leases or []
    resource_ids = resource_ids or set()
    status = run_git(["status", "--porcelain"], cwd)
    branch = run_git(["branch", "--show-current"], cwd)
    worktree = run_git(["rev-parse", "--show-toplevel"], cwd)
    operations = _in_progress_operations(cwd)
    conflicts = lease_conflicts(active_leases, resource_ids, execution_id, now=now)
    base_status = _base_branch_status(cwd, base_branch)

    shared_root = in_shared_root(str(cwd)) if require_dedicated_worktree else False

    checks = {
        "dirty_tree": bool(status),
        "dirty_tree_enforced": not allow_dirty,
        "in_progress_operations": operations,
        "branch": branch,
        "branch_mismatch": bool(expected_branch and branch != expected_branch),
        "worktree": worktree,
        "worktree_mismatch": bool(
            expected_worktree and Path(worktree).resolve() != Path(expected_worktree).resolve()
        ),
        "base_branch": base_status,
        "lease_conflicts": conflicts,
        "shared_root_worktree": shared_root,
    }
    ok = not (
        (checks["dirty_tree"] and not allow_dirty)
        or checks["in_progress_operations"]
        or checks["branch_mismatch"]
        or checks["worktree_mismatch"]
        or checks["base_branch"]["mismatch"]
        or checks["lease_conflicts"]
        or (require_dedicated_worktree and shared_root)
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


def _local_branches(cwd: Path) -> list[str]:
    output = run_git(["for-each-ref", "--format=%(refname:short)", "refs/heads"], cwd)
    return [line.strip() for line in output.splitlines() if line.strip()]


def _remote_branches(cwd: Path) -> list[str]:
    output = run_git(["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"], cwd)
    branches = []
    for line in output.splitlines():
        branch = line.strip()
        if not branch or branch in {"origin/HEAD", "origin"}:
            continue
        branch = branch.removeprefix("origin/")
        if branch == "HEAD":
            continue
        branches.append(branch)
    return branches


def load_pr_states_from_gh(cwd: Path) -> dict[str, dict[str, Any]]:
    result = run_command(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "all",
            "--limit",
            "500",
            "--json",
            "headRefName,state,isDraft,number,mergedAt,closedAt,updatedAt",
        ],
        cwd,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh pr list failed")
    states: dict[str, dict[str, Any]] = {}
    for pr in json.loads(result.stdout or "[]"):
        branch = pr.get("headRefName")
        if branch:
            states[str(branch)] = pr
    return states


def _checked_out_branches(worktrees: list[dict[str, str]]) -> dict[str, str]:
    checked_out: dict[str, str] = {}
    for worktree in worktrees:
        branch = worktree.get("branch", "").removeprefix("refs/heads/")
        path = worktree.get("worktree")
        if branch and path:
            checked_out[branch] = path
    return checked_out


def _worktree_dirty(path: str) -> bool | None:
    try:
        result = run_git_result(["status", "--porcelain"], Path(path))
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def _stash_epoch(line: str) -> int | None:
    match = re.search(r"(\d{10})", line)
    return int(match.group(1)) if match else None


def _stash_ref(line: str) -> str:
    return line.split(":", 1)[0]


def _utc_stamp(now: float | None = None) -> str:
    value = dt.datetime.fromtimestamp(time.time() if now is None else now, tz=dt.UTC)
    return value.strftime("%Y%m%dT%H%M%SZ")


def _archive_ref(branch: str, now: float | None = None) -> str:
    safe_branch = branch.replace("/", "-")
    return f"refs/archive/git-hygiene/{_utc_stamp(now)}/{safe_branch}"


def _pr_state(branch: str, pr_states: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    if pr_states is None:
        return {"state": "none"}
    return pr_states.get(branch, {"state": "unknown"})


def _branch_has_active_lease(branch: str, active_resources: set[str]) -> bool:
    return f"branch:{branch}" in active_resources


def _worktree_reclaim_reason(
    path: str,
    branch: str,
    *,
    current_worktree: str,
    active_resources: set[str],
    protected_branches: set[str],
    pr_states: dict[str, dict[str, Any]] | None,
    cwd: Path,
) -> tuple[str | None, str | None]:
    """Decide whether a present worktree is safe to reclaim.

    Returns ``(skip_reason, merge_proof)`` where exactly one element is set:

    - reclaimable -> ``(None, merge_proof)`` with ``merge_proof`` one of
      ``ancestor_of_origin_main``, ``merged_pr``, ``closed_pr``.
    - not reclaimable -> ``(reason, None)``.

    Candidacy gates on **merge state, not branch prefix**: any clean, non-root,
    non-lease, non-open-PR worktree whose branch is an ancestor of ``origin/main``
    OR has a merged/closed PR is reclaimable. Squash-merged branches are not
    ancestors, so PR state is required to catch them.

    Protected branches (``stable``/``develop``/etc.) are never reclaimed even
    when checked out in a non-root worktree: reclaiming would ``git branch -d``
    the protected ref and bypass the same protections the local/remote branch
    cleanup already honours.
    """
    if Path(path).resolve() == Path(current_worktree).resolve():
        return "root_worktree", None
    if branch in protected_branches:
        return "protected_branch", None
    if f"worktree:{path}" in active_resources or _branch_has_active_lease(
        branch, active_resources
    ):
        return "active_lease", None
    dirty = _worktree_dirty(path)
    if dirty is None:
        return "worktree_state_unavailable", None
    if dirty:
        return "dirty_worktree", None
    pr = _pr_state(branch, pr_states)
    if pr.get("state") == "OPEN" or pr.get("isDraft"):
        return "open_or_draft_pr", None
    if _is_ancestor(cwd, branch, "origin/main"):
        return None, "ancestor_of_origin_main"
    if pr.get("state") == "MERGED":
        return None, "merged_pr"
    if pr.get("state") == "CLOSED":
        return None, "closed_pr"
    # Clean but not provably merged/closed: hold back for manual review rather
    # than reclaim. Covers unknown PR state (pr_states given but branch absent)
    # and the report-mode case where PR state was not resolved.
    return "unknown_merge_state", None


def _local_branch_skip_reason(
    branch: str,
    *,
    current_branch: str,
    active_resources: set[str],
    checked_out: dict[str, str],
    protected_branches: set[str],
    pr_states: dict[str, dict[str, Any]] | None,
    cwd: Path,
) -> str | None:
    if branch == current_branch:
        return "current_branch"
    if branch in protected_branches:
        return "protected_branch"
    if _branch_has_active_lease(branch, active_resources):
        return "active_lease"
    pr = _pr_state(branch, pr_states)
    if pr["state"] == "unknown":
        return "unknown_github_state"
    if pr.get("state") == "OPEN" or pr.get("isDraft"):
        return "open_or_draft_pr"
    if branch in checked_out:
        dirty = _worktree_dirty(checked_out[branch])
        if dirty is None:
            return "worktree_state_unavailable"
        if dirty:
            return "dirty_worktree"
        return "checked_out_worktree"
    if not _is_ancestor(cwd, branch, "origin/main"):
        return "not_merged_to_origin_main"
    return None


def _remote_branch_skip_reason(
    branch: str,
    *,
    current_branch: str,
    active_resources: set[str],
    checked_out: dict[str, str],
    protected_branches: set[str],
    pr_states: dict[str, dict[str, Any]] | None,
    cwd: Path,
) -> tuple[str | None, bool]:
    if branch == current_branch:
        return "current_branch", False
    if branch in protected_branches:
        return "protected_branch", False
    if _branch_has_active_lease(branch, active_resources):
        return "active_lease", False
    if branch in checked_out:
        dirty = _worktree_dirty(checked_out[branch])
        if dirty is None:
            return "worktree_state_unavailable", False
        if dirty:
            return "dirty_worktree", False
    pr = _pr_state(branch, pr_states)
    if pr["state"] == "unknown":
        return "unknown_github_state", False
    if pr.get("state") == "OPEN" or pr.get("isDraft"):
        return "open_or_draft_pr", False
    merged = _is_ancestor(cwd, f"origin/{branch}", "origin/main")
    if merged:
        return None, False
    if pr.get("state") in {"CLOSED", "MERGED"}:
        return None, True
    if pr.get("state") == "none":
        return "remote_not_merged_without_pr", False
    return "remote_not_safe", False


def _lease_resources(active_leases: list[dict[str, Any]], now: float | None = None) -> set[str]:
    return {
        str(lease.get("resource_id"))
        for lease in active_leases
        if lease.get("resource_id") and lease_is_active(lease, now=now)
    }


def build_janitor_plan(
    cwd: Path,
    *,
    active_leases: list[dict[str, Any]] | None = None,
    stale_after_days: int = 14,
    remote_policy: str = DEFAULT_REMOTE_POLICY,
    pr_states: dict[str, dict[str, Any]] | None = None,
    protected_branches: set[str] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    active_leases = active_leases or []
    protected = protected_branches or DEFAULT_PROTECTED_BRANCHES
    active_resources = _lease_resources(active_leases, now=now)
    current_branch = run_git(["branch", "--show-current"], cwd)
    current_worktree = run_git(["rev-parse", "--show-toplevel"], cwd)
    worktrees = _parse_worktrees(run_git(["worktree", "list", "--porcelain"], cwd))
    checked_out = _checked_out_branches(worktrees)

    skipped: list[dict[str, Any]] = []
    local_branches = []
    for branch in _local_branches(cwd):
        reason = _local_branch_skip_reason(
            branch,
            current_branch=current_branch,
            active_resources=active_resources,
            checked_out=checked_out,
            protected_branches=protected,
            pr_states=pr_states,
            cwd=cwd,
        )
        if reason:
            skipped.append({"artifact": "local_branch", "name": branch, "reason": reason})
            continue
        local_branches.append({"branch": branch})

    reclaimable_worktrees = []
    orphaned_worktrees = []
    for worktree in worktrees:
        path = worktree.get("worktree")
        branch = worktree.get("branch", "").removeprefix("refs/heads/")
        if not path:
            continue
        is_root = Path(path).resolve() == Path(current_worktree).resolve()
        leased = f"worktree:{path}" in active_resources or _branch_has_active_lease(
            branch, active_resources
        )
        # A missing worktree is an orphan (its metadata is pruned, not reclaimed)
        # — but the root is never missing, and an active lease still wins so we
        # never touch leased work even if its checkout has gone.
        if not is_root and not leased and not Path(path).exists():
            orphaned_worktrees.append({"path": path, "branch": branch})
            continue
        # Candidacy gates on merge state, not branch prefix.
        reason, merge_proof = _worktree_reclaim_reason(
            path,
            branch,
            current_worktree=current_worktree,
            active_resources=active_resources,
            protected_branches=protected,
            pr_states=pr_states,
            cwd=cwd,
        )
        if reason:
            skipped.append({"artifact": "worktree", "path": path, "branch": branch, "reason": reason})
            continue
        reclaimable_worktrees.append(
            {"path": path, "branch": branch, "merge_proof": merge_proof}
        )

    remote_branches = []
    rescue_remote_branches = []
    for branch in _remote_branches(cwd):
        reason, needs_rescue = _remote_branch_skip_reason(
            branch,
            current_branch=current_branch,
            active_resources=active_resources,
            checked_out=checked_out,
            protected_branches=protected,
            pr_states=pr_states,
            cwd=cwd,
        )
        if reason:
            skipped.append({"artifact": "remote_branch", "name": branch, "reason": reason})
            continue
        if needs_rescue and remote_policy != DEFAULT_REMOTE_POLICY:
            skipped.append({"artifact": "remote_branch", "name": branch, "reason": "remote_policy_disallows_rescue"})
            continue
        candidate = {"branch": branch}
        if needs_rescue:
            candidate["rescue_ref"] = _archive_ref(branch, now=now)
            rescue_remote_branches.append(candidate)
        else:
            remote_branches.append(candidate)

    cutoff = (time.time() if now is None else now) - stale_after_days * 24 * 60 * 60
    old_stashes = []
    stash_output = run_git(["stash", "list", "--date=unix"], cwd)
    for line in stash_output.splitlines():
        epoch = _stash_epoch(line)
        if epoch and epoch < cutoff and "preserve-local-drift" in line:
            old_stashes.append({"ref": _stash_ref(line), "line": line})
        elif epoch and epoch < cutoff:
            skipped.append({"artifact": "stash", "name": _stash_ref(line), "reason": "missing_preserve_local_drift_marker"})

    prune_candidates = {
        "worktree": run_git(["worktree", "prune", "--dry-run"], cwd).splitlines(),
        "remote": run_git(["remote", "prune", "origin", "--dry-run"], cwd).splitlines(),
    }
    return {
        "mode": "report",
        "remote_policy": remote_policy,
        "destructive_actions": [],
        "candidates": {
            "local_branches": local_branches,
            "worktrees": reclaimable_worktrees,
            "orphaned_worktrees": orphaned_worktrees,
            "remote_branches": remote_branches,
            "remote_branches_requiring_rescue": rescue_remote_branches,
            "old_stashes": old_stashes,
        },
        # Top-level reclaim view: present-but-merged worktrees that are safe to
        # reclaim (with the proof that qualified each), kept distinct from
        # orphaned_worktrees (missing checkouts handled by `worktree prune`).
        "reclaimable_worktrees": reclaimable_worktrees,
        "orphaned_worktrees": orphaned_worktrees,
        "skipped": skipped,
        "prune_candidates": prune_candidates,
        "active_leases_respected": sorted(active_resources),
    }


def janitor_report(
    cwd: Path,
    *,
    active_leases: list[dict[str, Any]] | None = None,
    stale_after_days: int = 14,
    now: float | None = None,
) -> dict[str, Any]:
    active_leases = active_leases or []
    plan = build_janitor_plan(
        cwd,
        active_leases=active_leases,
        stale_after_days=stale_after_days,
        pr_states=None,
        now=now,
    )
    plan["mode"] = "report-only"
    plan["stale_merged_branches"] = [item["branch"] for item in plan["candidates"]["local_branches"]]
    plan["reclaimable_worktrees"] = plan["candidates"]["worktrees"]
    plan["orphaned_worktrees"] = plan["candidates"]["orphaned_worktrees"]
    plan["old_stashes"] = [item["line"] for item in plan["candidates"]["old_stashes"]]
    return plan


def janitor_apply(
    cwd: Path,
    *,
    active_leases: list[dict[str, Any]] | None = None,
    stale_after_days: int = 14,
    remote_policy: str = DEFAULT_REMOTE_POLICY,
    pr_states: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    if pr_states is None:
        return {
            "mode": "apply",
            "ok": False,
            "destructive_actions": [],
            "errors": [
                {
                    "artifact": "github_state",
                    "action": "load_pr_states",
                    "reason": "apply_requires_pr_state_file",
                }
            ],
        }

    def apply_git(args: list[str], action: dict[str, Any]) -> None:
        result = run_git_result(args, cwd)
        record = {**action, "command": ["git", *args], "returncode": result.returncode}
        if result.stdout.strip():
            record["stdout"] = result.stdout.strip()
        if result.stderr.strip():
            record["stderr"] = result.stderr.strip()
        if result.returncode == 0:
            actions.append(record)
        else:
            errors.append(record)

    apply_git(["fetch", "--prune", "origin"], {"artifact": "remote", "action": "fetch_prune"})
    plan = build_janitor_plan(
        cwd,
        active_leases=active_leases,
        stale_after_days=stale_after_days,
        remote_policy=remote_policy,
        pr_states=pr_states,
    )

    apply_git(["worktree", "prune"], {"artifact": "worktree", "action": "prune_metadata"})
    reclaimable = plan.get("reclaimable_worktrees", plan["candidates"]["worktrees"])
    for worktree in reclaimable:
        remove_errors_before = len(errors)
        # Never --force / --ignore-locked: a worktree that turned dirty or locked
        # since planning must fail the remove and keep its branch intact.
        apply_git(["worktree", "remove", worktree["path"]], {"artifact": "worktree", "action": "remove", **worktree})
        if len(errors) == remove_errors_before:
            # Squash/closed-PR-proven branches are not ancestors of origin/main,
            # so `git branch -d` refuses them and the branch would be skipped
            # forever. The merge_proof already establishes safe-to-delete, so use
            # -D for merged_pr/closed_pr; keep the conservative -d for branches
            # proven by ancestry.
            delete_flag = (
                "-D"
                if worktree.get("merge_proof") in {"merged_pr", "closed_pr"}
                else "-d"
            )
            apply_git(["branch", delete_flag, worktree["branch"]], {"artifact": "local_branch", "action": "delete_after_worktree_remove", "branch": worktree["branch"]})
    for branch in plan["candidates"]["local_branches"]:
        apply_git(["branch", "-d", branch["branch"]], {"artifact": "local_branch", "action": "delete", **branch})
    for remote in plan["candidates"]["remote_branches"]:
        apply_git(["push", "origin", "--delete", remote["branch"]], {"artifact": "remote_branch", "action": "delete", **remote})
    for remote in plan["candidates"]["remote_branches_requiring_rescue"]:
        errors_before_rescue = len(errors)
        apply_git(
            ["update-ref", remote["rescue_ref"], f"origin/{remote['branch']}"],
            {"artifact": "remote_branch", "action": "create_rescue_ref", **remote},
        )
        rescue_created = len(errors) == errors_before_rescue
        rescue_pushed = False
        if rescue_created:
            errors_before_push = len(errors)
            apply_git(
                ["push", "origin", f"{remote['rescue_ref']}:{remote['rescue_ref']}"],
                {"artifact": "remote_branch", "action": "push_rescue_ref", **remote},
            )
            rescue_pushed = len(errors) == errors_before_push
        if rescue_created and rescue_pushed:
            apply_git(["push", "origin", "--delete", remote["branch"]], {"artifact": "remote_branch", "action": "delete_after_rescue", **remote})
    for stash in plan["candidates"]["old_stashes"]:
        apply_git(["stash", "drop", stash["ref"]], {"artifact": "stash", "action": "drop", **stash})

    return {
        **plan,
        "mode": "apply",
        "destructive_actions": actions,
        "errors": errors,
        "ok": not errors,
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
    preflight.add_argument("--base-branch")
    preflight.add_argument("--resource-id", action="append", default=[])
    preflight.add_argument("--execution-id")
    preflight.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Do not fail on a dirty working tree (use at the publish boundary, "
        "where uncommitted work is expected; branch/worktree drift still fails)",
    )

    janitor = subparsers.add_parser("janitor")
    janitor.add_argument("--stale-after-days", type=int, default=14)
    janitor.add_argument("--mode", choices=["report", "apply"], default="report")
    janitor.add_argument("--remote-policy", choices=[DEFAULT_REMOTE_POLICY, "merged-only"], default=DEFAULT_REMOTE_POLICY)
    janitor.add_argument("--pr-state-file", help="JSON map of branch name to GitHub PR state")
    janitor.add_argument("--resolve-github-state", action="store_true", help="Load PR state with gh before planning")

    args = parser.parse_args(argv)
    cwd = Path(args.cwd).resolve()
    leases = load_active_leases(args.lease_file)
    if args.command == "preflight":
        report = preflight_report(
            cwd,
            expected_branch=args.expected_branch,
            expected_worktree=args.expected_worktree,
            base_branch=args.base_branch,
            active_leases=leases,
            resource_ids=set(args.resource_id),
            execution_id=args.execution_id,
            allow_dirty=args.allow_dirty,
        )
        _print_json(report)
        return 0 if report["ok"] else 1

    pr_states = None
    if args.pr_state_file:
        pr_states = json.loads(Path(args.pr_state_file).read_text(encoding="utf-8"))
    if args.resolve_github_state:
        pr_states = load_pr_states_from_gh(cwd)
    if args.mode == "apply":
        report = janitor_apply(
            cwd,
            active_leases=leases,
            stale_after_days=args.stale_after_days,
            remote_policy=args.remote_policy,
            pr_states=pr_states,
        )
    else:
        report = janitor_report(
            cwd,
            active_leases=leases,
            stale_after_days=args.stale_after_days,
        )
        if pr_states is not None:
            report = build_janitor_plan(
                cwd,
                active_leases=leases,
                stale_after_days=args.stale_after_days,
                remote_policy=args.remote_policy,
                pr_states=pr_states,
            )
    _print_json(report)
    return 0 if not report.get("errors") else 1


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
