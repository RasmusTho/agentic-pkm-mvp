"""Fail-closed PR evidence seam for an upstream automation caller.

Inputs are fresh, secret-free observations supplied by the caller. This module
reserves requests; it does not discover PRs, run agents, or execute merges.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
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
    # A peer merge moves base_sha without changing this PR's reviewed work.
    # The native merge procedure independently refreshes base and CI authority.
    contract = {key: pr[key] for key in (
        "repository", "number", "head_sha", "body", "draft", "labels",
        "base_ref", "governing_issue", "state", "head_repository",
        "restrictions", "route",
    )}
    for key in ("title", "check_config", "review_context"):
        if key in pr:
            contract[key] = pr[key]
    contract["labels"] = sorted(contract["labels"])
    return _digest(contract)


def _bound(value: Any, binding: str, *, key: str = "identity") -> bool:
    return (isinstance(value, dict) and value.get("status") == "pass"
            and value.get("trusted") is True and value.get(key) == binding
            and isinstance(value.get("ref"), str) and bool(value["ref"].strip()))


def _blocking_reviews(reviews: list[Any]) -> bool:
    """Interpret GitHub REST reviews; latest decisive review per user wins."""
    latest: dict[str, tuple[datetime, str]] = {}
    seen: set[tuple[str, datetime]] = set()
    for review in reviews:
        if not isinstance(review, dict) or not isinstance(review.get("user"), dict):
            raise ValueError("invalid review")
        login = review["user"].get("login")
        state = review.get("state")
        if not isinstance(login, str) or not login.strip() or state not in (
            "APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED", "PENDING"
        ):
            raise ValueError("invalid review")
        if state == "PENDING" and review.get("submitted_at") is None:
            continue
        submitted = review.get("submitted_at")
        if not isinstance(submitted, str):
            raise ValueError("invalid review timestamp")
        timestamp = datetime.fromisoformat(submitted.replace("Z", "+00:00"))
        if timestamp.utcoffset() is None:
            raise ValueError("invalid review timestamp")
        key = (login.casefold(), timestamp)
        if key in seen:
            raise ValueError("ambiguous review ordering")
        seen.add(key)
        if state in ("APPROVED", "CHANGES_REQUESTED"):
            previous = latest.get(key[0])
            if previous is None or timestamp > previous[0]:
                latest[key[0]] = (timestamp, state)
    return any(state == "CHANGES_REQUESTED" for _, state in latest.values())


def intake(prs: list[Mapping[str, Any]], *, run_id: str, root: Path | str,
           expected_run_id: str, expected_root: Path | str,
           expected_epic_issue_number: int) -> list[Decision]:
    """Return one decision per open PR, atomically recording waits and requests.

    The caller must supply all fields below, including explicit evidence states.
    ``effect_outcomes`` maps prior operation IDs to independently reconciled
    trusted receipts with ``completed`` or ``no_effect`` status; missing or unknown outcomes remain unresolved.
    The caller must bind successful review evidence to ``work_identity`` and
    supply repository acceptance Verify evidence and current CI independently.
    ``reviews`` contains GitHub REST review records with user.login, state and
    submitted_at. The latest APPROVED or CHANGES_REQUESTED per user is decisive;
    COMMENTED, PENDING and DISMISSED records are not decisive. A dismissed
    review must itself be supplied as DISMISSED. Malformed records fail closed.
    ``governing_issue`` requires a nonblank string body and a state of ``open``
    or ``closed`` (lowercase).
    ``expected_epic_issue_number`` is the configured governing epic; a run-state
    file owned by any other epic is refused before any reservation or mutation.
    A dispatch is a request to the named external boundary, never an execution.
    """
    if run_id != expected_run_id or Path(root).resolve() != Path(expected_root).resolve():
        raise ValueError("run does not match configured reservation authority")
    required = {"repository", "number", "state", "head_repository", "head_sha", "body",
                "draft", "labels", "base_ref", "base_sha", "governing_issue", "reviews",
                "verification", "restrictions", "owner", "route", "effect_outcome", "ci",
                "verify_evidence", "review_outcome", "independent_review_identity",
                "closure_authorized", "effect_outcomes"}
    decisions: list[Decision] = []
    for pr in prs:
        try:
            if not required <= pr.keys():
                raise ValueError("incomplete PR observation: " + ", ".join(sorted(required - pr.keys())))
            if pr["repository"] != REPOSITORY or type(pr["number"]) is not int or pr["number"] <= 0:
                raise ValueError("invalid repository or PR number")
            if pr["state"] != "open":
                continue
            if (not isinstance(pr["labels"], list) or not all(isinstance(x, str) for x in pr["labels"])
                    or not isinstance(pr["governing_issue"], dict)
                    or not {"body", "state"} <= pr["governing_issue"].keys()
                    or not isinstance(pr["governing_issue"]["body"], str)
                    or not pr["governing_issue"]["body"].strip()
                    or not isinstance(pr["governing_issue"]["state"], str)
                    or pr["governing_issue"]["state"] not in ("open", "closed")
                    or not isinstance(pr["restrictions"], list) or not isinstance(pr["effect_outcomes"], dict)
                    or not isinstance(pr["reviews"], list) or not isinstance(pr["verification"], dict)
                    or type(pr["draft"]) is not bool or not isinstance(pr["body"], str)
                    or not all(isinstance(pr[k], str) and pr[k] for k in ("head_sha", "base_ref", "base_sha"))):
                raise ValueError("invalid PR contract observation")
            identity = work_identity(pr)
            route = pr["route"]
            if route not in ("native", "executor", "fenced", "unknown"):
                raise ValueError("unknown delivery route")
            blocking_review = _blocking_reviews(pr["reviews"])
            _digest(pr)  # validate the complete observation before any reservation
        except (AttributeError, KeyError, TypeError, ValueError, RecursionError):
            number = pr.get("number", 0) if isinstance(pr, Mapping) else 0
            decisions.append({"number": number if type(number) is int else 0, "identity": "",
                              "action": "wait", "reason": "invalid PR observation",
                              "operation_id": None, "route": ""})
            continue
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
            result["reason"] = "executor, fenced or unverified route requires owning workflow"
        elif pr["effect_outcome"] != "none":
            result["reason"] = "existing or unknown effect requires reconciliation"
        elif blocking_review:
            result["reason"] = "review repair belongs to current owner"
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
        elif not _bound(pr["verify_evidence"], identity):
            result["reason"] = "repository acceptance Verify evidence failed or unknown"
        elif not _bound(pr["ci"], pr["head_sha"], key="head_sha"):
            result["reason"] = "CI pending, failed, or unknown"
        elif not _bound(pr["closure_authorized"], identity):
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
                if (op.get("outcome") not in ("completed", "no_effect")
                        and isinstance(outcome, dict) and outcome.get("status") in ("completed", "no_effect")
                        and outcome.get("trusted") is True and outcome.get("operation_id") == op["operation_id"]
                        and isinstance(outcome.get("ref"), str) and outcome["ref"].strip()):
                    op["outcome"] = outcome["status"]
            unresolved = next((op for op in operations if op.get("outcome") not in ("completed", "no_effect")), None)
            if unresolved:
                result["action"] = "reconcile"
                result["operation_id"] = unresolved["operation_id"]
                result["reason"] = "reconcile existing reservation before replacement"
            elif request:
                previous = [op for op in operations if op.get("identity") == identity and op.get("request") == request and op.get("route") == route]
                last = previous[-1] if previous else None
                retry = pr.get("retry_authorization")
                if last is not None and last.get("outcome") == "completed" and not (
                    isinstance(retry, dict) and _bound(retry, identity) and retry.get("operation_id") == last["operation_id"]
                ):
                    result["action"] = "reconcile"
                    result["operation_id"] = last["operation_id"]
                    result["reason"] = "completed request lacks results or authorized retry"
                else:
                    attempt = len(previous) + 1
                    operation_id = "pr-completion-" + _digest({"identity": identity, "action": request, "route": route, "attempt": attempt})
                    records.append({"kind": "openhands_pr_completion", "operation_id": operation_id,
                                    "repository": REPOSITORY, "number": pr["number"], "identity": identity,
                                    "route": route, "request": request, "attempt": attempt, "outcome": "unknown"})
                    result["action"] = request
                    result["operation_id"] = operation_id
                    result["reason"] = "request reserved"
            if result["action"] == "wait":
                wait = {"kind": "openhands_pr_wait", "repository": REPOSITORY, "number": pr["number"],
                        "identity": identity, "route": route, "reason": result["reason"]}
                if wait not in records:
                    records.append(wait)
            return state

        update_epic_run_state(
            run_id, root=root, updater=record,
            expected_epic_issue_number=expected_epic_issue_number,
        )
        decisions.append(result)
    return decisions
