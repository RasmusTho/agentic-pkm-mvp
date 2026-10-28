#!/usr/bin/env python3
"""Read-only report of class-A blocked Issues that may be ready to unblock.

Class A is an open ``agent:blocked`` + ``action:wait-dependency`` Issue whose
current, context-bound ``blocker_action.v1`` receipt is builder-owned and names
same-repository dependencies.  Such an Issue is a *candidate* when every
dependency is terminal-completed (Issue closed as ``completed``, PR merged) and
its current body classifies ``ready_candidate`` under the labels it would carry
after the transition.

This report never writes labels, comments, Project state, or leases.  A
candidate is input for a governed re-read under ``BLOCKER_ACTION_CONTRACT.md``;
it is not authority to pick up blocked work.

The optional ``unblock_predicate`` receipt line is a proposed (not yet
normative) field.  When present it replaces the derived predicate::

    unblock_predicate: {"all_completed": ["#3860"], "readiness": "strict"}
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.builderops.blocker_actions import (  # noqa: E402
    ACTION_LABELS,
    is_blocker_action_receipt_marker,
    label_names,
    receipt_for_context,
)
from scripts.validate_issue_readiness import classify_issue_body  # noqa: E402

PREDICATE_KEYS = frozenset({"all_completed", "readiness"})
_LOCAL_REF = re.compile(r"#(\d+)\Z")
_URL_REF = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+)/(issues|pull)/(\d+)(#\S*)?\Z")

Fetch = Callable[[str], Any]


def _receipt_body(comments: Iterable[dict[str, Any]]) -> str:
    """Return the newest receipt-marker body, matching ``latest_receipt``."""
    markers = [comment for comment in comments if is_blocker_action_receipt_marker(comment)]
    return str(markers[-1].get("body") or "") if markers else ""


def _field_items(body: str, key: str) -> list[str] | None:
    """Read one receipt list field in inline (``[a, b]``) or block (``- a``) form."""
    lines = body.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith(f"{key}:"):
            continue
        value = stripped.split(":", 1)[1].strip()
        if value.startswith("["):
            try:
                items = json.loads(value)
            except json.JSONDecodeError:
                items = [part.strip().strip("'\"") for part in value.strip("[]").split(",")]
            return [str(item).strip() for item in items if str(item).strip()]
        if value in {"", "null"}:
            items = []
            for follow in lines[index + 1:]:
                follow = follow.strip()
                if not follow.startswith("- "):
                    break
                items.append(follow[2:].strip().strip("'\""))
            return items
        return [value.strip("'\"")]
    return None


def classify_ref(ref: str, repo: str) -> tuple[str, int | None]:
    """Classify one dependency ref as ``local``, ``evidence`` or ``unresolvable``."""
    ref = ref.strip().strip("'\"")
    if match := _LOCAL_REF.fullmatch(ref):
        return "local", int(match.group(1))
    if match := _URL_REF.fullmatch(ref):
        if match.group(1).lower() != repo.lower():
            return "unresolvable", None
        # A comment permalink is cited evidence, not a dependency to wait on.
        if (match.group(4) or "").startswith("#issuecomment-"):
            return "evidence", None
        return "local", int(match.group(3))
    # Foreign ``owner/repo#N`` and free-text refs cannot be checked here.
    return "unresolvable", None


def parse_predicate(body: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse the proposed ``unblock_predicate`` line; return (predicate, error)."""
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("unblock_predicate:"):
            continue
        value = stripped.split(":", 1)[1].strip()
        try:
            predicate = json.loads(value)
        except json.JSONDecodeError:
            return None, "unblock_predicate_not_json"
        if (
            not isinstance(predicate, dict)
            or set(predicate) - PREDICATE_KEYS
            or not isinstance(predicate.get("all_completed"), list)
            or not predicate["all_completed"]
            or predicate.get("readiness", "strict") != "strict"
        ):
            return None, "unblock_predicate_invalid"
        return predicate, None
    return None, None


def dependency_state(item: dict[str, Any] | None) -> str:
    """Return ``completed``, ``open`` or ``not_completed`` for one Issue/PR readback."""
    if not isinstance(item, dict):
        return "not_completed"
    if str(item.get("state", "")).lower() == "open":
        return "open"
    if item.get("pull_request") is not None:
        return "completed" if (item["pull_request"] or {}).get("merged_at") else "not_completed"
    return "completed" if item.get("state_reason") == "completed" else "not_completed"


def post_transition_labels(labels: set[str]) -> list[str]:
    """Labels the Issue would carry after the governed blocked -> ready transition."""
    return sorted(labels - {"agent:blocked"} - ACTION_LABELS)


