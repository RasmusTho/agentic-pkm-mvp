#!/usr/bin/env python3
"""Produce an incomplete, read-only operator reconciliation draft.

Run with ``python -m scripts.legacy_operator_evidence``. The null fields are
intentional: the operator must independently establish and record their sources.
This output is neither a transfer nor a validated or authenticated receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

from app.builderops import legacy_git_config, legacy_owner_recovery as recovery
from scripts import agent_worktree


def build_draft(*, cwd: Path, issue: int, pr: int, worktree: Path, base: str,
                agent: str, session: str) -> dict[str, Any]:
    if not agent or agent.strip() != agent or not session or session != os.environ.get("CODEX_SESSION_ID"):
        raise recovery.RecoveryEvidenceError("current successor identity is unavailable")
    try:
        legacy_git_config.check_host_config()
        legacy_git_config.check(cwd=cwd, worktree=worktree)
    except legacy_git_config.ConfigError as exc:
        raise recovery.RecoveryEvidenceError("candidate Git configuration is unsupported") from exc
    predecessor = recovery.read_live_predecessor(cwd=cwd, issue=issue)
    candidate = recovery.read_clean_candidate(cwd=cwd, worktree=worktree)
    registration = recovery.read_expired_registration(cwd=cwd, candidate=candidate)
    publication = recovery.read_live_publication(cwd=cwd, pr=pr, branch=candidate["branch"])
    recovery._verify_pr_origin(cwd=cwd, issue=issue, pr=pr, worktree=worktree,
                               candidate=candidate, predecessor=predecessor, publication=publication)
    if not re.fullmatch(r"[0-9a-f]{40,64}", base):
        raise recovery.RecoveryEvidenceError("base must be an exact commit SHA")
    resolved = recovery._git_read(worktree, "rev-parse", "--verify", f"{base}^{{commit}}").decode().strip()
    if resolved != base:
        raise recovery.RecoveryEvidenceError("base commit does not match")
    changed = recovery._git_read(worktree, "diff", "--name-only", "--find-renames", "-z",
                                 f"{base}...{candidate['head']}")
    try:
        changed_files = sorted(set(item.decode("utf-8") for item in changed.split(b"\0") if item))
    except UnicodeDecodeError as exc:
        raise recovery.RecoveryEvidenceError("candidate paths are not UTF-8") from exc
    snapshot = agent_worktree._locked_lifecycle_snapshot(agent_worktree._default_registry_path(cwd))
    prior = snapshot.get(str(worktree))
    if (not isinstance(prior, dict)
            or hashlib.sha256(json.dumps(prior, sort_keys=True).encode()).hexdigest() != registration["history_digest"]
            or agent_worktree._branch_history_digest(snapshot, candidate["branch"]) != registration["branch_history_digest"]
            or recovery.read_clean_candidate(cwd=cwd, worktree=worktree) != candidate):
        raise recovery.RecoveryEvidenceError("candidate or registration changed during readback")
    return {"operator_reconciliation.v1": {
        "issue": issue, "mode": "operator", "account": "RasmusTho",
        "mandate": {"reference": None, "effects": ["reconcile", "claim", "register", "acknowledge"],
                    "repo": predecessor["repo"], "issue": issue},
        "successor": {"agent": agent, "session": session}, "predecessor": predecessor,
        "registration": registration, "candidate": candidate,
        "writer": {"state": None, "delegations": None, "restart": None, "last_activity": None,
                   "boot": None, "sources": {"execution": [], "delegations": [], "restart": []}},
        "publication": {**publication, "state": None, "sources": {"attempts": [], "github": []}},
        "branch": candidate["branch"], "writable_worktree": candidate["path"],
        "predecessor_registration": prior, "branch_history_digest": registration["branch_history_digest"],
        "base": base, "unpublished_candidate_head": candidate["head"], "changed_files": changed_files,
    }}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--base", required=True, help="exact base commit SHA")
    parser.add_argument("--agent", required=True)
    args = parser.parse_args()
    try:
        draft = build_draft(cwd=Path.cwd(), issue=args.issue, pr=args.pr, worktree=args.worktree,
                            base=args.base, agent=args.agent, session=os.environ.get("CODEX_SESSION_ID", ""))
    except (recovery.RecoveryEvidenceError, agent_worktree.WorktreeLifecycleError, OSError, UnicodeDecodeError) as exc:
        print(f"readback refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(draft, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
