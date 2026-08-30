"""Canonical next-action classification for non-active GitHub Issues.

This is deliberately a pure, read-only projection.  It never claims work or
changes an Issue's lifecycle state; callers that mutate labels must provide
their own bounded, auditable write boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Iterable

BLOCKED_ACTIONS = frozenset({
    "action:repair-contract", "action:wait-dependency", "action:restore-environment",
    "action:wait-external", "action:review-at",
})
HUMAN_ACTIONS = frozenset({
    "action:human-decision", "action:human-authorization", "action:human-access",
    "action:human-operation", "action:human-acceptance",
})
ACTION_LABELS = BLOCKED_ACTIONS | HUMAN_ACTIONS
LEGACY_HUMAN_ACTIONS = {
    "human:decision": "action:human-decision",
    "human:authorize": "action:human-authorization",
    "human:access": "action:human-access",
    "human:operator": "action:human-operation",
    "human:acceptance": "action:human-acceptance",
}

RECEIPT_FIELDS = ("action", "owner", "next_action", "unblocks_when", "dependency_refs", "review_at", "last_verified_at")
_EXTERNAL_OWNER = re.compile(r"external:[a-z0-9][a-z0-9._-]*\Z")


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _valid_owner(value: object) -> bool:
    return value in {"builder", "owner"} or (
        isinstance(value, str) and _EXTERNAL_OWNER.fullmatch(value) is not None
    )


def parse_blocker_action_receipt(comment: object) -> dict[str, object] | None:
    """Parse the deliberately small YAML receipt subset from one REST comment."""
    body = comment.get("body", "") if isinstance(comment, dict) else str(comment)
    if "receipt: blocker_action.v1" not in body:
        return None
    values: dict[str, object] = {"dependency_refs": []}
    for line in body.splitlines():
        if ":" not in line:
            continue
        key, value = line.strip().split(":", 1)
        if key in RECEIPT_FIELDS or key == "receipt":
            values[key] = value.strip()
    if values.get("dependency_refs") == "[]":
        values["dependency_refs"] = []
    action = values.get("action")
    if action not in ACTION_LABELS or not _valid_owner(values.get("owner")) or any(not isinstance(values.get(key), str) or not values[key] for key in ("next_action", "unblocks_when")) or not _valid_timestamp(values.get("last_verified_at")):
        return None
    return values


def latest_receipt(comments: Iterable[object]) -> dict[str, object] | None:
    receipts = [receipt for item in comments if (receipt := parse_blocker_action_receipt(item))]
    return receipts[-1] if receipts else None


def receipt_for_action(action: str, *, now: datetime | None = None) -> dict[str, object]:
    """Produce a valid, explicit maintenance receipt without inventing cause."""
    if action not in ACTION_LABELS:
        raise ValueError(f"unknown blocker action: {action}")
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {"receipt": "blocker_action.v1", "action": action, "owner": "builder", "next_action": "verify and repair the live Issue contract before pickup", "unblocks_when": "fresh authority evidence establishes a valid transition", "dependency_refs": [], "review_at": "null", "last_verified_at": stamp}


def label_names(issue: dict[str, Any]) -> set[str]:
    return {str(item.get("name") if isinstance(item, dict) else item) for item in issue.get("labels", [])}


@dataclass(frozen=True)
class ActionVerdict:
    action: str | None
    errors: tuple[str, ...]


def classify(labels: Iterable[str], *, open_issue: bool = True) -> ActionVerdict:
    labels = set(labels)
    actions = sorted(labels & ACTION_LABELS)
    lifecycle = labels & {"agent:blocked", "agent:needs-human"}
    if not open_issue:
        return ActionVerdict(None, () if not actions else ("terminal_issue_has_action_label",))
    if len(lifecycle) != 1:
        return ActionVerdict(None, () if not actions else ("action_without_blocker_lifecycle",))
    if len(actions) != 1:
        return ActionVerdict(None, ("missing_action_label" if not actions else "multiple_action_labels",))
    action = actions[0]
    if "agent:blocked" in lifecycle and action not in BLOCKED_ACTIONS:
        return ActionVerdict(action, ("blocked_requires_blocked_action",))
    if "agent:needs-human" in lifecycle and action not in HUMAN_ACTIONS:
        return ActionVerdict(action, ("needs_human_requires_human_action",))
    return ActionVerdict(action, ())


def intake(issues: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return deterministic non-claim queues for supplied REST Issue objects."""
    queues: dict[str, list[dict[str, Any]]] = {action: [] for action in sorted(ACTION_LABELS)}
    drift: list[dict[str, Any]] = []
    for issue in issues:
        labels = label_names(issue)
        if not labels & {"agent:blocked", "agent:needs-human"}:
            continue
        verdict = classify(labels, open_issue=str(issue.get("state", "open")).lower() == "open")
        receipt = latest_receipt(issue.get("comments", []))
        item = {
            "issue_number": issue.get("number"), "title": issue.get("title"),
            "state": issue.get("state", "open"), "action": verdict.action,
            "owner": receipt.get("owner") if receipt else None,
            "next_action": receipt.get("next_action") if receipt else None,
            "receipt_freshness": receipt.get("last_verified_at") if receipt else None,
            "claim_posture": "read-only; never claims implementation work",
        }
        if verdict.errors or receipt is None:
            if receipt is None:
                item.setdefault("errors", []).append("missing_or_invalid_blocker_action_receipt")
            item["errors"] = list(verdict.errors)
            if receipt is None:
                item["errors"].append("missing_or_invalid_blocker_action_receipt")
            drift.append(item)
        elif verdict.action:
            queues[verdict.action].append(item)
    return {"schema": "blocker_action_intake.v1", "claim_posture": "read-only; never claims implementation work", "queues": queues, "drift": drift}
