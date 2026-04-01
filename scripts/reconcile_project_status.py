#!/usr/bin/env python3
"""
Reconcile GitHub Project v2 Status for repository issues and pull requests.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


GOVERNANCE_PATH = Path(".github/github-governance.yml")


def run_gh(*args: str) -> str:
    result = subprocess.run(
        ["gh", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def load_governance_project_name() -> str:
    content = GOVERNANCE_PATH.read_text(encoding="utf-8")
    match = re.search(r"(?m)^\s*name:\s*(.+?)\s*$", content)
    if not match:
        raise RuntimeError(f"Could not find project name in {GOVERNANCE_PATH}")
    return match.group(1).strip()


def discover_project(owner: str, title: str) -> dict[str, Any]:
    payload = json.loads(run_gh("project", "list", "--owner", owner, "--format", "json"))
    for project in payload.get("projects", []):
        if project.get("title") == title:
            return project
    raise RuntimeError(f'Project "{title}" not found for owner "{owner}"')


def get_status_field(owner: str, project_number: int) -> tuple[str, dict[str, str]]:
    payload = json.loads(
        run_gh("project", "field-list", str(project_number), "--owner", owner, "--format", "json")
    )
    for field in payload.get("fields", []):
        if field.get("name") != "Status":
            continue
        options = {option["name"]: option["id"] for option in field.get("options", [])}
        return field["id"], options
    raise RuntimeError('Project is missing required "Status" field')


def list_project_items(owner: str, project_number: int) -> list[dict[str, Any]]:
    payload = json.loads(
        run_gh(
            "project",
            "item-list",
            str(project_number),
            "--owner",
            owner,
            "--limit",
            "200",
            "--format",
            "json",
        )
    )
    return payload.get("items", [])


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
        return "In Progress"
    return None


def add_item_to_project(owner: str, project_number: int, url: str) -> None:
    run_gh("project", "item-add", str(project_number), "--owner", owner, "--url", url)


def set_project_status(
    owner: str,
    project_id: str,
    item_id: str,
    field_id: str,
    option_id: str,
    dry_run: bool,
) -> None:
    cmd = [
        "project",
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
        print("DRY RUN:", "gh", *cmd)
        return
    run_gh(*cmd)


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
    items = list_project_items(owner, project["number"])
    item = find_item_by_number(items, "Issue", args.issue)
    if item is None:
        print(f'add issue #{args.issue} to project "{project["title"]}"')
        if not args.dry_run:
            add_item_to_project(owner, project["number"], issue["url"])
            items = list_project_items(owner, project["number"])
            item = find_item_by_number(items, "Issue", args.issue)
        if item is None and args.dry_run:
            return 0
        if item is None:
            raise RuntimeError(f"Failed to add issue #{args.issue} to project")

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
    items = list_project_items(owner, project["number"])
    item = find_item_by_number(items, "PullRequest", args.pr)
    if item is None:
        print(f'add pr #{args.pr} to project "{project["title"]}"')
        if not args.dry_run:
            add_item_to_project(owner, project["number"], pr["url"])
            items = list_project_items(owner, project["number"])
            item = find_item_by_number(items, "PullRequest", args.pr)
        if item is None and args.dry_run:
            return 0
        if item is None:
            raise RuntimeError(f"Failed to add pr #{args.pr} to project")

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
    items = list_project_items(owner, project["number"])
    repo = args.repo
    changes = 0
    for item in items:
        content = item.get("content") or {}
        kind = content.get("type")
        number = content.get("number")
        if kind not in {"Issue", "PullRequest"} or not number:
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
    project = discover_project(owner, project_name)
    status_field_id, status_options = get_status_field(owner, project["number"])

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
