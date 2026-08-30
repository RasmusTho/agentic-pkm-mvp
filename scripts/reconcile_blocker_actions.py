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

from app.builderops.blocker_actions import ACTION_LABELS, LEGACY_HUMAN_ACTIONS, classify, label_names, receipt_for_action, receipt_for_context


_REPAIRABLE_RECEIPT_ERRORS = frozenset({
    "missing_or_invalid_blocker_action_receipt",
    "receipt_action_mismatch",
})


def _receipt_disposition(
    labels: set[str], comments: list[dict[str, Any]], *, open_issue: bool
) -> tuple[str, list[str], str | None]:
    """Classify receipt state without turning evidence drift into label drift."""
    if not labels & ({"agent:blocked", "agent:needs-human"} | ACTION_LABELS):
        return "not_applicable", [], None
    verdict, _ = receipt_for_context(labels, comments, open_issue=open_issue)
    errors = list(verdict.errors)
    if not errors:
        return "receipt_current", errors, verdict.action
    if verdict.action and set(errors).issubset(_REPAIRABLE_RECEIPT_ERRORS):
        return "receipt_repair", errors, verdict.action
    return "drift", errors, verdict.action


def plan(issue: dict[str, Any], comments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    labels = label_names(issue)
    desired = set(labels)
    changes: list[dict[str, str]] = []
    errors: list[str] = []
    for old, new in LEGACY_HUMAN_ACTIONS.items():
        if old in desired:
            live_actions = desired & ACTION_LABELS
            if new in desired:
                # A prior partial apply already established the exact successor.
                desired.remove(old)
                changes.append({"remove": old, "add": ""})
            elif live_actions:
                # Never add a second successor over a conflicting live action.
                errors.append("legacy_successor_conflict")
            else:
                desired.remove(old); desired.add(new)
                changes.extend(({"remove": "", "add": new}, {"remove": old, "add": ""}))
    lifecycle = labels & {"agent:blocked", "agent:needs-human"}
    if labels & ACTION_LABELS and not lifecycle:
        for action in labels & ACTION_LABELS:
            desired.remove(action); changes.append({"remove": action, "add": ""})
    elif lifecycle == {"agent:blocked"} and not labels & ACTION_LABELS:
        desired.add("action:repair-contract"); changes.append({"remove": "", "add": "action:repair-contract"})
    open_issue = str(issue.get("state", "open")).lower() == "open"
    verdict = classify(desired, open_issue=open_issue)
    all_errors = errors + list(verdict.errors)
    if all_errors:
        disposition = "drift"
        receipt_errors: list[str] = []
        action = verdict.action
    elif changes:
        # The post-label state needs one newly bound receipt; it cannot be
        # truthfully classified from a pre-mutation comment stream.
        disposition = "label_reconciliation"
        receipt_errors = []
        action = verdict.action
    else:
        disposition, receipt_errors, action = _receipt_disposition(
            desired, comments or [], open_issue=open_issue
        )
    return {
        "issue": issue.get("number"), "before": sorted(labels), "after": sorted(desired),
        "changes": changes, "errors": all_errors, "receipt_errors": receipt_errors,
        "action": action, "disposition": disposition,
    }


def _api(repo: str, endpoint: str, *, method: str = "GET", payload: Any = None) -> Any:
    cmd = ["gh", "api", endpoint, "--method", method]
    if payload is not None:
        cmd += ["--input", "-"]
    result = subprocess.run(cmd, input=json.dumps(payload) if payload is not None else None, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout) if result.stdout.strip() else None


def _labels(issue: dict[str, Any]) -> set[str]:
    return label_names(issue)


def _mutate_label(repo: str, endpoint: str, *, add: str | None = None, remove: str | None = None) -> None:
    """Use GitHub's narrow label endpoints, never a whole-array PATCH."""
    if bool(add) == bool(remove):
        raise ValueError("exactly one narrow label mutation is required")
    if add:
        _api(repo, f"{endpoint}/labels", method="POST", payload={"labels": [add]})
    else:
        _api(repo, f"{endpoint}/labels/{remove}", method="DELETE")


def _receipt_text(receipt: dict[str, object]) -> str:
    lines = ["```yaml"] + [f"{key}: {value if key != 'dependency_refs' else '[]'}" for key, value in receipt.items()] + ["```", "", "Bounded migration receipt; it does not infer an underlying blocker cause or claim implementation work."]
    return "\n".join(lines)


def _comments(repo: str, endpoint: str) -> list[dict[str, Any]]:
    comments = _api(repo, f"{endpoint}/comments?per_page=100")
    if not isinstance(comments, list):
        raise RuntimeError("comment readback did not return a list")
    return [comment for comment in comments if isinstance(comment, dict)]


def _current_receipt_state(live: dict[str, Any], comments: list[dict[str, Any]]) -> tuple[str, list[str], str | None]:
    return _receipt_disposition(
        _labels(live), comments, open_issue=str(live.get("state", "")).lower() == "open"
    )


def apply_plan(repo: str, owner: str, name: str, item: dict[str, Any]) -> dict[str, Any]:
    """Re-read, validate and apply one plan with narrow mutations and readback."""
    endpoint = f"repos/{owner}/{name}/issues/{item['issue']}"
    live = _api(repo, endpoint)
    if _labels(live) != set(item["before"]) or str(live.get("state", "open")).lower() != "open":
        raise RuntimeError(f"refusing stale snapshot for issue #{item['issue']}")
    if item["errors"]:
        raise RuntimeError(f"refusing drifted issue #{item['issue']}: {item['errors']}")
    if not item["changes"] and item["disposition"] == "not_applicable":
        raise RuntimeError(f"refusing non-blocker issue #{item['issue']}")
    live_comments = _comments(repo, endpoint)
    live_disposition, live_receipt_errors, live_action = _current_receipt_state(live, live_comments)
    if not item["changes"] and live_action != item.get("action"):
        raise RuntimeError(f"refusing lifecycle/action drift for issue #{item['issue']}")
    # A concurrent successful repair wins: retries converge without another
    # receipt write, even when this plan was made while evidence was absent.
    if not item["changes"] and live_disposition == "receipt_current":
        return {"issue": item["issue"], "labels": sorted(_labels(live)), "action": live_action, "disposition": "receipt_current"}
    if not item["changes"] and live_disposition != "receipt_repair":
        raise RuntimeError(f"refusing receipt drift for issue #{item['issue']}: {live_receipt_errors}")
    expected_labels = set(item["before"])
    for change in item["changes"]:
        # Immediate re-read closes stale observation before every authority write.
        current = _api(repo, endpoint)
        current_labels = _labels(current)
        if str(current.get("state", "open")).lower() != "open" or current_labels != expected_labels:
            raise RuntimeError(f"refusing terminal drift for issue #{item['issue']}")
        if change["remove"] and change["remove"] not in current_labels:
            raise RuntimeError(f"refusing label drift for issue #{item['issue']}")
        if change["add"] and change["add"] in current_labels:
            raise RuntimeError(f"refusing duplicate mutation for issue #{item['issue']}")
        _mutate_label(repo, endpoint, add=change["add"] or None, remove=change["remove"] or None)
        expected_labels.discard(change["remove"])
        if change["add"]:
            expected_labels.add(change["add"])
        readback = _api(repo, endpoint)
        if _labels(readback) != expected_labels:
            raise RuntimeError(f"post-mutation label drift for issue #{item['issue']}")
        verdict = classify(_labels(readback), open_issue=True)
        if verdict.errors:
            raise RuntimeError(f"post-mutation lifecycle/action drift for issue #{item['issue']}: {verdict.errors}")
    final = _api(repo, endpoint)
    final_verdict = classify(_labels(final), open_issue=True)
    if final_verdict.errors:
        raise RuntimeError(f"post-apply drift for issue #{item['issue']}: {final_verdict.errors}")
    final_comments = _comments(repo, endpoint)
    final_disposition, final_receipt_errors, action = _current_receipt_state(final, final_comments)
    if final_disposition == "receipt_current":
        return {"issue": item["issue"], "labels": sorted(_labels(final)), "action": action, "disposition": "receipt_current"}
    if final_disposition != "receipt_repair" or not action:
        raise RuntimeError(f"post-apply receipt drift for issue #{item['issue']}: {final_receipt_errors}")
    if item["changes"] or item["disposition"] == "receipt_repair":
        receipt = receipt_for_action(action)
        created = _api(repo, f"{endpoint}/comments", method="POST", payload={"body": _receipt_text(receipt)})
        created_id = created.get("id") if isinstance(created, dict) else None
        exact_comment = _api(repo, f"repos/{owner}/{name}/issues/comments/{created_id}") if created_id else None
        receipt_verdict, exact_receipt = receipt_for_context(
            _labels(final), [exact_comment] if exact_comment else [],
            open_issue=str(final.get("state", "")).lower() == "open",
        )
        if exact_receipt != receipt or receipt_verdict.errors:
            raise RuntimeError(f"receipt readback mismatch for issue #{item['issue']}")
        terminal = _api(repo, endpoint)
        terminal_comments = _comments(repo, endpoint)
        terminal_open = str(terminal.get("state", "")).lower() == "open"
        final_open = str(final.get("state", "")).lower() == "open"
        if (
            terminal_open != final_open
            or _labels(terminal) != _labels(final)
            or receipt_for_context(_labels(terminal), terminal_comments, open_issue=terminal_open)[0].errors
        ):
            raise RuntimeError(f"post-receipt lifecycle/action drift for issue #{item['issue']}")
    return {"issue": item["issue"], "labels": sorted(_labels(final)), "action": final_verdict.action, "disposition": "receipt_repaired"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True); parser.add_argument("--issue", type=int, action="append", default=[])
    parser.add_argument("--apply", action="store_true"); parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 5: parser.error("--limit must be 1..5")
    if len(args.issue) > args.limit: parser.error("issue set exceeds bounded --limit")
    owner, name = args.repo.split("/", 1)
    issues = [_api(args.repo, f"repos/{owner}/{name}/issues/{number}") for number in args.issue]
    plans = [plan(issue, _comments(args.repo, f"repos/{owner}/{name}/issues/{issue['number']}")) for issue in issues]
    if args.apply:
        # Label creation is deterministic and idempotent.  It is intentionally
        # limited to the canonical family; no legacy or unrelated label is deleted.
        existing = _api(args.repo, f"repos/{owner}/{name}/labels?per_page=100")
        existing_names = {str(label.get("name")) for label in existing}
        for label in sorted(ACTION_LABELS - existing_names):
            _api(args.repo, f"repos/{owner}/{name}/labels", method="POST", payload={"name": label, "color": "bfdadc", "description": "Canonical next action for a non-active Issue"})
        for item in plans:
            apply_plan(args.repo, owner, name, item)
    print(json.dumps({"mode": "apply" if args.apply else "report", "plans": plans}, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__": raise SystemExit(main())
