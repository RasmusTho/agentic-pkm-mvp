#!/usr/bin/env python3
"""Report or boundedly reconcile canonical blocker-action labels via GitHub REST."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.builderops.blocker_actions import ACTION_LABELS, LEGACY_HUMAN_ACTIONS, classify, label_names


def plan(issue: dict[str, Any]) -> dict[str, Any]:
    labels = label_names(issue)
    desired = set(labels)
    changes: list[dict[str, str]] = []
    for old, new in LEGACY_HUMAN_ACTIONS.items():
        if old in desired:
            desired.remove(old); desired.add(new); changes.append({"remove": old, "add": new})
    lifecycle = labels & {"agent:blocked", "agent:needs-human"}
    if labels & ACTION_LABELS and not lifecycle:
        for action in labels & ACTION_LABELS:
            desired.remove(action); changes.append({"remove": action, "add": ""})
    elif lifecycle == {"agent:blocked"} and not labels & ACTION_LABELS:
        desired.add("action:repair-contract"); changes.append({"remove": "", "add": "action:repair-contract"})
    verdict = classify(desired, open_issue=str(issue.get("state", "open")).lower() == "open")
    return {"issue": issue.get("number"), "before": sorted(labels), "after": sorted(desired), "changes": changes, "errors": list(verdict.errors)}


def _api(repo: str, endpoint: str, *, method: str = "GET", payload: Any = None) -> Any:
    cmd = ["gh", "api", endpoint, "--method", method]
    if payload is not None:
        cmd += ["--input", "-"]
    result = subprocess.run(cmd, input=json.dumps(payload) if payload is not None else None, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout) if result.stdout.strip() else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True); parser.add_argument("--issue", type=int, action="append", default=[])
    parser.add_argument("--apply", action="store_true"); parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 5: parser.error("--limit must be 1..5")
    if len(args.issue) > args.limit: parser.error("issue set exceeds bounded --limit")
    owner, name = args.repo.split("/", 1)
    issues = [_api(args.repo, f"repos/{owner}/{name}/issues/{number}") for number in args.issue]
    plans = [plan(issue) for issue in issues]
    if args.apply:
        # Label creation is deterministic and idempotent.  It is intentionally
        # limited to the canonical family; no legacy or unrelated label is deleted.
        existing = _api(args.repo, f"repos/{owner}/{name}/labels?per_page=100")
        existing_names = {str(label.get("name")) for label in existing}
        for label in sorted(ACTION_LABELS - existing_names):
            _api(args.repo, f"repos/{owner}/{name}/labels", method="POST", payload={"name": label, "color": "bfdadc", "description": "Canonical next action for a non-active Issue"})
        for item in plans:
            if item["errors"]: raise RuntimeError(f"refusing drifted issue #{item['issue']}: {item['errors']}")
            _api(args.repo, f"repos/{owner}/{name}/issues/{item['issue']}", method="PATCH", payload={"labels": item["after"]})
            if item["changes"]:
                action = next((label for label in item["after"] if label.startswith("action:")), "none")
                _api(args.repo, f"repos/{owner}/{name}/issues/{item['issue']}/comments", method="POST", payload={"body": "```yaml\nreceipt: blocker_action.v1\naction: " + action + "\nowner: unknown\nnext_action: verify and repair the live Issue contract before pickup\nunblocks_when: fresh authority evidence establishes a valid transition\ndependency_refs: []\nreview_at: null\nlast_verified_at: migration apply readback\n```\n\nBounded migration receipt; it does not infer an underlying blocker cause or claim implementation work."})
    print(json.dumps({"mode": "apply" if args.apply else "report", "plans": plans}, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__": raise SystemExit(main())
