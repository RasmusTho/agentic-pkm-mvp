"""Dry-run lifecycle transition planning for epic runner issue/PR flows."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1
PROJECT_TITLE = "Agent Delivery Control Plane"
VALID_TRANSITIONS = {"claim", "review", "done"}
AGENT_LABEL_PREFIX = "agent:"
TERMINAL_CHECK_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}


class EpicLifecyclePlanError(ValueError):
    """Raised when lifecycle planning input is invalid."""


def build_lifecycle_transition_plan(
    *,
    transition: str,
    issue: Mapping[str, Any],
    pull_request: Mapping[str, Any] | None = None,
    checks: Iterable[Mapping[str, Any]] = (),
    actor: str | None = None,
    repo: str = "OWNER/REPO",
) -> dict[str, Any]:
    """Build a deterministic dry-run plan for common issue/PR lifecycle flows.

    The plan describes reads and explicit commands a caller may execute later.
    It never calls GitHub, mutates Project state, writes dispatcher leases, or
    spawns agents.
    """

    normalized_transition = _normalize_transition(transition)
    normalized_issue = _normalize_issue(issue)
    normalized_pr = _normalize_pr(pull_request) if pull_request is not None else None
    normalized_checks = [_normalize_check(item) for item in checks]
    normalized_actor = _normalize_optional_string(actor)
    normalized_repo = _normalize_repo(repo)

    plan = _empty_plan(
        transition=normalized_transition,
        issue=normalized_issue,
        pull_request=normalized_pr,
        checks=normalized_checks,
        actor=normalized_actor,
        repo=normalized_repo,
    )

    if normalized_transition == "claim":
        _plan_claim(plan, normalized_issue, actor=normalized_actor, repo=normalized_repo)
    elif normalized_transition == "review":
        _plan_review(plan, normalized_issue, normalized_pr, repo=normalized_repo)
    elif normalized_transition == "done":
        _plan_done(
            plan,
            normalized_issue,
            normalized_pr,
            checks=normalized_checks,
            repo=normalized_repo,
        )

    plan["summary"] = _summary(plan)
    return plan


def _empty_plan(
    *,
    transition: str,
    issue: Mapping[str, Any],
    pull_request: Mapping[str, Any] | None,
    checks: list[Mapping[str, Any]],
    actor: str | None,
    repo: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "transition": transition,
        "dry_run": True,
        "repo": repo,
        "actor": actor,
        "content": {
            "issue": {
                "number": issue["number"],
                "state": issue["state"],
                "labels": issue["labels"],
                "project_status": issue["project_status"],
            },
            "pull_request": (
                {
                    "number": pull_request["number"],
                    "state": pull_request["state"],
                    "is_draft": pull_request["is_draft"],
                    "merged": pull_request["merged"],
                    "project_status": pull_request["project_status"],
                }
                if pull_request is not None
                else None
            ),
            "checks": checks,
        },
        "authority_order": [
            "github_issue_state_and_labels",
            "github_pr_state",
            "ci_checks",
            "github_project_projection",
            "dispatcher_run_state",
        ],
        "required_reads": [],
        "proposed_writes": {
            "issue_labels": [],
            "issue_project_status": [],
            "pr_project_status": [],
            "pr_state": [],
            "dispatcher_leases": [],
            "agent_spawns": [],
        },
        "verification_reads": [],
        "blocked_reasons": [],
        "authority_notes": [
            "GitHub Issue/PR/CI truth outranks Project status when they disagree.",
            "Project status changes in this plan are projection corrections only.",
        ],
        "github_mutations": [],
        "project_mutations": [],
        "dispatcher_mutations": [],
        "agent_spawns": [],
        "source": "builderops.epic_lifecycle_plan.dry_run",
    }


def _plan_claim(
    plan: dict[str, Any],
    issue: Mapping[str, Any],
    *,
    actor: str | None,
    repo: str,
) -> None:
    issue_number = issue["number"]
    _add_read(
        plan,
        "read_issue_claim_state",
        f"gh issue view {issue_number} --json state,labels,assignees,projectItems",
    )

    if issue["state"] != "OPEN":
        plan["blocked_reasons"].append("issue-not-open")
        return

    labels = set(issue["labels"])
    if "agent:ready" in labels:
        _add_write(
            plan,
            "issue_labels",
            action="remove_label",
            target=f"issue:{issue_number}",
            value="agent:ready",
            command=f"gh issue edit {issue_number} --remove-label agent:ready",
            reason="fast claim removes pickup eligibility before local edits",
        )
    else:
        plan["authority_notes"].append(
            "Issue has no agent:ready label; claim planning treats the current issue "
            "state as harder truth."
        )

    if actor and actor not in issue["assignees"]:
        _add_write(
            plan,
            "issue_labels",
            action="assign",
            target=f"issue:{issue_number}",
            value=actor,
            command=f"gh issue edit {issue_number} --add-assignee {actor}",
            reason="make the active implementer visible on the Issue",
        )

    _plan_project_status(
        plan,
        bucket="issue_project_status",
        target=f"issue:{issue_number}",
        current=issue["project_status"],
        desired="In Progress",
        command=(
            "gh api graphql -f projectId=$PROJECT_ID -f itemId=$ISSUE_ITEM_ID "
            "-f fieldId=$STATUS_FIELD_ID -f optionId=$IN_PROGRESS_OPTION_ID "
            "-f query='mutation(...)'"
        ),
        reason="active implementation must not remain projected as Ready",
    )
    _add_verify(
        plan,
        "verify_issue_claim_projection",
        f"gh issue view {issue_number} --json labels,projectItems",
    )


def _plan_review(
    plan: dict[str, Any],
    issue: Mapping[str, Any],
    pull_request: Mapping[str, Any] | None,
    *,
    repo: str,
) -> None:
    issue_number = issue["number"]
    _add_read(
        plan,
        "read_issue_review_state",
        f"gh issue view {issue_number} --json state,labels,projectItems",
    )
    if pull_request is None:
        plan["blocked_reasons"].append("missing-pull-request")
        return

    pr_number = pull_request["number"]
    _add_read(
        plan,
        "read_pr_review_state",
        f"gh pr view {pr_number} --json state,isDraft,reviewRequests,projectItems",
    )

    if issue["state"] != "OPEN":
        plan["blocked_reasons"].append("issue-not-open")
    if pull_request["state"] != "OPEN":
        plan["blocked_reasons"].append("pr-not-open")
    if pull_request["is_draft"]:
        _add_write(
            plan,
            "pr_state",
            action="mark_ready_for_review",
            target=f"pr:{pr_number}",
            value="ready_for_review",
            command=f"gh pr ready {pr_number}",
            reason="review handoff requires a non-draft PR artifact",
        )

    if plan["blocked_reasons"]:
        return

    _plan_project_status(
        plan,
        bucket="issue_project_status",
        target=f"issue:{issue_number}",
        current=issue["project_status"],
        desired="Review",
        command=_project_status_command("ISSUE_ITEM_ID", "REVIEW_OPTION_ID"),
        reason="issue enters review only at explicit PR handoff",
    )
    _plan_project_status(
        plan,
        bucket="pr_project_status",
        target=f"pr:{pr_number}",
        current=pull_request["project_status"],
        desired="Review",
        command=_project_status_command("PR_ITEM_ID", "REVIEW_OPTION_ID"),
        reason="open non-draft PR is the review handoff projection",
    )
    _add_verify(
        plan,
        "verify_issue_review_projection",
        f"gh issue view {issue_number} --json projectItems",
    )
    _add_verify(plan, "verify_pr_review_projection", f"gh pr view {pr_number} --json projectItems")


def _plan_done(
    plan: dict[str, Any],
    issue: Mapping[str, Any],
    pull_request: Mapping[str, Any] | None,
    *,
    checks: list[Mapping[str, Any]],
    repo: str,
) -> None:
    issue_number = issue["number"]
    _add_read(
        plan,
        "read_issue_terminal_state",
        f"gh issue view {issue_number} --json state,labels,projectItems,closedAt",
    )

    pr_terminal = False
    if pull_request is not None:
        pr_number = pull_request["number"]
        pr_terminal = pull_request["merged"] or pull_request["state"] == "CLOSED"
        _add_read(
            plan,
            "read_pr_terminal_state",
            f"gh pr view {pr_number} --json state,mergedAt,isDraft,projectItems,headRefOid",
        )
        _add_read(
            plan,
            "read_pr_terminal_checks",
            f"gh api repos/{repo}/commits/$PR_HEAD_SHA/check-runs",
        )
    else:
        plan["authority_notes"].append("No PR supplied; done planning uses Issue state only.")

    check_verdict = _check_verdict(checks)
    issue_terminal = issue["state"] == "CLOSED"
    if check_verdict == "failed":
        plan["blocked_reasons"].append("ci-checks-not-green")
    elif check_verdict == "unknown":
        plan["authority_notes"].append(
            "CI checks were not supplied; terminal checks remain required reads."
        )

    for label in issue["labels"]:
        if label.startswith(AGENT_LABEL_PREFIX):
            _add_write(
                plan,
                "issue_labels",
                action="remove_label",
                target=f"issue:{issue_number}",
                value=label,
                command=f"gh issue edit {issue_number} --remove-label {label}",
                reason="terminal work must not retain active agent labels",
            )

    terminal_projection_allowed = check_verdict != "failed"

    if issue_terminal and terminal_projection_allowed:
        _plan_project_status(
            plan,
            bucket="issue_project_status",
            target=f"issue:{issue_number}",
            current=issue["project_status"],
            desired="Done",
            command=_project_status_command("ISSUE_ITEM_ID", "DONE_OPTION_ID"),
            reason="closed Issue is terminal GitHub truth",
        )
    elif pr_terminal:
        plan["blocked_reasons"].append("issue-not-closed")
        plan["authority_notes"].append(
            "A terminal PR does not by itself close the Issue; verification-and-closure owns issue closure."
        )

    if pull_request is not None and pr_terminal and terminal_projection_allowed:
        _plan_project_status(
            plan,
            bucket="pr_project_status",
            target=f"pr:{pull_request['number']}",
            current=pull_request["project_status"],
            desired="Done",
            command=_project_status_command("PR_ITEM_ID", "DONE_OPTION_ID"),
            reason="merged or closed PR is terminal GitHub truth",
        )
    elif pull_request is not None:
        plan["blocked_reasons"].append("pr-not-terminal")

    _add_verify(
        plan,
        "verify_issue_done_projection",
        f"gh issue view {issue_number} --json labels,projectItems,state",
    )
    if pull_request is not None:
        _add_verify(
            plan,
            "verify_pr_done_projection",
            f"gh pr view {pull_request['number']} --json projectItems,state,mergedAt",
        )


def _plan_project_status(
    plan: dict[str, Any],
    *,
    bucket: str,
    target: str,
    current: str | None,
    desired: str,
    command: str,
    reason: str,
) -> None:
    if current == desired:
        return
    if current is None:
        _add_write(
            plan,
            bucket,
            action="add_to_project",
            target=target,
            value=PROJECT_TITLE,
            command=(
                "gh api graphql -f projectId=$PROJECT_ID -f contentId=$CONTENT_ID "
                "-f query='mutation(...)'"
            ),
            reason=f"{target} is missing from the Project projection",
        )
    _add_write(
        plan,
        bucket,
        action="set_status",
        target=target,
        value=desired,
        command=command,
        reason=reason,
    )


def _add_read(plan: dict[str, Any], name: str, command: str) -> None:
    plan["required_reads"].append({"name": name, "command": command})


def _add_verify(plan: dict[str, Any], name: str, command: str) -> None:
    plan["verification_reads"].append({"name": name, "command": command})


def _add_write(
    plan: dict[str, Any],
    bucket: str,
    *,
    action: str,
    target: str,
    value: str,
    command: str,
    reason: str,
) -> None:
    plan["proposed_writes"][bucket].append(
        {
            "action": action,
            "target": target,
            "value": value,
            "command": command,
            "reason": reason,
            "execute": False,
        }
    )


def _project_status_command(item_var: str, option_var: str) -> str:
    return (
        f"gh api graphql -f projectId=$PROJECT_ID -f itemId=${item_var} "
        f"-f fieldId=$STATUS_FIELD_ID -f optionId=${option_var} "
        "-f query='mutation(...)'"
    )


def _summary(plan: Mapping[str, Any]) -> dict[str, Any]:
    write_count = sum(len(items) for items in plan["proposed_writes"].values())
    return {
        "planned_write_count": write_count,
        "blocked": bool(plan["blocked_reasons"]),
        "no_mutations_performed": True,
    }


def _check_verdict(checks: list[Mapping[str, Any]]) -> str:
    if not checks:
        return "unknown"
    for check in checks:
        status = check.get("status")
        conclusion = check.get("conclusion")
        if status and status != "COMPLETED":
            return "failed"
        if conclusion and conclusion not in TERMINAL_CHECK_CONCLUSIONS:
            return "failed"
    return "passed"


def _normalize_transition(value: str) -> str:
    normalized = _normalize_string(value, "transition").lower().replace("_", "-")
    aliases = {
        "review-handoff": "review",
        "terminal": "done",
        "terminal-projection": "done",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in VALID_TRANSITIONS:
        raise EpicLifecyclePlanError(
            f"transition must be one of {sorted(VALID_TRANSITIONS)}"
        )
    return normalized


def _normalize_issue(issue: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(issue, Mapping):
        raise EpicLifecyclePlanError("issue must be an object")
    return {
        "number": _normalize_positive_int(issue.get("number", issue.get("issue_number")), "issue"),
        "state": _normalize_state(issue.get("state", "OPEN")),
        "labels": _normalize_labels(issue.get("labels", [])),
        "assignees": _normalize_logins(issue.get("assignees", []), "assignees"),
        "project_status": _project_status(issue),
    }


def _normalize_pr(pull_request: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(pull_request, Mapping):
        raise EpicLifecyclePlanError("pull_request must be an object")
    return {
        "number": _normalize_positive_int(
            pull_request.get("number", pull_request.get("pr_number")),
            "pull_request",
        ),
        "state": _normalize_state(pull_request.get("state", "OPEN")),
        "is_draft": bool(
            pull_request.get(
                "is_draft",
                pull_request.get("isDraft", pull_request.get("draft", False)),
            )
        ),
        "merged": bool(pull_request.get("merged", False) or pull_request.get("mergedAt")),
        "project_status": _project_status(pull_request),
    }


def _normalize_check(check: Mapping[str, Any]) -> dict[str, str | None]:
    if not isinstance(check, Mapping):
        raise EpicLifecyclePlanError("checks must contain objects")
    status = check.get("status")
    conclusion = check.get("conclusion")
    name = check.get("name")
    return {
        "name": str(name) if name is not None else None,
        "status": str(status).upper() if status is not None else None,
        "conclusion": str(conclusion).upper() if conclusion is not None else None,
    }


def _project_status(content: Mapping[str, Any]) -> str | None:
    explicit = content.get("project_status", content.get("status"))
    if explicit is not None:
        return _normalize_string(explicit, "project_status")
    project_items = content.get("projectItems", content.get("project_items", []))
    if not isinstance(project_items, list):
        raise EpicLifecyclePlanError("projectItems must be a list when supplied")
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
        if item.get("title") == PROJECT_TITLE:
            return _normalize_string(name, "project_status")
        fallback_status = fallback_status or _normalize_string(name, "project_status")
    return fallback_status


def _normalize_labels(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise EpicLifecyclePlanError("labels must be a list")
    labels: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            item = item.get("name")
        labels.append(_normalize_string(item, "labels"))
    return sorted(set(labels))


def _normalize_logins(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise EpicLifecyclePlanError(f"{field} must be a list")
    logins: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            item = item.get("login")
        logins.append(_normalize_string(item, field))
    return sorted(set(logins))


def _normalize_state(value: Any) -> str:
    return _normalize_string(value, "state").upper()


def _normalize_positive_int(value: Any, field: str) -> int:
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EpicLifecyclePlanError(f"{field} number must be a positive integer")
    return value


def _normalize_repo(value: str) -> str:
    repo = _normalize_string(value, "repo")
    if "/" not in repo:
        raise EpicLifecyclePlanError("repo must be in owner/name form")
    return repo


def _normalize_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EpicLifecyclePlanError(f"{field} must be a non-empty string")
    return value.strip()


def _normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    return _normalize_string(value, "optional string")


__all__ = [
    "EpicLifecyclePlanError",
    "SCHEMA_VERSION",
    "build_lifecycle_transition_plan",
]
