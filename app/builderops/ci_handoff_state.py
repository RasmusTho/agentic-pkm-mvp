"""PR CI monitor handoff records for epic runner coordination."""

from __future__ import annotations

from datetime import datetime, timezone
from collections.abc import Iterable, Mapping
from typing import Any

from app.builderops.epic_run_state import apply_epic_run_update

TERMINAL_GREEN_CONCLUSIONS = frozenset({"success", "skipped", "neutral"})


class CiHandoffStateError(ValueError):
    """Raised when a CI handoff record or resume input is invalid."""


def build_ci_pending_handoff(
    *,
    pr_number: int,
    head_sha: str,
    local_validation: Iterable[str],
    review_state: str,
    pending_checks: Iterable[Mapping[str, Any]] = (),
    next_closure_action: str,
    issue_number: int | None = None,
    repo: str | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Build a normalized CI-pending handoff record.

    The record is coordination evidence only. Closure still has to re-read the
    live PR head and check state before merge or terminal issue projection.
    """

    normalized_pr = _positive_int(pr_number, "pr_number")
    normalized_head = _required_string(head_sha, "head_sha")
    return {
        "id": f"ci-handoff-pr-{normalized_pr}",
        "status": "ci_pending",
        "repo": _optional_string(repo, "repo"),
        "issue_number": (
            _positive_int(issue_number, "issue_number")
            if issue_number is not None
            else None
        ),
        "pr_number": normalized_pr,
        "head_sha": normalized_head,
        "local_validation": _string_list(local_validation, "local_validation"),
        "review_state": _required_string(review_state, "review_state"),
        "pending_checks": [_normalize_check(item) for item in pending_checks],
        "next_closure_action": _required_string(
            next_closure_action,
            "next_closure_action",
        ),
        "recorded_at": recorded_at or _utc_now(),
        "authority_boundary": (
            "coordination-evidence-only; re-read GitHub PR head and checks before closure"
        ),
    }


def record_ci_pending_handoff(
    state: Mapping[str, Any],
    handoff: Mapping[str, Any],
) -> dict[str, Any]:
    """Return run-state updated with one normalized CI handoff record."""

    normalized = normalize_ci_handoff(handoff)
    return apply_epic_run_update(state, ci_handoffs=[normalized])


def normalize_ci_handoff(handoff: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(handoff, Mapping):
        raise CiHandoffStateError("handoff must be an object")
    return build_ci_pending_handoff(
        pr_number=_positive_int(handoff.get("pr_number"), "pr_number"),
        head_sha=_required_string(handoff.get("head_sha"), "head_sha"),
        local_validation=handoff.get("local_validation", []),
        review_state=_required_string(handoff.get("review_state"), "review_state"),
        pending_checks=handoff.get("pending_checks", []),
        next_closure_action=_required_string(handoff.get("next_closure_action"), "next_closure_action"),
        issue_number=handoff.get("issue_number"),
        repo=handoff.get("repo"),
        recorded_at=handoff.get("recorded_at"),
    )


def plan_ci_handoff_resume(
    *,
    handoff: Mapping[str, Any],
    live_pr: Mapping[str, Any],
    checks: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Plan CI handoff closure from live PR/check evidence without merging."""

    normalized_handoff = normalize_ci_handoff(handoff)
    live_head = _extract_pr_head_sha(live_pr)
    normalized_checks = [_normalize_check(item) for item in checks]
    latest_checks = _latest_checks_by_name(normalized_checks)
    verdict = _checks_verdict(latest_checks)
    blocked_reasons: list[str] = []

    if live_head != normalized_handoff["head_sha"]:
        blocked_reasons.append("stale-head-sha")
    if verdict == "pending":
        blocked_reasons.append("ci-not-terminal")
    elif verdict == "failure":
        blocked_reasons.append("ci-not-green")

    closure_candidate = None
    if not blocked_reasons:
        closure_candidate = {
            "pr_number": normalized_handoff["pr_number"],
            "head_sha": live_head,
            "next_closure_action": normalized_handoff["next_closure_action"],
            "review_state": normalized_handoff["review_state"],
            "local_validation": normalized_handoff["local_validation"],
            "checks": latest_checks,
            "proposed_commands": [],
            "note": "CI is terminal green; caller must still perform explicit closure workflow.",
        }

    return {
        "ok": not blocked_reasons,
        "blocked": bool(blocked_reasons),
        "blocked_reasons": blocked_reasons,
        "handoff": normalized_handoff,
        "live_head_sha": live_head,
        "handoff_head_sha": normalized_handoff["head_sha"],
        "check_verdict": verdict,
        "closure_plan_candidate": closure_candidate,
        "required_reads": [
            "read_pr_current_head_sha",
            "read_pr_current_checks",
            "read_review_state",
        ],
        "mutations_performed": False,
        "authority_boundary": (
            "GitHub PR head/checks remain truth; handoff state cannot authorize merge"
        ),
    }


def find_ci_handoff(
    state: Mapping[str, Any],
    *,
    pr_number: int,
) -> dict[str, Any] | None:
    target = _positive_int(pr_number, "pr_number")
    for item in state.get("ci_handoffs", []):
        if isinstance(item, Mapping) and item.get("pr_number") == target:
            return normalize_ci_handoff(item)
    return None


def pending_check_summary(checks: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        item for item in _latest_checks_by_name(
            [_normalize_check(check) for check in checks]
        )
        if item["status"] != "completed"
    ]


def _latest_checks_by_name(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for check in checks:
        existing = latest.get(check["name"])
        if existing is None or _check_rank(check) >= _check_rank(existing):
            latest[check["name"]] = check
    return list(latest.values())


def _check_rank(check: Mapping[str, Any]) -> tuple[str, str]:
    return (
        str(check.get("started_at") or ""),
        str(check.get("id") or ""),
    )


def _checks_verdict(checks: list[dict[str, Any]]) -> str:
    if not checks:
        return "pending"
    for check in checks:
        if check["status"] != "completed":
            return "pending"
        if check["conclusion"] not in TERMINAL_GREEN_CONCLUSIONS:
            return "failure"
    return "green"


def _normalize_check(check: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(check, Mapping):
        raise CiHandoffStateError("checks must contain objects")
    name = _required_string(check.get("name"), "check.name")
    status = _required_string(check.get("status", "completed"), "check.status").lower()
    conclusion = check.get("conclusion")
    if conclusion is None or conclusion == "":
        conclusion = None
    else:
        conclusion = _required_string(conclusion, "check.conclusion").lower()
    normalized: dict[str, Any] = {
        "name": name,
        "status": status,
        "conclusion": conclusion,
    }
    check_id: object = check.get("id")
    if isinstance(check_id, (int, str)) and not isinstance(check_id, bool):
        normalized["id"] = check_id
    started_at = check.get("started_at", check.get("startedAt"))
    if isinstance(started_at, str) and started_at.strip():
        normalized["started_at"] = started_at.strip()
    return normalized


def _extract_pr_head_sha(live_pr: Mapping[str, Any]) -> str:
    if not isinstance(live_pr, Mapping):
        raise CiHandoffStateError("live_pr must be an object")
    for key in ("head_sha", "headRefOid"):
        value = live_pr.get(key)
        if value:
            return _required_string(value, key)
    head = live_pr.get("head")
    if isinstance(head, Mapping):
        value = head.get("sha")
        if value:
            return _required_string(value, "head.sha")
    raise CiHandoffStateError("live_pr head SHA is required")


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CiHandoffStateError(f"{field} must be a positive integer")
    return value


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CiHandoffStateError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, field)


def _string_list(values: Iterable[str], field: str) -> list[str]:
    if isinstance(values, str) or not isinstance(values, Iterable):
        raise CiHandoffStateError(f"{field} must be a list")
    normalized = [_required_string(item, f"{field}[]") for item in values]
    if not normalized:
        raise CiHandoffStateError(f"{field} must be a non-empty list")
    return normalized


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


__all__ = [
    "CiHandoffStateError",
    "build_ci_pending_handoff",
    "find_ci_handoff",
    "pending_check_summary",
    "plan_ci_handoff_resume",
    "record_ci_pending_handoff",
]
