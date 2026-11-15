#!/usr/bin/env python3
"""Read-only operator-successor proof for existing closure routes.

This does not authorize or perform publication, merge, issue closure, review, or CI.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.builderops import legacy_owner_recovery as recovery  # noqa: E402
from app.builderops import openhands_pr_cycle as cycle  # noqa: E402
from app.dispatcher.sync_github import github_issue_task_id  # noqa: E402
from scripts import agent_worktree  # noqa: E402
from scripts.pr_body_generator import resolve_native_issue_authority  # noqa: E402


def _readonly_dispatcher(*, cwd: Path, task_id: str) -> tuple[dict, list, dict]:
    try:
        return recovery._readonly_dispatcher(cwd=cwd, task_id=task_id)
    except recovery.RecoveryEvidenceError as exc:
        raise cycle.CycleError(str(exc)) from exc


def _readonly_lifecycle(*, cwd: Path, worktree: Path, workspace_root: Path,
                        branch: str, session: str) -> tuple[dict, dict]:
    """Use the existing registry lock and an identity-bound no-follow reader."""
    try:
        common = recovery.legacy_git_config._common(recovery.legacy_git_config._gitdir(cwd))
        registry = common / "agent-worktrees.json"
        with agent_worktree._locked_existing_registry(registry, shared=True) as read_registry:
            payload = read_registry(registry)
            records = agent_worktree._lifecycle_records(payload)
            live = agent_worktree.git_hygiene._parse_worktrees(
                agent_worktree.git_hygiene.run_git(["worktree", "list", "--porcelain"], cwd))
            paths = [*records, *(row.get("worktree") for row in live)]
            for value in paths:
                if not isinstance(value, str):
                    raise cycle.CycleError("lifecycle checkout path is unavailable")
                agent_worktree._screen_transfer_workspace(cwd, Path(value), workspace_root)
            candidate_paths = {str(Path(row["worktree"]).resolve()) for row in live
                               if row.get("branch", "").removeprefix("refs/heads/") == branch}
            selected = agent_worktree._select_authority_records(
                payload.get("worktrees"), candidate_branch=branch, candidate_paths=candidate_paths)
            if candidate_paths != {str(worktree)}:
                raise cycle.CycleError("candidate worktree registration is ambiguous")
            if any(key != str(worktree) for key in selected):
                raise cycle.CycleError("lifecycle authority contains an unqualified checkout")
            authority = agent_worktree._lifecycle_authority_under_registry_lock(
                cwd, registry, candidate_branch=branch, allow_released_history=True,
                permitted_probe_paths={str(worktree)}, registry_reader=read_registry)
            active = [dict(row) for row in authority.values()
                      if row.get("branch") == branch and row.get("status") == "active"]
            if (len(active) != 1 or active[0].get("path") != str(worktree)
                    or active[0].get("owner") != session
                    or not isinstance(active[0].get("expires_at"), (int, float))
                    or active[0]["expires_at"] <= time.time()
                    or not agent_worktree._valid_generation(active[0].get("registration_epoch"))):
                raise cycle.CycleError("current lifecycle successor is unavailable")
            return active[0], records
    except (OSError, ValueError, recovery.legacy_git_config.ConfigError, agent_worktree.WorktreeLifecycleError) as exc:
        raise cycle.CycleError("existing lifecycle registry or lock is unavailable") from exc


def verify(*, issue: int, pr: int, worktree: Path, workspace_root: Path,
           agent: str, session: str, cwd: Path) -> dict:
    """Re-read the pinned successor using the existing native lineage gate."""
    if not session or session != os.environ.get("CODEX_SESSION_ID") or not agent:
        raise cycle.CycleError("current successor session is unavailable")
    try:
        agent_worktree._screen_transfer_workspace(cwd, worktree, workspace_root)
    except agent_worktree.WorktreeLifecycleError as exc:
        raise cycle.CycleError("operator workspace boundary is invalid") from exc
    try:
        recovery.legacy_git_config.check_host_config()
        recovery.legacy_git_config.check(cwd=cwd, worktree=worktree)
    except recovery.legacy_git_config.ConfigError as exc:
        raise cycle.CycleError("operator Git configuration is invalid") from exc
    recovery._verify_current_issue(cwd=cwd, issue=issue, worktree=worktree)
    executor = cycle.SubprocessExecutor(timeout_seconds=30)
    user = executor.run(["gh", "api", "--hostname", "github.com", "user", "--jq", ".login"], cwd=cwd)
    if user.returncode or user.stdout.strip() != "RasmusTho":
        raise cycle.CycleError("host GitHub identity is unavailable")
    repo = cycle.completion.REPOSITORY
    repository = cycle.closure._api(executor, cwd, repo, "GET", "")
    live = cycle.closure._pr(executor, cwd, repo, pr)
    authority = resolve_native_issue_authority(live.get("body"))
    head = live.get("head", {})
    base = live.get("base", {})
    if (not isinstance(repository, dict) or repository.get("full_name") != repo
            or repository.get("default_branch") != "main" or live.get("state") != "open"
            or live.get("draft") is not False or authority is None or authority.governing_issue != issue
            or not isinstance(head, dict) or head.get("repo", {}).get("full_name") != repo
            or not isinstance(head.get("sha"), str) or not isinstance(head.get("ref"), str)
            or not isinstance(base, dict) or base.get("ref") != "main" or not isinstance(base.get("sha"), str)):
        raise cycle.CycleError("live PR authority is unavailable")
    refs = cycle.closure._closing_issue_references(executor, cwd, repo, pr)
    if refs != list(authority.closing_issues):
        raise cycle.CycleError("GitHub closing references differ from the canonical contract")
    task_id = github_issue_task_id(repo, issue)
    task, events, lease = _readonly_dispatcher(cwd=cwd, task_id=task_id)
    owner = cycle.closure._dispatcher_lease_snapshot(task, task_id, repository=repo,
              issue_number=issue, lease=lease)
    linked_pr = task.get("linked_pr")
    if linked_pr is not None and str(linked_pr) != str(pr):
        raise cycle.CycleError("dispatcher task is linked to a different PR")
    cycle.closure._validate_claimant_history(events, owner)
    if owner.get("lease_holder") != agent:
        raise cycle.CycleError("current dispatcher owner differs from successor")
    entry = {"lifecycle_repo": str(cwd), "owner_worktree": str(worktree), "session": session,
             "claimant": agent, "lease_id": owner.get("lease_id"), "base_sha": base["sha"]}
    registration, records = _readonly_lifecycle(cwd=cwd, worktree=worktree, workspace_root=workspace_root, branch=head["ref"], session=session)
    issue_comments = cycle._api_pages(executor, cwd, f"/issues/{issue}/comments")
    pr_comments = cycle._api_pages(executor, cwd, f"/issues/{pr}/comments")
    origin, _ = cycle._pickup_origin(live.get("body", ""), issue=issue, closing=refs,
                                      branch=head["ref"], comments=issue_comments)
    files = cycle._api_pages(executor, cwd, f"/pulls/{pr}/files")
    if not files or any(not isinstance(x, dict) or not isinstance(x.get("filename"), str) for x in files):
        raise cycle.CycleError("candidate changed-file readback is unavailable")
    cycle._operator_lineage(events=events, owner=owner, origin=origin, registration=registration, records=records,
        comments=[*issue_comments, *pr_comments], issue_comments=issue_comments, issue=issue, pr_number=pr,
        branch=head["ref"], head=head["sha"], files=sorted(x["filename"] for x in files), entry=entry)
    if cycle.closure._pr(executor, cwd, repo, pr) != live:
        raise cycle.CycleError("PR changed during operator proof")
    recovery._verify_current_issue(cwd=cwd, issue=issue, worktree=worktree)
    return {"issue": issue, "pr": pr, "head": head["sha"], "agent": agent, "session": session,
            "lease_id": owner["lease_id"], "registration_epoch": registration["registration_epoch"],
            "task_pr_projection": task.get("linked_pr")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--session", required=True)
    args = parser.parse_args()
    try:
        result = verify(**vars(args), cwd=Path.cwd())
    except (cycle.CycleError, cycle.closure.ClosureError, recovery.RecoveryEvidenceError,
            agent_worktree.WorktreeLifecycleError, OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
