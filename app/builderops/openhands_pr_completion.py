"""Fail-closed PR evidence seam for an upstream automation caller.

Inputs are fresh, secret-free observations supplied by the caller. This module
reserves requests; it does not discover PRs, run agents, or execute merges.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, TypedDict

from app.builderops.epic_run_state import update_epic_run_state

REPOSITORY = "RasmusTho/agentic-pkm-mvp"


class Decision(TypedDict):
    number: int
    identity: str
    action: str
    reason: str
    operation_id: str | None
    route: str


def _digest(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(data.encode()).hexdigest()


def work_identity(pr: Mapping[str, Any]) -> str:
    """Hash the current repository, code and relevant observed contract state."""
    contract = {key: pr[key] for key in (
        "repository", "number", "head_sha", "body", "draft", "labels",
        "base_ref", "base_sha", "governing_issue", "reviews", "verification",
    )}
    contract["labels"] = sorted(contract["labels"])
    return _digest(contract)


def intake(prs: list[Mapping[str, Any]], *, run_id: str, root: Path | str) -> list[Decision]:
    """Return one decision per open PR, atomically recording waits and requests.

    The caller must supply all fields below, including explicit evidence states.
    ``effect_outcomes`` maps prior operation IDs to independently reconciled
    ``completed`` or ``no_effect``; missing or unknown outcomes remain unresolved.
    The caller must bind successful review evidence to ``work_identity`` and
    supply repository acceptance Verify evidence and current CI independently.
    A dispatch is a request to the named external boundary, never an execution.
    """
    required = {"repository", "number", "state", "head_repository", "head_sha", "body",
                "draft", "labels", "base_ref", "base_sha", "governing_issue", "reviews",
                "verification", "restrictions", "owner", "route", "effect_outcome", "ci",
                "verify_evidence", "review_outcome", "independent_review_identity",
                "closure_authorized", "effect_outcomes"}
    decisions: list[Decision] = []
    for pr in prs:
        if not required <= pr.keys():
            raise ValueError("incomplete PR observation: " + ", ".join(sorted(required - pr.keys())))
        if pr["repository"] != REPOSITORY or type(pr["number"]) is not int or pr["number"] <= 0:
            raise ValueError("invalid repository or PR number")
        if pr["state"] != "open":
            continue
        if (not isinstance(pr["labels"], list) or not all(isinstance(x, str) for x in pr["labels"])
                or not isinstance(pr["governing_issue"], dict)
                or not {"body", "state"} <= pr["governing_issue"].keys()
                or not isinstance(pr["restrictions"], list) or not isinstance(pr["effect_outcomes"], dict)
                or not isinstance(pr["reviews"], list) or not isinstance(pr["verification"], dict)
                or type(pr["draft"]) is not bool or not isinstance(pr["body"], str)
                or not all(isinstance(pr[k], str) and pr[k] for k in ("head_sha", "base_ref", "base_sha"))):
            raise ValueError("invalid PR contract observation")
        identity = work_identity(pr)
        route = pr["route"]
        if route not in ("native", "executor", "fenced"):
            raise ValueError("unknown delivery route")
        result: Decision = {"number": pr["number"], "identity": identity, "action": "wait",
                            "reason": "", "operation_id": None, "route": route}
        labels = {label.strip().lower() for label in pr["labels"]}
        holds = {"wip", "work in progress", "do-not-merge", "do not merge", "agent:blocked",
                 "agent:needs-human", "agent:needs-review", "hold"}
        request = None
        if pr["draft"] or labels & holds or pr["restrictions"]:
            result["reason"] = "explicit hold or restriction"
        elif pr["head_repository"] != REPOSITORY:
            result["reason"] = "foreign head requires owner handoff"
        elif route != "native":
            result["reason"] = "executor or fenced route requires owning workflow"
        elif pr["effect_outcome"] != "none":
            result["reason"] = "existing or unknown effect requires reconciliation"
        elif pr["review_outcome"] == "unknown":
            result["reason"] = "review outcome unknown"
        elif pr["review_outcome"] == "changes_requested":
            result["reason"] = "review repair belongs to current owner"
        elif pr["review_outcome"] == "missing" or (
            pr["review_outcome"] == "pass" and pr["independent_review_identity"] != identity
        ):
            request = "independent-review"
        elif pr["review_outcome"] != "pass":
            result["reason"] = "review outcome unknown"
        elif pr["owner"] != "none":
            result["reason"] = "active or unknown writable owner"
        elif pr["verify_evidence"] == "missing":
            request = "repository-verification"
        elif pr["verify_evidence"] != "pass":
            result["reason"] = "repository acceptance Verify evidence failed or unknown"
        elif pr["ci"] != "success":
            result["reason"] = "CI pending, failed, or unknown"
        elif pr["closure_authorized"] is not True:
            result["reason"] = "verification-and-closure authorization missing"
        else:
            request = "verification-and-closure"

        def record(state: dict[str, Any]) -> dict[str, Any]:
            records = state["dispatch_decisions"]
            operations = [r for r in records if isinstance(r, dict)
                          and r.get("kind") == "openhands_pr_completion"
                          and r.get("repository") == REPOSITORY and r.get("number") == pr["number"]
                          and r.get("operation_id")]
            for op in operations:
                outcome = pr["effect_outcomes"].get(op["operation_id"])
                if outcome in ("completed", "no_effect"):
                    op["outcome"] = outcome
            if request:
                operation_id = "pr-completion-" + _digest({"identity": identity, "action": request, "route": route})
                unresolved = next((op for op in operations if op.get("outcome") not in ("completed", "no_effect")), None)
                previous = next((op for op in operations if op["operation_id"] == operation_id), None)
                if unresolved or previous:
                    op = unresolved or previous
                    result.update(action="reconcile", operation_id=op["operation_id"],
                                  reason="reconcile existing reservation before replacement")
                else:
                    records.append({"kind": "openhands_pr_completion", "operation_id": operation_id,
                                    "repository": REPOSITORY, "number": pr["number"], "identity": identity,
                                    "route": route, "request": request, "outcome": "unknown"})
                    result.update(action=request, operation_id=operation_id, reason="request reserved")
            if result["action"] == "wait":
                wait = {"kind": "openhands_pr_wait", "repository": REPOSITORY, "number": pr["number"],
                        "identity": identity, "route": route, "reason": result["reason"]}
                if wait not in records:
                    records.append(wait)
            return state

        update_epic_run_state(run_id, root=root, updater=record)
        decisions.append(result)
    return decisions