def evaluate(issue: dict[str, Any], comments: list[dict[str, Any]], repo: str, fetch_issue: Callable[[int], Any]) -> dict[str, Any]:
    """Evaluate one Issue; ``fetch_issue`` is the only dependency readback."""
    number = issue.get("number")
    labels = label_names(issue)
    result: dict[str, Any] = {"issue": number, "title": issue.get("title", ""), "verdict": "", "reasons": []}
    if issue.get("pull_request") is not None or str(issue.get("state", "")).lower() != "open":
        result.update(verdict="not_class_a", reasons=["not_open_issue"])
        return result
    if "agent:blocked" not in labels or "action:wait-dependency" not in labels:
        result.update(verdict="not_class_a", reasons=["not_blocked_wait_dependency"])
        return result
    verdict, receipt = receipt_for_context(labels, comments, open_issue=True)
    if receipt is None:
        result.update(verdict="not_class_a", reasons=list(verdict.errors) or ["no_bound_receipt"])
        return result
    result["unblocks_when"] = receipt.get("unblocks_when")
    if receipt.get("owner") != "builder":
        result.update(verdict="not_class_a", reasons=[f"owner_{receipt.get('owner')}"])
        return result

    body = _receipt_body(comments)
    predicate, predicate_error = parse_predicate(body)
    if predicate_error:
        result.update(verdict="unresolvable_refs", reasons=[predicate_error])
        return result
    refs = predicate["all_completed"] if predicate else (_field_items(body, "dependency_refs") or [])
    result["predicate_source"] = "declared" if predicate else "derived"

    local: list[int] = []
    unresolvable: list[str] = []
    for ref in refs:
        kind, ref_number = classify_ref(str(ref), repo)
        if kind == "local" and ref_number is not None and ref_number != number:
            local.append(ref_number)
        elif kind == "unresolvable":
            unresolvable.append(str(ref))
    local = sorted(set(local))
    result["dependencies"] = {}
    if unresolvable:
        result.update(verdict="unresolvable_refs", reasons=[f"unresolvable:{ref}" for ref in unresolvable])
        return result
    if not local:
        result.update(verdict="unresolvable_refs", reasons=["no_local_dependency_refs"])
        return result
    for ref_number in local:
        result["dependencies"][f"#{ref_number}"] = dependency_state(fetch_issue(ref_number))
    states = set(result["dependencies"].values())
    if "open" in states:
        result.update(verdict="waiting_on_dependencies", reasons=[ref for ref, state in result["dependencies"].items() if state == "open"])
        return result
    if "not_completed" in states:
        result.update(verdict="dependency_not_completed", reasons=[ref for ref, state in result["dependencies"].items() if state == "not_completed"])
        return result

    report = classify_issue_body(
        issue.get("body") or "",
        issue_number=number if isinstance(number, int) else None,
        labels=post_transition_labels(labels),
        repo_root=REPO_ROOT,
    )
    result["readiness"] = report.readiness_classification
    if report.readiness_classification != "ready_candidate":
        result.update(verdict="readiness_failed", reasons=list(report.repair_guidance))
        return result
    result.update(verdict="candidate", reasons=[])
    return result


def _api(endpoint: str) -> Any:
    result = subprocess.run(["gh", "api", endpoint, "--method", "GET"], text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout) if result.stdout.strip() else None


def _pages(fetch: Fetch, endpoint: str) -> list[dict[str, Any]]:
    """Read every page so neither the blocked set nor receipts are truncated."""
    items: list[dict[str, Any]] = []
    page = 1
    separator = "&" if "?" in endpoint else "?"
    while True:
        batch = fetch(f"{endpoint}{separator}per_page=100&page={page}")
        if not isinstance(batch, list):
            raise RuntimeError(f"paged readback did not return a list: {endpoint}")
        items.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < 100:
            return items
        page += 1


def collect(repo: str, numbers: list[int], fetch: Fetch = _api) -> list[dict[str, Any]]:
    base = f"repos/{repo}/issues"
    if numbers:
        issues = [fetch(f"{base}/{number}") for number in numbers]
    else:
        issues = _pages(fetch, f"{base}?state=open&labels=agent:blocked")
    cache: dict[int, Any] = {}

    def fetch_issue(number: int) -> Any:
        if number not in cache:
            try:
                cache[number] = fetch(f"{base}/{number}")
            except RuntimeError:
                cache[number] = None
        return cache[number]

    results = []
    for issue in issues:
        comments = _pages(fetch, f"{base}/{issue['number']}/comments")
        results.append(evaluate(issue, comments, repo, fetch_issue))
    return sorted(results, key=lambda item: (item["verdict"] != "candidate", item["issue"]))


def render_markdown(results: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for item in results:
        counts[item["verdict"]] = counts.get(item["verdict"], 0) + 1
    lines = ["# Unblock candidates (read-only)", "", "| Verdict | Count |", "|---|---|"]
    lines += [f"| {verdict} | {count} |" for verdict, count in sorted(counts.items())]
    lines += ["", "| Issue | Verdict | Predicate | Detail |", "|---|---|---|---|"]
    for item in results:
        if item["verdict"] == "not_class_a":
            continue
        detail = ", ".join(item["reasons"][:3]) if item["reasons"] else ", ".join(item.get("dependencies", {}))
        lines.append(f"| #{item['issue']} | {item['verdict']} | {item.get('predicate_source', '')} | {detail.replace('|', '/')[:160]} |")
    lines += ["", "A candidate requires a governed re-read before any lifecycle change; derived predicates also need",
              "confirmation that `unblocks_when` names no further evidence gate."]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--issue", type=int, action="append", default=[], help="limit to these Issues")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args()
    if "/" not in args.repo:
        parser.error("--repo must be owner/name")
    results = collect(args.repo, args.issue)
    if args.format == "markdown":
        print(render_markdown(results), end="")
    else:
        print(json.dumps({"mode": "report", "results": results}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
