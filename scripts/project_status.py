#!/usr/bin/env python3
"""
Project PR status projection helper.

Maps GitHub PR lifecycle events to a deterministic Project `Status` and then
delegates the actual write to the existing reconcile script.
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def parse_bool(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def desired_status(action: str, draft: bool | None) -> str:
    if action in {"opened", "reopened"}:
        if draft is None:
            raise ValueError("draft is required for opened/reopened events")
        return "In Progress" if draft else "Review"
    if action == "ready_for_review":
        return "Review"
    if action == "converted_to_draft":
        return "In Progress"
    if action == "closed":
        # Both merged and unmerged-closed PRs are terminal Project artifacts.
        return "Done"
    raise ValueError(f"unsupported pull request action: {action}")


# Actions whose terminal projection must be re-derived from the LIVE PR state by
# the reconcile script rather than forced via an explicit `--status` override.
#
# A `closed` webhook can arrive after the PR has already been re-opened (the
# close->reopen race): forcing `--status Done` would slam a now-OPEN PR card to
# Done. For `closed` we therefore pass NO explicit status and let
# reconcile_project_status.desired_pr_status read the live `pr.state` — which
# yields Done only for a still-merged/closed PR, and In Progress/Review for a
# reopened one (PR #2055 review residual).
_LIVE_STATE_DERIVED_ACTIONS = frozenset({"closed"})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--pr", type=int, required=True, help="Pull request number")
    parser.add_argument("--action", required=True, help="GitHub pull_request action")
    parser.add_argument("--draft", help="True when the PR is currently a draft")
    args = parser.parse_args()

    draft = None if args.draft is None else parse_bool(args.draft)
    # Validate the action maps to a status (raises on unsupported actions) even
    # when we will not forward an explicit override.
    status = desired_status(args.action, draft)
    cmd = [
        sys.executable,
        "scripts/reconcile_project_status.py",
        "--repo",
        args.repo,
        "--pr",
        str(args.pr),
    ]
    if args.action not in _LIVE_STATE_DERIVED_ACTIONS:
        cmd += ["--status", status]
    subprocess.run(cmd, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
