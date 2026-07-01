#!/usr/bin/env python3
"""
Reconcile GitHub Project v2 Status for repository issues and pull requests.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.dispatcher.sync_github import classify_github_api_failure


GOVERNANCE_PATH = Path(".github/github-governance.yml")
DEFAULT_PROJECT_NAME = "Agent Delivery Control Plane"
SCAN_WATERMARK_PATH = REPO_ROOT / "runtime" / "dispatcher" / "project_status_reconcile_scan_watermark.json"
PROJECT_ITEM_LIST_INITIAL_LIMIT = 200
PROJECT_ITEM_SCAN_PAGE_SIZE = 100
GH_RETRY_ATTEMPTS = 5
GH_RETRY_BASE_DELAY_SECONDS = 0.4
PROJECT_ITEMS_WITH_UPDATED_AT_QUERY = """
query($owner: String!, $number: Int!, $after: String) {
  user(login: $owner) {
    projectV2(number: $number) {
      items(first: 100, after: $after) {
        totalCount
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          id
          content {
            __typename
            ... on Issue {
              number
              url
              updatedAt
            }
            ... on PullRequest {
              number
              url
              updatedAt
            }
          }
          fieldValues(first: 20) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                field {
                  ... on ProjectV2SingleSelectField {
                    name
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
"""

# GitHub's shared GraphQL pool (~5000 points/hr, shared across every tool/agent
# on this identity) exhausts long before REST core. Below these remaining-budget
# floors we shed the most expensive GraphQL work instead of pushing an already
# strained pool into hard exhaustion. Env-overridable for incident tuning.
# See issues #2681 (daily, budget-gated reconcile) and #2684 (GitHub-API
# observability) for the rationale and thresholds.
GRAPHQL_SCAN_MIN_BUDGET = int(os.environ.get("RECONCILE_GRAPHQL_SCAN_MIN_BUDGET", "500"))
GRAPHQL_OPTIONAL_MIN_BUDGET = int(
    os.environ.get("RECONCILE_GRAPHQL_OPTIONAL_MIN_BUDGET", "250")
)
# Never block a CI runner waiting on a far-off reset; above this many seconds we
# stop retrying and defer to the next (daily / event-driven) reconcile.
GH_MAX_RATE_LIMIT_WAIT_SECONDS = int(
    os.environ.get("RECONCILE_MAX_RATE_LIMIT_WAIT_SECONDS", "120")
)


class ProjectItemListDeferred(RuntimeError):
    """Raised when the project item list cannot be safely materialized."""


def _api_class(args: tuple[str, ...]) -> str:
    """Best-effort classification of which GitHub quota pool a `gh` call spends."""
    if not args:
        return "unknown"
    head = args[0]
    if head == "project":
        return "graphql"  # every `gh project` subcommand is GraphQL-only
    if head in {"issue", "pr"}:
        return "rest"
    if head == "api" and len(args) > 1 and args[1] == "graphql":
        return "graphql"
    if head == "api":
        # `gh api rate_limit` is REST core and does not count against any quota.
        return "rest-core"
    return "unknown"


def _rw_class(args: tuple[str, ...]) -> str:
    return "write" if any(a in {"item-edit", "item-add"} for a in args) else "read"


def _log_event(event: dict[str, Any]) -> None:
    """Emit one structured JSON record to stderr (stdout stays human-readable)."""
    try:
        sys.stderr.write(
            json.dumps({"component": "reconcile_project_status", **event}) + "\n"
        )
    except Exception:
        pass


def _github_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_github_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _scan_started_at() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def load_scan_watermark() -> datetime | None:
    try:
        payload = json.loads(SCAN_WATERMARK_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, str):
        return _github_timestamp(payload)
    if not isinstance(payload, dict):
        return None
    return _github_timestamp(payload.get("last_scan_started_at"))


def persist_scan_watermark(scan_started_at: datetime) -> None:
    SCAN_WATERMARK_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCAN_WATERMARK_PATH.write_text(
        json.dumps(
            {"last_scan_started_at": _format_github_timestamp(scan_started_at)},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _should_retry_gh_error(exc: subprocess.CalledProcessError) -> bool:
    classification = classify_github_api_failure(exc)
    return classification.kind in {"primary_quota", "secondary_quota", "network"}


def graphql_rate_limit() -> tuple[int | None, int | None]:
    """Return ``(remaining, reset_epoch)`` for the GraphQL pool via the REST
    ``rate_limit`` endpoint, which itself does not count against any quota.

    Returns ``(None, None)`` when the budget cannot be determined (fail-open:
    an unreadable meta-probe must not permanently disable reconciliation).
    """
    try:
        out = run_gh(
            "api",
            "rate_limit",
            "--jq",
            ".resources.graphql.remaining,.resources.graphql.reset",
        )
        remaining_str, reset_str = out.split()
        remaining, reset = int(remaining_str), int(reset_str)
        _log_event(
            {
                "event": "github.budget",
                "api": "graphql",
                "remaining": remaining,
                "reset": reset,
            }
        )
        return remaining, reset
    except Exception:
        return None, None


def graphql_budget_remaining() -> int | None:
    return graphql_rate_limit()[0]


def _rate_limit_wait_seconds(exc: subprocess.CalledProcessError) -> int | None:
    """Seconds to wait before retrying a rate-limited call.

    Honors an explicit ``Retry-After`` in stderr; otherwise waits until the
    GraphQL reset (read from the REST ``rate_limit`` endpoint, since the `gh`
    subcommands do not surface response headers). Returns ``None`` when this is
    not a rate-limit error, so the caller falls back to plain jittered backoff.
    """
    classification = classify_github_api_failure(exc)
    if classification.kind not in {"primary_quota", "secondary_quota"}:
        return None
    if classification.retry_after_seconds is not None:
        return classification.retry_after_seconds
    if classification.reset_epoch is not None:
        return max(0, classification.reset_epoch - int(time.time()))
    _remaining, reset = graphql_rate_limit()
    if reset is not None:
        return max(0, reset - int(time.time()))
    return None


def run_gh(*args: str) -> str:
    op = " ".join(args[:2])
    api = _api_class(args)
    rw = _rw_class(args)
    for attempt in range(1, GH_RETRY_ATTEMPTS + 1):
        started = time.monotonic()
        try:
            result = subprocess.run(
                ["gh", *args],
                check=True,
                capture_output=True,
                text=True,
            )
            _log_event(
                {
                    "event": "github.call",
                    "op": op,
                    "api": api,
                    "rw": rw,
                    "attempt": attempt,
                    "status": "ok",
                    "latency_ms": round((time.monotonic() - started) * 1000),
                }
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as exc:
            _log_event(
                {
                    "event": "github.call",
                    "op": op,
                    "api": api,
                    "rw": rw,
                    "attempt": attempt,
                    "status": "error",
                    "latency_ms": round((time.monotonic() - started) * 1000),
                    "error": (exc.stderr or exc.stdout or "")[:200].strip(),
                }
            )
            if attempt == GH_RETRY_ATTEMPTS or not _should_retry_gh_error(exc):
                raise
            wait = _rate_limit_wait_seconds(exc)
            if wait is not None:
                # Rate-limited: wait until reset / Retry-After, but never burn the
                # runner on a far-off reset, and never re-issue the same expensive
                # GraphQL query into a fully exhausted pool.
                if wait > GH_MAX_RATE_LIMIT_WAIT_SECONDS:
                    _log_event(
                        {
                            "event": "github.retry.abort",
                            "op": op,
                            "reason": "reset_beyond_cap",
                            "wait_s": wait,
                        }
                    )
                    raise
                sleep_seconds = float(wait) + 1.0
            else:
                # Transient (non-rate-limit) error: bounded jittered backoff.
                sleep_seconds = GH_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)) + random.uniform(
                    0.0, 0.25
                )
            time.sleep(sleep_seconds)
    raise RuntimeError("unreachable")


def run_gh_project(owner: str, *args: str) -> str:
    # gh project item-edit does not accept --owner on some gh versions.
    if args and args[0] == "item-edit":
        return run_gh("project", *args)
    return run_gh("project", *args, "--owner", owner)


def load_governance_project_name() -> str:
    if not GOVERNANCE_PATH.exists():
        return os.environ.get("GOVERNANCE_PROJECT_NAME", DEFAULT_PROJECT_NAME)
    content = GOVERNANCE_PATH.read_text(encoding="utf-8")
    match = re.search(r"(?m)^\s*name:\s*(.+?)\s*$", content)
    if not match:
        raise RuntimeError(f"Could not find project name in {GOVERNANCE_PATH}")
    return match.group(1).strip()


def discover_project(owner: str, title: str) -> dict[str, Any]:
    payload = json.loads(run_gh_project(owner, "list", "--format", "json"))
    for project in payload.get("projects", []):
        if project.get("title") == title:
            return project
    raise RuntimeError(f'Project "{title}" not found for owner "{owner}"')


def warn_and_exit_if_project_unavailable(args: argparse.Namespace, exc: Exception) -> int:
    target = f"issue #{args.issue}" if args.issue else f"pr #{args.pr}" if args.pr else "project scan"
    print(
        "skip project reconciliation for"
        f" {target}: project board is unavailable to current credentials; "
        "issue/PR truth remains authoritative"
    )
    print(f"detail: {exc}")
    return 0


def get_status_field(owner: str, project_number: int) -> tuple[str, dict[str, str]]:
    payload = json.loads(run_gh_project(owner, "field-list", str(project_number), "--format", "json"))
    for field in payload.get("fields", []):
        if field.get("name") != "Status":
            continue
        options = {option["name"]: option["id"] for option in field.get("options", [])}
        return field["id"], options
    raise RuntimeError('Project is missing required "Status" field')


def list_project_items(owner: str, project_number: int) -> list[dict[str, Any]]:
    limit = PROJECT_ITEM_LIST_INITIAL_LIMIT
    try:
        payload = json.loads(
            run_gh_project(
                owner,
                "item-list",
                str(project_number),
                "--limit",
                str(limit),
                "--format",
                "json",
            )
        )
    except subprocess.CalledProcessError as exc:
        classification = classify_github_api_failure(exc)
        if classification.kind == "resource_limit":
            raise ProjectItemListDeferred(
                "project item-list deferred after resource-limit failure; cannot safely "
                "materialize the full board without pagination"
            ) from exc
        raise
    items = payload.get("items", [])
    total_count = payload.get("totalCount")
    if not isinstance(total_count, int):
        return items
    if len(items) >= total_count:
        return items
    raise ProjectItemListDeferred(
        "project item-list returned a partial board snapshot; cannot safely "
        "materialize the full board without pagination"
    )


def _status_from_field_values(item: dict[str, Any]) -> str | None:
    field_values = item.get("fieldValues") or {}
    for field_value in field_values.get("nodes", []):
        field = field_value.get("field") or {}
        if field.get("name") == "Status":
            return field_value.get("name")
    return None


def _scan_item_from_graphql_node(node: dict[str, Any]) -> dict[str, Any] | None:
    content = node.get("content") or {}
    typename = content.get("__typename")
    if typename not in {"Issue", "PullRequest"}:
        return None
    updated_at = content.get("updatedAt")
    if not updated_at:
        raise RuntimeError(
            "project scan item is missing Issue/PullRequest updatedAt; cannot "
            "safely run incremental scan"
        )
    return {
        "id": node.get("id"),
        "content": {
            "type": typename,
            "number": content.get("number"),
            "url": content.get("url"),
            "updatedAt": updated_at,
        },
        "status": _status_from_field_values(node),
    }


def list_project_items_for_scan(owner: str, project_number: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    after: str | None = None
    while True:
        cmd = [
            "api",
            "graphql",
            "-f",
            f"query={PROJECT_ITEMS_WITH_UPDATED_AT_QUERY}",
            "-F",
            f"owner={owner}",
            "-F",
            f"number={project_number}",
        ]
        if after:
            cmd.extend(["-F", f"after={after}"])
        payload = json.loads(run_gh(*cmd))
        project = ((payload.get("data") or {}).get("user") or {}).get("projectV2")
        if not project:
            raise RuntimeError(f'Project #{project_number} not found for owner "{owner}"')
        page = project.get("items") or {}
        for node in page.get("nodes", []):
            item = _scan_item_from_graphql_node(node)
            if item is not None:
                items.append(item)
        page_info = page.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        after = page_info.get("endCursor")
        if not after:
            raise ProjectItemListDeferred(
                "project scan pagination did not return an end cursor"
            )
    return items


def find_item_by_number(items: list[dict[str, Any]], kind: str, number: int) -> dict[str, Any] | None:
    for item in items:
        content = item.get("content") or {}
        if content.get("type") == kind and content.get("number") == number:
            return item
    return None


def get_issue(repo: str, number: int) -> dict[str, Any]:
    return json.loads(
        run_gh("issue", "view", str(number), "--repo", repo, "--json", "number,state,labels,url,title")
    )


def get_pr(repo: str, number: int) -> dict[str, Any]:
    return json.loads(
        run_gh("pr", "view", str(number), "--repo", repo, "--json", "number,state,isDraft,mergedAt,url,title")
    )


def desired_issue_status(issue: dict[str, Any]) -> str | None:
    if issue.get("state") == "CLOSED":
        return "Done"
    label_names = {label["name"] for label in issue.get("labels", [])}
    if "agent:ready" in label_names:
        return "Ready"
    if {"agent:blocked", "agent:needs-human"} & label_names:
        return "Backlog"
    return None


def desired_pr_status(pr: dict[str, Any], explicit_status: str | None) -> str | None:
    if explicit_status:
        return explicit_status
    if pr.get("mergedAt"):
        return "Done"
    if pr.get("state") == "OPEN":
        return "In Progress" if pr.get("isDraft") else "Review"
    if pr.get("state") == "CLOSED":
        # Closed PR cards are terminal Project artifacts and must not remain blank.
        return "Done"
    return None


def add_item_to_project(owner: str, project_number: int, url: str) -> None:
    run_gh_project(owner, "item-add", str(project_number), "--url", url)


def soft_fail_project_add(
    kind: str,
    number: int,
    project_title: str,
    exc: Exception | None = None,
) -> int:
    print(
        f"soft-fail {kind} #{number}: failed to add to project "
        f'"{project_title}" after bounded retry; content truth remains authoritative'
    )
    if exc is not None:
        print(f"detail: {exc}")
    return 0


def set_project_status(
    owner: str,
    project_id: str,
    item_id: str,
    field_id: str,
    option_id: str,
    dry_run: bool,
) -> None:
    cmd = [
        "item-edit",
        "--id",
        item_id,
        "--project-id",
        project_id,
        "--field-id",
        field_id,
        "--single-select-option-id",
        option_id,
    ]
    if dry_run:
        print("DRY RUN:", "gh", "project", *cmd, "--owner", owner)
        return
    run_gh_project(owner, *cmd)


def reconcile_issue(
    args: argparse.Namespace,
    owner: str,
    project: dict[str, Any],
    status_field_id: str,
    status_options: dict[str, str],
) -> int:
    issue = get_issue(args.repo, args.issue)
    desired = args.status or desired_issue_status(issue)
    if not desired:
        print(f"skip issue #{args.issue}: no derived status")
        return 0
    try:
        items = list_project_items(owner, project["number"])
    except ProjectItemListDeferred as exc:
        print(f"skip issue #{args.issue}: {exc}")
        return 0
    item = find_item_by_number(items, "Issue", args.issue)
    if item is None:
        print(f'add issue #{args.issue} to project "{project["title"]}"')
        if not args.dry_run:
            try:
                add_item_to_project(owner, project["number"], issue["url"])
            except subprocess.CalledProcessError as exc:
                if _should_retry_gh_error(exc):
                    return soft_fail_project_add("issue", args.issue, project["title"], exc)
                raise
            items = list_project_items(owner, project["number"])
            item = find_item_by_number(items, "Issue", args.issue)
        if item is None and args.dry_run:
            return 0
        if item is None:
            return soft_fail_project_add("issue", args.issue, project["title"])

    current = item.get("status")
    if current == desired:
        print(f"issue #{args.issue}: already {desired}")
        return 0
    print(f"issue #{args.issue}: {current or '<none>'} -> {desired}")
    set_project_status(
        owner,
        project["id"],
        item["id"],
        status_field_id,
        status_options[desired],
        args.dry_run,
    )
    return 0


def reconcile_pr(
    args: argparse.Namespace,
    owner: str,
    project: dict[str, Any],
    status_field_id: str,
    status_options: dict[str, str],
) -> int:
    pr = get_pr(args.repo, args.pr)
    desired = desired_pr_status(pr, args.status)
    if not desired:
        print(f"skip pr #{args.pr}: no derived status")
        return 0
    try:
        items = list_project_items(owner, project["number"])
    except ProjectItemListDeferred as exc:
        print(f"skip pr #{args.pr}: {exc}")
        return 0
    item = find_item_by_number(items, "PullRequest", args.pr)
    if item is None:
        print(f'add pr #{args.pr} to project "{project["title"]}"')
        if not args.dry_run:
            try:
                add_item_to_project(owner, project["number"], pr["url"])
            except subprocess.CalledProcessError as exc:
                if _should_retry_gh_error(exc):
                    return soft_fail_project_add("pr", args.pr, project["title"], exc)
                raise
            items = list_project_items(owner, project["number"])
            item = find_item_by_number(items, "PullRequest", args.pr)
        if item is None and args.dry_run:
            return 0
        if item is None:
            return soft_fail_project_add("pr", args.pr, project["title"])

    current = item.get("status")
    if current == desired:
        print(f"pr #{args.pr}: already {desired}")
        return 0
    print(f"pr #{args.pr}: {current or '<none>'} -> {desired}")
    set_project_status(
        owner,
        project["id"],
        item["id"],
        status_field_id,
        status_options[desired],
        args.dry_run,
    )
    return 0


def reconcile_scan(
    args: argparse.Namespace,
    owner: str,
    project: dict[str, Any],
    status_field_id: str,
    status_options: dict[str, str],
) -> int:
    scan_started_at = _scan_started_at()
    watermark = load_scan_watermark()
    try:
        items = list_project_items_for_scan(owner, project["number"])
    except ProjectItemListDeferred as exc:
        print(f"skip project scan: {exc}")
        return 0
    repo = args.repo
    changes = 0
    for item in items:
        content = item.get("content") or {}
        kind = content.get("type")
        number = content.get("number")
        if kind not in {"Issue", "PullRequest"} or not number:
            continue
        content_updated_at = _github_timestamp(content.get("updatedAt"))
        if watermark is not None and content_updated_at is not None and content_updated_at < watermark:
            continue
        current = item.get("status")
        desired = None
        url = content.get("url")
        if kind == "Issue":
            issue = get_issue(repo, number)
            desired = desired_issue_status(issue)
            url = issue["url"]
        elif kind == "PullRequest":
            pr = get_pr(repo, number)
            desired = desired_pr_status(pr, None)
            url = pr["url"]
        if not desired:
            continue
        if current == desired:
            continue
        print(f"{kind.lower()} #{number}: {current or '<none>'} -> {desired}")
        set_project_status(
            owner,
            project["id"],
            item["id"],
            status_field_id,
            status_options[desired],
            args.dry_run,
        )
        changes += 1
        if item.get("id") is None and not args.dry_run and url:
            add_item_to_project(owner, project["number"], url)
    if not args.dry_run:
        persist_scan_watermark(scan_started_at)
    print(f"scan complete: {changes} change(s)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--owner", help="Project owner; defaults to repo owner")
    parser.add_argument("--issue", type=int, help="Issue number to reconcile")
    parser.add_argument("--pr", type=int, help="Pull request number to reconcile")
    parser.add_argument("--scan", action="store_true", help="Reconcile all existing project items")
    parser.add_argument("--status", choices=["Backlog", "Ready", "In Progress", "Review", "Done"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    mode_count = sum(bool(value) for value in (args.issue, args.pr, args.scan))
    if mode_count != 1:
        parser.error("pass exactly one of --issue, --pr, or --scan")

    owner = args.owner or args.repo.split("/", 1)[0]
    project_name = load_governance_project_name()

    # Budget pre-gate — runs BEFORE any `gh project` GraphQL. `discover_project`
    # and `get_status_field` below each spend a GraphQL call, so the budget must
    # be checked here, not inside the per-mode reconcilers, or a burst of
    # low-budget events still drains the pool on discovery before skipping. The
    # probe itself is the free REST rate_limit endpoint. Scan uses the higher
    # floor; event reconciles use the optional floor.
    budget = graphql_budget_remaining()
    budget_floor = GRAPHQL_SCAN_MIN_BUDGET if args.scan else GRAPHQL_OPTIONAL_MIN_BUDGET
    if budget is not None and budget < budget_floor:
        target = (
            "project scan"
            if args.scan
            else f"issue #{args.issue}"
            if args.issue
            else f"pr #{args.pr}"
        )
        print(
            f"skip {target}: GraphQL budget low (remaining={budget} < {budget_floor}) "
            "before project discovery; deferring to the next daily or manual reconcile"
        )
        _log_event(
            {
                "event": "github.budget.skip",
                "target": target,
                "stage": "pre-discovery",
                "remaining": budget,
            }
        )
        return 0

    try:
        project = discover_project(owner, project_name)
        status_field_id, status_options = get_status_field(owner, project["number"])
    except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        return warn_and_exit_if_project_unavailable(args, exc)

    if args.scan:
        return reconcile_scan(args, owner, project, status_field_id, status_options)
    if args.issue:
        return reconcile_issue(args, owner, project, status_field_id, status_options)
    return reconcile_pr(args, owner, project, status_field_id, status_options)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        if exc.stderr:
            sys.stderr.write(exc.stderr)
        raise
