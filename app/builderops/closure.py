"""Hash-bound, light-path-only GitHub closure adapter.

This module deliberately owns effect sequencing, not closure policy.  The
verification-and-closure skill remains the authority for deciding whether a PR
belongs on this path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.builderops.publication import CommandExecutor, CommandResult, SubprocessExecutor

PLAN_SCHEMA = "builder.closure-plan.v1"
RECEIPT_SCHEMA = "builder.closure-receipt.v1"
GITHUB_HOST = "github.com"
SHA_RE = re.compile(r"[0-9a-f]{40,64}\Z")
REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


class ClosureError(RuntimeError):
    def __init__(self, outcome: str, reason: str, result: CommandResult | None = None) -> None:
        super().__init__(reason)
        self.outcome, self.reason, self.result = outcome, reason, result


@dataclass(frozen=True)
class ClosureRequest:
    repository: str
    worktree: Path
    pr_number: int
    verify_evidence: Mapping[str, Any]
    dispatcher_task_id: str | None = None


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def closure_plan_hash(plan: Mapping[str, Any]) -> str:
    value = dict(plan)
    value.pop("plan_sha256", None)
    return _digest(value)


def _run(
    executor: CommandExecutor,
    cwd: Path,
    argv: Sequence[str],
    *,
    input_text: str | None = None,
) -> CommandResult:
    result = executor.run(argv, cwd=cwd, input_text=input_text)
    if result.returncode:
        raise ClosureError("command-failed", "closure command failed", result)
    return result


def _api(
    executor: CommandExecutor,
    cwd: Path,
    repository: str,
    method: str,
    endpoint: str,
    *fields: str,
    input_text: str | None = None,
) -> Any:
    result = _run(
        executor,
        cwd,
        ["gh", "api", "--hostname", GITHUB_HOST, "--method", method, f"repos/{repository}{endpoint}", *fields],
        input_text=input_text,
    )
    try:
        return json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError as exc:
        raise ClosureError("unknown", "GitHub readback was not JSON") from exc


def _pr(executor: CommandExecutor, cwd: Path, repository: str, number: int) -> dict[str, Any]:
    value = _api(executor, cwd, repository, "GET", f"/pulls/{number}")
    if not isinstance(value, dict) or value.get("number") != number:
        raise ClosureError("unknown", "PR readback was malformed")
    return value


def _issue(executor: CommandExecutor, cwd: Path, repository: str, number: int) -> dict[str, Any]:
    value = _api(executor, cwd, repository, "GET", f"/issues/{number}")
    if not isinstance(value, dict) or value.get("number") != number or "pull_request" in value:
        raise ClosureError("unknown", "Issue readback was malformed")
    return value


def _issue_hashes(issue: Mapping[str, Any]) -> dict[str, str]:
    title = issue.get("title")
    body = issue.get("body")
    if not isinstance(title, str) or (body is not None and not isinstance(body, str)):
        raise ClosureError("unknown", "Issue title/body readback was malformed")
    return {
        "title_sha256": hashlib.sha256(title.encode()).hexdigest(),
        "body_sha256": hashlib.sha256((body or "").encode()).hexdigest(),
    }


def _validate_planned_issue(
    issue: Mapping[str, Any], plan: Mapping[str, Any], *, phase: str
) -> None:
    planned = plan.get("closing_issue")
    if not isinstance(planned, Mapping) or issue.get("number") != planned.get("number"):
        raise ClosureError("drift", f"{phase} closing Issue identity drifted")
    if _issue_hashes(issue) != {
        "title_sha256": planned.get("title_sha256"),
        "body_sha256": planned.get("body_sha256"),
    }:
        raise ClosureError("drift", f"{phase} closing Issue title/body drifted")


def _issue_events(executor: CommandExecutor, cwd: Path, repository: str, number: int) -> list[dict[str, Any]]:
    value = _api(executor, cwd, repository, "GET", f"/issues/{number}/events", "-f", "per_page=100")
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ClosureError("unknown", "Issue event readback was malformed")
    return [dict(item) for item in value]


def _issue_number(body: str) -> int:
    governing = re.findall(r"(?m)^Governing-Issue:\s*#(\d+)\s*$", body)
    closing = re.findall(r"(?mi)^\s*(?:fixes|closes|resolves)\s+#(\d+)\s*$", body)
    if len(governing) != 1 or len(closing) != 1 or governing[0] != closing[0]:
        raise ClosureError("unsupported", "PR must have one exact governing and closing Issue")
    return int(governing[0])


def _checks(executor: CommandExecutor, cwd: Path, repository: str, sha: str) -> list[dict[str, Any]]:
    value = _api(executor, cwd, repository, "GET", f"/commits/{sha}/check-runs", "-f", "per_page=100")
    runs = value.get("check_runs") if isinstance(value, dict) else None
    if not isinstance(runs, list) or not runs:
        raise ClosureError("incomplete", "current-head check evidence is unavailable")
    normalized = [dict(run) for run in runs if isinstance(run, dict)]
    if len(normalized) != len(runs) or any(run.get("status") != "completed" or run.get("conclusion") != "success" for run in normalized):
        raise ClosureError("incomplete", "current-head checks are not all successful")
    return normalized


def _required_check_authority(
    executor: CommandExecutor, cwd: Path, repository: str
) -> list[dict[str, Any]]:
    protection = _api(executor, cwd, repository, "GET", "/branches/main/protection")
    configured = protection.get("required_status_checks") if isinstance(protection, Mapping) else None
    if not isinstance(configured, Mapping):
        raise ClosureError("incomplete", "required-check authority is unavailable")
    contexts, checks = configured.get("contexts"), configured.get("checks")
    if not isinstance(contexts, list) or not isinstance(checks, list):
        raise ClosureError("incomplete", "required-check authority is malformed")
    required: list[dict[str, Any]] = []
    for context in contexts:
        if not isinstance(context, str) or not context:
            raise ClosureError("incomplete", "required-check authority is malformed")
        required.append({"kind": "status", "name": context})
    for check in checks:
        if not isinstance(check, Mapping) or not isinstance(check.get("context"), str) or not check["context"]:
            raise ClosureError("incomplete", "required-check authority is malformed")
        app_id = check.get("app_id")
        if not isinstance(app_id, int) or isinstance(app_id, bool) or app_id <= 0:
            raise ClosureError("incomplete", "required-check authority is malformed")
        required.append({"kind": "check", "name": check["context"], "app_id": app_id})
    canonical = sorted(required, key=canonical_json)
    if len({canonical_json(item) for item in canonical}) != len(canonical):
        raise ClosureError("incomplete", "required-check authority is ambiguous")
    return canonical


def _statuses(
    executor: CommandExecutor, cwd: Path, repository: str, sha: str
) -> list[dict[str, Any]]:
    value = _api(executor, cwd, repository, "GET", f"/commits/{sha}/status")
    rows = value.get("statuses") if isinstance(value, Mapping) else None
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise ClosureError("incomplete", "current-head status evidence is unavailable")
    return [dict(row) for row in rows]


def _required_check_evidence(
    checks: Sequence[Mapping[str, Any]],
    statuses: Sequence[Mapping[str, Any]],
    required: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for requirement in required:
        candidates = (
            [
                check
                for check in checks
                if check.get("name") == requirement["name"]
                and isinstance(check.get("app"), Mapping)
                and check["app"].get("id") == requirement["app_id"]
            ]
            if requirement["kind"] == "check"
            else [status for status in statuses if status.get("context") == requirement["name"]]
        )
        if len(candidates) != 1:
            raise ClosureError("incomplete", "required-check evidence is unavailable or ambiguous")
        candidate = candidates[0]
        successful = (
            candidate.get("status") == "completed" and candidate.get("conclusion") == "success"
            if requirement["kind"] == "check"
            else candidate.get("state") == "success"
        )
        if not successful:
            raise ClosureError("incomplete", "required-check evidence is not successful")
        evidence_id = candidate.get("id")
        if not isinstance(evidence_id, int) or isinstance(evidence_id, bool) or evidence_id <= 0:
            raise ClosureError("incomplete", "required-check evidence identity is malformed")
        evidence.append({**requirement, "evidence_id": evidence_id})
    return sorted(evidence, key=canonical_json)


def _dispatcher_snapshot(
    executor: CommandExecutor, cwd: Path, task_id: str | None, *, pr_number: int
) -> dict[str, str] | None:
    if task_id is None:
        return None
    result = _run(
        executor,
        cwd,
        [sys.executable, "-m", "app.dispatcher", "show", task_id, "--json"],
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ClosureError("unknown", "dispatcher readback was not JSON") from exc
    task = payload.get("task") if isinstance(payload, dict) else None
    if not isinstance(task, dict) or task.get("task_id") != task_id:
        raise ClosureError("unknown", "dispatcher task identity was not exact")
    holder, lease_id, linked_pr = task.get("claimed_by"), task.get("lease_id"), task.get("linked_pr")
    if task.get("status") != "claimed" or not isinstance(holder, str) or not holder or not isinstance(lease_id, str) or not lease_id:
        raise ClosureError("incomplete", "dispatcher task has no active lease-holder identity")
    if str(linked_pr) != str(pr_number):
        raise ClosureError("incomplete", "dispatcher task is not linked to the exact PR")
    return {"task_id": task_id, "lease_holder": holder, "lease_id": lease_id, "linked_pr": str(pr_number)}


def _dispatcher_completion(
    executor: CommandExecutor, cwd: Path, dispatcher: Mapping[str, Any], *, pr_number: int
) -> dict[str, str]:
    task_id = dispatcher.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise ClosureError("unknown", "dispatcher completion identity is malformed")
    result = _run(executor, cwd, [sys.executable, "-m", "app.dispatcher", "show", task_id, "--json"])
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ClosureError("unknown", "dispatcher readback was not JSON") from exc
    task = payload.get("task") if isinstance(payload, Mapping) else None
    if not isinstance(task, Mapping) or task.get("task_id") != task_id or str(task.get("linked_pr")) != str(pr_number):
        raise ClosureError("incomplete", "dispatcher completion task identity drifted")
    if task.get("status") == "claimed":
        active = _dispatcher_snapshot(executor, cwd, task_id, pr_number=pr_number)
        if active != dispatcher:
            raise ClosureError("drift", "dispatcher task or lease-holder drifted")
        return {"status": "claimed", **active}
    if task.get("status") != "completed" or task.get("claimed_by") is not None or task.get("lease_id") is not None:
        raise ClosureError("incomplete", "dispatcher completion is unavailable")
    events = _run(executor, cwd, [sys.executable, "-m", "app.dispatcher", "events", "--tail", "1000", "--json"])
    try:
        rows = json.loads(events.stdout).get("events", [])
    except (AttributeError, json.JSONDecodeError) as exc:
        raise ClosureError("unknown", "dispatcher completion receipt was not JSON") from exc
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("task_id") == task_id and row.get("event_type") == "task.completed" and row.get("actor") == dispatcher.get("lease_holder") and row.get("lease_id") == dispatcher.get("lease_id")]
    if len(matches) != 1:
        raise ClosureError("incomplete", "dispatcher completion receipt is unavailable or ambiguous")
    return {"status": "completed", **{key: str(dispatcher[key]) for key in ("task_id", "lease_holder", "lease_id", "linked_pr")}}


def _issue_timeline(executor: CommandExecutor, cwd: Path, repository: str, number: int) -> list[dict[str, Any]]:
    value = _api(executor, cwd, repository, "GET", f"/issues/{number}/timeline", "-f", "per_page=100")
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ClosureError("unknown", "Issue timeline readback was malformed")
    return [dict(item) for item in value]


def _validate_closure_attribution(
    events: Sequence[Mapping[str, Any]], timeline: Sequence[Mapping[str, Any]], repository: str, issue_number: int, merge_sha: str, pr_number: int
) -> str:
    matches = []
    for event in events:
        if event.get("event") != "closed" or event.get("commit_id") != merge_sha:
            continue
        # The endpoint is already scoped to /issues/{issue_number}/events.  The
        # event API may omit issue.number, so only reject an explicitly
        # conflicting number and never require the optional field.
        event_issue = event.get("issue")
        if isinstance(event_issue, Mapping) and event_issue.get("number") not in (None, issue_number):
            continue
        if event_issue is not None and not isinstance(event_issue, Mapping):
            continue
        matches.append(event)
    if len(matches) == 1:
        return "GitHub-native closing keyword and exact merge event"
    null_close = [event for event in events if event.get("event") == "closed" and event.get("commit_id") is None]
    pr_references = [
        event for event in timeline
        if event.get("event") == "cross-referenced"
        and isinstance(event.get("source"), Mapping)
        and isinstance(event["source"].get("issue"), Mapping)
        and event["source"]["issue"].get("number") == pr_number
        and isinstance(event["source"]["issue"].get("pull_request"), Mapping)
        and event["source"]["issue"]["pull_request"].get("url") == f"https://api.github.com/repos/{repository}/pulls/{pr_number}"
    ]
    if len(null_close) == 1 and len(pr_references) == 1:
        return "GitHub-native exact PR closer attribution"
    raise ClosureError("incomplete", "exact closing Issue attribution was not proven")


def _snapshot(request: ClosureRequest, executor: CommandExecutor) -> dict[str, Any]:
    if not REPO_RE.fullmatch(request.repository) or request.pr_number <= 0:
        raise ClosureError("unsupported", "repository and PR number are required")
    cwd = request.worktree.resolve()
    pr = _pr(executor, cwd, request.repository, request.pr_number)
    if str(pr.get("state", "")).lower() != "open" or pr.get("merged_at") is not None:
        raise ClosureError("unsupported", "closure plan requires one open PR")
    base, head = pr.get("base"), pr.get("head")
    if not isinstance(base, Mapping) or not isinstance(head, Mapping) or base.get("ref") != "main":
        raise ClosureError("unsupported", "light path requires a main-targeting PR")
    if base.get("repo", {}).get("full_name") != request.repository or head.get("repo", {}).get("full_name") != request.repository:
        raise ClosureError("unsupported", "light path requires an in-repository PR")
    sha = head.get("sha")
    if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
        raise ClosureError("unknown", "PR head SHA is malformed")
    body = pr.get("body") or ""
    if not isinstance(body, str) or "Final-Review-Rounds: 0" not in body:
        raise ClosureError("unsupported", "light path requires Final-Review-Rounds: 0")
    if re.search(r"(?i)(?:risk[- ]surface|high[- ]risk|tier\s*3|final-review-rounds:\s*[12])", body):
        raise ClosureError("unsupported", "PR body declares an unsupported light-path surface")
    issue_number = _issue_number(body)
    issue = _issue(executor, cwd, request.repository, issue_number)
    _issue_hashes(issue)
    labels = sorted(str(item.get("name") if isinstance(item, dict) else item) for item in issue.get("labels", []))
    if str(issue.get("state", "")).lower() != "open" or "agent:in-progress" not in labels:
        raise ClosureError("incomplete", "governing Issue is not the active open claim")
    if not isinstance(request.verify_evidence, Mapping) or request.verify_evidence.get("head_sha") != sha or not request.verify_evidence.get("verified"):
        raise ClosureError("incomplete", "self-verified Verify evidence is not bound to the PR head")
    checks = _checks(executor, cwd, request.repository, sha)
    statuses = _statuses(executor, cwd, request.repository, sha)
    required_checks = _required_check_authority(executor, cwd, request.repository)
    required_evidence = _required_check_evidence(checks, statuses, required_checks)
    dispatcher = _dispatcher_snapshot(executor, cwd, request.dispatcher_task_id, pr_number=request.pr_number)
    return {"pr": pr, "issue": issue, "issue_labels": labels, "checks": checks, "required_checks": required_checks, "required_evidence": required_evidence, "head_sha": sha, "issue_number": issue_number, "dispatcher": dispatcher}


def build_closure_plan(request: ClosureRequest, *, executor: CommandExecutor | None = None) -> dict[str, Any]:
    runner = executor or SubprocessExecutor()
    before = _snapshot(request, runner)
    plan = {
        "schema": PLAN_SCHEMA, "repository": request.repository, "worktree": str(request.worktree.resolve()),
        "pr_number": request.pr_number, "base_sha": before["pr"]["base"].get("sha"), "head_sha": before["head_sha"],
        "title_sha256": hashlib.sha256(str(before["pr"].get("title") or "").encode()).hexdigest(),
        "body_sha256": hashlib.sha256(str(before["pr"].get("body") or "").encode()).hexdigest(),
        "governing_issue": before["issue_number"], "closing_issues": [before["issue_number"]],
        "closing_issue": {"number": before["issue_number"], **_issue_hashes(before["issue"])},
        "tier": 2, "final_review_rounds": 0, "verify_evidence": json.loads(canonical_json(request.verify_evidence)),
        "checks": [{"name": item.get("name"), "status": item.get("status"), "conclusion": item.get("conclusion")} for item in before["checks"]],
        "required_checks": before["required_checks"], "required_check_evidence": before["required_evidence"],
        "merge": {"method": "squash", "commit_title": f"Merge PR #{request.pr_number}", "commit_message": "Governed light-path closure."},
        "post_merge": {"remove_label_prefix": "agent:", "dispatcher": before["dispatcher"], "remaining_action": "post-merge-owner-doc"},
    }
    plan["plan_sha256"] = closure_plan_hash(plan)
    return plan


def _validated(plan: Mapping[str, Any], expected: str) -> dict[str, Any]:
    value = json.loads(canonical_json(plan))
    if value.get("schema") != PLAN_SCHEMA or value.get("plan_sha256") != expected or closure_plan_hash(value) != expected:
        raise ClosureError("drift", "closure plan hash mismatch")
    closing_issue = value.get("closing_issue")
    if (
        value.get("tier") not in (1, 2)
        or value.get("final_review_rounds") != 0
        or value.get("closing_issues") != [value.get("governing_issue")]
        or not isinstance(closing_issue, Mapping)
        or closing_issue.get("number") != value.get("governing_issue")
        or not all(isinstance(closing_issue.get(field), str) and re.fullmatch(r"[0-9a-f]{64}", closing_issue[field]) for field in ("title_sha256", "body_sha256"))
        or not isinstance(value.get("required_checks"), list)
        or not isinstance(value.get("required_check_evidence"), list)
    ):
        raise ClosureError("unsupported", "plan is outside the light path")
    return value


def apply_closure_plan(plan: Mapping[str, Any], *, expected_plan_sha256: str, executor: CommandExecutor | None = None) -> dict[str, Any]:
    value = _validated(plan, expected_plan_sha256); runner = executor or SubprocessExecutor(); cwd = Path(value["worktree"])
    dispatcher = value["post_merge"].get("dispatcher") or {}
    task_id = dispatcher.get("task_id") if isinstance(dispatcher, Mapping) else None
    current_pr = _pr(runner, cwd, value["repository"], value["pr_number"])
    if str(current_pr.get("state", "")).lower() == "closed" and current_pr.get("merged_at") is not None:
        if current_pr.get("merge_commit_sha") is None or current_pr.get("head", {}).get("sha") != value["head_sha"]:
            raise ClosureError("unknown", "closed PR does not prove the planned exact merge")
        current = {"pr": current_pr, "issue": _issue(runner, cwd, value["repository"], value["governing_issue"]), "issue_labels": [], "checks": [], "head_sha": value["head_sha"], "issue_number": value["governing_issue"], "dispatcher": dispatcher}
        _validate_planned_issue(current["issue"], value, phase="post-merge")
        if str(current["issue"].get("state", "")).lower() != "closed":
            raise ClosureError("incomplete", "merged PR exists but GitHub-native Issue closure is absent")
        events = _issue_events(runner, cwd, value["repository"], int(value["governing_issue"]))
        attribution = _validate_closure_attribution(events, _issue_timeline(runner, cwd, value["repository"], int(value["governing_issue"])), str(value["repository"]), int(value["governing_issue"]), str(current_pr["merge_commit_sha"]), int(value["pr_number"]))
        current["closure_attribution"] = attribution
        return _finish_cleanup(value, current, runner, cwd, reconciled=True)
    request = ClosureRequest(value["repository"], cwd, int(value["pr_number"]), value["verify_evidence"], task_id)
    planned_dispatcher = _dispatcher_snapshot(runner, cwd, task_id, pr_number=int(value["pr_number"])) if task_id else {}
    if planned_dispatcher != dispatcher:
        raise ClosureError("drift", "dispatcher task or lease-holder drifted before merge")
    current = _snapshot(request, runner)
    _validate_planned_issue(current["issue"], value, phase="pre-merge")
    if current["head_sha"] != value["head_sha"] or current["issue_number"] != value["governing_issue"] or current["pr"].get("base", {}).get("sha") != value["base_sha"] or hashlib.sha256(str(current["pr"].get("body") or "").encode()).hexdigest() != value["body_sha256"] or hashlib.sha256(str(current["pr"].get("title") or "").encode()).hexdigest() != value["title_sha256"]:
        raise ClosureError("drift", "mutable PR or Issue authority drifted before merge")
    observed_checks = [{"name": item.get("name"), "status": item.get("status"), "conclusion": item.get("conclusion")} for item in current["checks"]]
    if observed_checks != value["checks"]:
        raise ClosureError("drift", "current-head check evidence drifted before merge")
    if current["required_checks"] != value["required_checks"] or current["required_evidence"] != value["required_check_evidence"]:
        raise ClosureError("drift", "required-check authority or evidence drifted before merge")
    merge = value["merge"]
    result = runner.run(["gh", "api", "--hostname", GITHUB_HOST, "--method", "PUT", f"repos/{value['repository']}/pulls/{value['pr_number']}/merge", "-f", f"sha={value['head_sha']}", "-f", f"merge_method={merge['method']}", "-f", f"commit_title={merge['commit_title']}", "-f", f"commit_message={merge['commit_message']}"], cwd=cwd)
    if result.returncode:
        try:
            readback = _pr(runner, cwd, value["repository"], value["pr_number"])
            if readback.get("merged_at") is not None and readback.get("head", {}).get("sha") == value["head_sha"]:
                current = {"pr": readback, "issue": _issue(runner, cwd, value["repository"], value["governing_issue"]), "issue_labels": [], "checks": [], "head_sha": value["head_sha"], "issue_number": value["governing_issue"], "dispatcher": dispatcher}
                _validate_planned_issue(current["issue"], value, phase="post-merge")
                if str(current["issue"].get("state", "")).lower() == "closed":
                    events = _issue_events(runner, cwd, value["repository"], int(value["governing_issue"]))
                    attribution = _validate_closure_attribution(events, _issue_timeline(runner, cwd, value["repository"], int(value["governing_issue"])), str(value["repository"]), int(value["governing_issue"]), str(readback["merge_commit_sha"]), int(value["pr_number"]))
                    current["closure_attribution"] = attribution
                    return _finish_cleanup(value, current, runner, cwd, reconciled=True)
        except ClosureError:
            pass
        raise ClosureError("unknown", "exact-head merge outcome is ambiguous; read PR and Issue", result)
    merged = _pr(runner, cwd, value["repository"], int(value["pr_number"]))
    merge_sha = merged.get("merge_commit_sha")
    closed = _issue(runner, cwd, value["repository"], int(value["governing_issue"]))
    if str(merged.get("state", "")).lower() != "closed" or merged.get("merged_at") is None or not isinstance(merge_sha, str) or not SHA_RE.fullmatch(merge_sha) or str(closed.get("state", "")).lower() != "closed":
        raise ClosureError("incomplete", "merge or GitHub-native Issue closure lacks exact readback")
    _validate_planned_issue(closed, value, phase="post-merge")
    events = _issue_events(runner, cwd, value["repository"], int(value["governing_issue"]))
    attribution = _validate_closure_attribution(events, _issue_timeline(runner, cwd, value["repository"], int(value["governing_issue"])), str(value["repository"]), int(value["governing_issue"]), merge_sha, int(value["pr_number"]))
    return _finish_cleanup(value, {"pr": merged, "issue": closed, "issue_labels": [], "checks": [], "head_sha": value["head_sha"], "issue_number": value["governing_issue"], "dispatcher": dispatcher, "closure_attribution": attribution}, runner, cwd, reconciled=False, merge_sha=merge_sha)


def _finish_cleanup(value: Mapping[str, Any], current: Mapping[str, Any], runner: CommandExecutor, cwd: Path, *, reconciled: bool, merge_sha: str | None = None) -> dict[str, Any]:
    closed = current["issue"]
    labels = [str(item.get("name") if isinstance(item, dict) else item) for item in closed.get("labels", [])]
    retained = [label for label in labels if not label.startswith("agent:")]
    if set(labels) != set(retained):
        _api(runner, cwd, str(value["repository"]), "PATCH", f"/issues/{value['governing_issue']}", "--input", "-", input_text=canonical_json({"labels": retained}))
    dispatcher = value["post_merge"].get("dispatcher")
    if isinstance(dispatcher, Mapping):
        state = _dispatcher_completion(runner, cwd, dispatcher, pr_number=int(value["pr_number"]))
        if state["status"] == "claimed":
            completed = runner.run([sys.executable, "-m", "app.dispatcher", "complete", str(dispatcher["task_id"]), "--agent", str(dispatcher["lease_holder"]), "--json"], cwd=cwd)
            if completed.returncode:
                raise ClosureError("incomplete", "merge succeeded but dispatcher completion failed", completed)
            state = _dispatcher_completion(runner, cwd, dispatcher, pr_number=int(value["pr_number"]))
        dispatcher = state
    merge_sha = merge_sha or current["pr"].get("merge_commit_sha")
    receipt = {"schema": RECEIPT_SCHEMA, "outcome": "success", "reconciled": reconciled, "plan_sha256": value["plan_sha256"], "repository": value["repository"], "pr_number": value["pr_number"], "head_sha": value["head_sha"], "merge_sha": merge_sha, "issue": {"number": value["governing_issue"], "state": "closed", "closure_attribution": current.get("closure_attribution", "GitHub-native closing keyword and exact merge event")}, "cleanup": {"removed_agent_labels": sorted(set(labels) - set(retained)), "dispatcher": dispatcher, "project_projection": "optional/unmodified"}, "remaining_action": "post-merge-owner-doc"}
    receipt["receipt_sha256"] = _digest(receipt)
    return receipt


def cli_main(argv: Sequence[str] | None = None, *, executor: CommandExecutor | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); subs = parser.add_subparsers(dest="command", required=True)
    p = subs.add_parser("plan"); p.add_argument("--repository", required=True); p.add_argument("--worktree", type=Path, default=Path.cwd()); p.add_argument("--pr-number", type=int, required=True); p.add_argument("--verify-evidence-json", type=Path, required=True); p.add_argument("--dispatcher-task-id")
    a = subs.add_parser("apply"); a.add_argument("--plan-file", type=Path, required=True); a.add_argument("--expected-plan-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan": result = build_closure_plan(ClosureRequest(args.repository, args.worktree, args.pr_number, json.loads(args.verify_evidence_json.read_text()), args.dispatcher_task_id), executor=executor)
        else: result = apply_closure_plan(json.loads(args.plan_file.read_text()), expected_plan_sha256=args.expected_plan_sha256, executor=executor)
    except ClosureError as exc:
        print(canonical_json({"ok": False, "outcome": exc.outcome, "reason": exc.reason, "returncode": exc.result.returncode if exc.result else None}), file=sys.stderr); return exc.result.returncode if exc.result else (4 if exc.outcome in {"unknown", "incomplete"} else 3)
    print(canonical_json(result)); return 0
