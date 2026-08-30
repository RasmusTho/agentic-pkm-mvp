"""Canonical next-action classification for non-active GitHub Issues.

This is deliberately a pure, read-only projection.  It never claims work or
changes an Issue's lifecycle state; callers that mutate labels must provide
their own bounded, auditable write boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
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
        item = {
            "issue_number": issue.get("number"), "title": issue.get("title"),
            "state": issue.get("state", "open"), "action": verdict.action,
            "owner": issue.get("blocker_action", {}).get("owner") if isinstance(issue.get("blocker_action"), dict) else None,
            "next_action": issue.get("blocker_action", {}).get("next_action") if isinstance(issue.get("blocker_action"), dict) else None,
            "claim_posture": "read-only; never claims implementation work",
        }
        if verdict.errors:
            item["errors"] = list(verdict.errors)
            drift.append(item)
        elif verdict.action:
            queues[verdict.action].append(item)
    return {"schema": "blocker_action_intake.v1", "claim_posture": "read-only; never claims implementation work", "queues": queues, "drift": drift}
