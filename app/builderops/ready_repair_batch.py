"""Batch readiness repair planning for epic child issues."""

from __future__ import annotations

import subprocess
from dataclasses import asdict
from typing import Any, Callable, Mapping, Sequence

from scripts.validate_issue_readiness import classify_issue_body

SCHEMA_VERSION = 1
PROJECT_TITLE = "Agent Delivery Control Plane"
READY_STATUS = "Ready"

CommandRunner = Callable[[Sequence[str]], Mapping[str, Any]]


class ReadyRepairBatchError(ValueError):
    """Raised when ready-repair batch input is invalid."""


def build_ready_repair_batch(
    *,
    issues: Sequence[Mapping[str, Any]],
    repo: str = "OWNER/REPO",
    apply: bool = False,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Plan or explicitly apply Ready repairs for a child issue batch.

    Default mode is dry-run only. Apply mode is explicit and executes only the
    proposed commands for issues that passed strict readiness validation.
    """

    normalized_repo = _normalize_repo(repo)
    normalized_issues = [_normalize_issue(issue) for issue in issues]
    runner = command_runner or _subprocess_runner
    issue_reports = [
        _issue_ready_repair_report(issue, repo=normalized_repo)
        for issue in normalized_issues
    ]

    command_results: list[dict[str, Any]] = []
    if apply:
        for issue_report in issue_reports:
            if issue_report["status"] != "ready_candidate":
                continue
            for command in issue_report["proposed_commands"]:
                result = dict(runner(command["argv"]))
                command_result = {
                    "issue_number": issue_report["issue_number"],
                    "name": command["name"],
                    "argv": command["argv"],
                    "returncode": int(result.get("returncode", 0)),
                    "ok": bool(result.get("ok", result.get("returncode", 0) == 0)),
                    "stdout": result.get("stdout", ""),
                    "stderr": result.get("stderr", ""),
                }
                command_results.append(command_result)
                if not command_result["ok"]:
                    break

    failed_commands = [item for item in command_results if not item["ok"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "dry_run": not apply,
        "apply": apply,
        "repo": normalized_repo,
        "authority_order": [
            "github_issue_body_labels_state",
            "strict_readiness_validator",
            "github_project_projection",
        ],
        "issues": issue_reports,
        "command_results": command_results,
        "mutations_performed": bool(command_results),
        "blocked": any(item["status"] == "blocked" for item in issue_reports) or bool(failed_commands),
        "summary": {
            "issue_count": len(issue_reports),
            "ready_candidate_count": sum(
                1 for item in issue_reports if item["status"] == "ready_candidate"
            ),
            "already_ready_count": sum(
                1 for item in issue_reports if item["status"] == "already_ready"
            ),
            "blocked_count": sum(1 for item in issue_reports if item["status"] == "blocked"),
            "planned_command_count": sum(
                len(item["proposed_commands"]) for item in issue_reports
            ),
            "executed_command_count": len(command_results),
            "failed_command_count": len(failed_commands),
        },
        "verification_reads": [
            {
                "issue_number": item["issue_number"],
                "command": f"gh issue view {item['issue_number']} --repo {normalized_repo} --json labels,projectItems,state",
            }
            for item in issue_reports
            if item["proposed_commands"]
        ],
        "source": "builderops.ready_repair_batch",
    }


def _issue_ready_repair_report(issue: Mapping[str, Any], *, repo: str) -> dict[str, Any]:
    labels = list(issue["labels"])
    readiness = classify_issue_body(
        issue["body"],
        issue_number=issue["number"],
        labels=labels,
    )
    classification = readiness.readiness_classification
    blocked_reasons: list[str] = []
    proposed_commands: list[dict[str, Any]] = []

    if issue["state"] != "OPEN":
        blocked_reasons.append("issue-not-open")
    if classification != "ready_candidate":
        blocked_reasons.append(f"readiness-{classification}")

    if blocked_reasons:
        status = "blocked"
    elif "agent:ready" in labels and issue["project_status"] == READY_STATUS:
        status = "already_ready"
    else:
        status = "ready_candidate"
        if "agent:ready" not in labels:
            proposed_commands.append({
                "name": "add_agent_ready_label",
                "argv": [
                    "gh",
                    "issue",
                    "edit",
                    str(issue["number"]),
                    "--repo",
                    repo,
                    "--add-label",
                    "agent:ready",
                ],
                "reason": "strict readiness validation passed and issue lacks pickup label",
            })
        if issue["project_status"] != READY_STATUS:
            proposed_commands.append({
                "name": "set_project_ready",
                "argv": [
                    "python3",
                    "scripts/reconcile_project_status.py",
                    "--repo",
                    repo,
                    "--issue",
                    str(issue["number"]),
                    "--status",
                    READY_STATUS,
                ],
                "reason": "Project status is a projection and should match Ready label state",
            })

    return {
        "issue_number": issue["number"],
        "title": issue.get("title"),
        "state": issue["state"],
        "labels": labels,
        "project_status": issue["project_status"],
        "readiness_classification": classification,
        "readiness_report": asdict(readiness),
        "status": status,
        "blocked_reasons": blocked_reasons,
        "proposed_commands": proposed_commands,
        "github_mutations": [
            command for command in proposed_commands
            if command["argv"][:3] == ["gh", "issue", "edit"]
        ],
        "project_mutations": [
            command for command in proposed_commands
            if command["argv"][:2] == ["python3", "scripts/reconcile_project_status.py"]
        ],
    }


def _subprocess_runner(argv: Sequence[str]) -> Mapping[str, Any]:
    completed = subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "returncode": completed.returncode,
        "ok": completed.returncode == 0,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _normalize_issue(issue: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(issue, Mapping):
        raise ReadyRepairBatchError("issue entries must be objects")
    number = issue.get("number", issue.get("issue_number"))
    if isinstance(number, str) and number.isdigit():
        number = int(number)
    if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
        raise ReadyRepairBatchError("issue number must be a positive integer")
    body = issue.get("body")
    if not isinstance(body, str):
        raise ReadyRepairBatchError(f"issue {number} body must be a string")
    return {
        "number": number,
        "title": _optional_string(issue.get("title")),
        "body": body,
        "state": _string(issue.get("state", "OPEN"), "state").upper(),
        "labels": _labels(issue.get("labels", [])),
        "project_status": _project_status(issue),
    }


def _project_status(issue: Mapping[str, Any]) -> str | None:
    explicit = issue.get("project_status", issue.get("status"))
    if explicit is not None:
        return _string(explicit, "project_status")
    project_items = issue.get("projectItems", issue.get("project_items", []))
    if not isinstance(project_items, list):
        raise ReadyRepairBatchError("projectItems must be a list when supplied")
    fallback_status = None
    for item in project_items:
        if not isinstance(item, Mapping):
            continue
        status = item.get("status")
        name = None
        if isinstance(status, Mapping):
            name = status.get("name")
        elif isinstance(status, str):
            name = status
        if name is None:
            continue
        normalized = _string(name, "project_status")
        if item.get("title") == PROJECT_TITLE:
            return normalized
        fallback_status = fallback_status or normalized
    return fallback_status


def _labels(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        raise ReadyRepairBatchError("labels must be a list")
    labels: list[str] = []
    for item in raw:
        if isinstance(item, Mapping):
            item = item.get("name")
        labels.append(_string(item, "labels"))
    return sorted(set(labels))


def _normalize_repo(value: str) -> str:
    repo = _string(value, "repo")
    if "/" not in repo:
        raise ReadyRepairBatchError("repo must be in owner/name form")
    return repo


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReadyRepairBatchError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    return _string(value, "optional string")


__all__ = [
    "ReadyRepairBatchError",
    "SCHEMA_VERSION",
    "build_ready_repair_batch",
]
