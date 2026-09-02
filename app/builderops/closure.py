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


def _run(executor: CommandExecutor, cwd: Path, argv: Sequence[str]) -> CommandResult:
    result = executor.run(argv, cwd=cwd)
    if result.returncode:
        raise ClosureError("command-failed", "closure command failed", result)
    return result


def _api(executor: CommandExecutor, cwd: Path, repository: str, method: str, endpoint: str, *fields: str) -> Any:
    result = _run(executor, cwd, ["gh", "api", "--hostname", GITHUB_HOST, "--method", method, f"repos/{repository}{endpoint}", *fields])
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
    labels = sorted(str(item.get("name") if isinstance(item, dict) else item) for item in issue.get("labels", []))
    if str(issue.get("state", "")).lower() != "open" or "agent:in-progress" not in labels:
        raise ClosureError("incomplete", "governing Issue is not the active open claim")
    if not isinstance(request.verify_evidence, Mapping) or request.verify_evidence.get("head_sha") != sha or not request.verify_evidence.get("verified"):
        raise ClosureError("incomplete", "self-verified Verify evidence is not bound to the PR head")
    checks = _checks(executor, cwd, request.repository, sha)
    return {"pr": pr, "issue": issue, "issue_labels": labels, "checks": checks, "head_sha": sha, "issue_number": issue_number}


def build_closure_plan(request: ClosureRequest, *, executor: CommandExecutor | None = None) -> dict[str, Any]:
    runner = executor or SubprocessExecutor()
    before = _snapshot(request, runner)
    plan = {
        "schema": PLAN_SCHEMA, "repository": request.repository, "worktree": str(request.worktree.resolve()),
        "pr_number": request.pr_number, "base_sha": before["pr"]["base"].get("sha"), "head_sha": before["head_sha"],
        "title_sha256": hashlib.sha256(str(before["pr"].get("title") or "").encode()).hexdigest(),
        "body_sha256": hashlib.sha256(str(before["pr"].get("body") or "").encode()).hexdigest(),
        "governing_issue": before["issue_number"], "closing_issues": [before["issue_number"]],
        "tier": 2, "final_review_rounds": 0, "verify_evidence": json.loads(canonical_json(request.verify_evidence)),
        "checks": [{"name": item.get("name"), "status": item.get("status"), "conclusion": item.get("conclusion")} for item in before["checks"]],
        "merge": {"method": "squash", "commit_title": f"Merge PR #{request.pr_number}", "commit_message": "Governed light-path closure."},
        "post_merge": {"remove_label_prefix": "agent:", "dispatcher_task_id": request.dispatcher_task_id, "remaining_action": "post-merge-owner-doc"},
    }
    plan["plan_sha256"] = closure_plan_hash(plan)
    return plan


def _validated(plan: Mapping[str, Any], expected: str) -> dict[str, Any]:
    value = json.loads(canonical_json(plan))
    if value.get("schema") != PLAN_SCHEMA or value.get("plan_sha256") != expected or closure_plan_hash(value) != expected:
        raise ClosureError("drift", "closure plan hash mismatch")
    if value.get("tier") not in (1, 2) or value.get("final_review_rounds") != 0 or value.get("closing_issues") != [value.get("governing_issue")]:
        raise ClosureError("unsupported", "plan is outside the light path")
    return value


def apply_closure_plan(plan: Mapping[str, Any], *, expected_plan_sha256: str, executor: CommandExecutor | None = None) -> dict[str, Any]:
    value = _validated(plan, expected_plan_sha256); runner = executor or SubprocessExecutor(); cwd = Path(value["worktree"])
    request = ClosureRequest(value["repository"], cwd, int(value["pr_number"]), value["verify_evidence"], value["post_merge"].get("dispatcher_task_id"))
    current_pr = _pr(runner, cwd, value["repository"], value["pr_number"])
    if str(current_pr.get("state", "")).lower() == "closed" and current_pr.get("merged_at") is not None:
        if current_pr.get("merge_commit_sha") is None or current_pr.get("head", {}).get("sha") != value["head_sha"]:
            raise ClosureError("unknown", "closed PR does not prove the planned exact merge")
        current = {"pr": current_pr, "issue": _issue(runner, cwd, value["repository"], value["governing_issue"]), "issue_labels": [], "checks": [], "head_sha": value["head_sha"], "issue_number": value["governing_issue"]}
        if str(current["issue"].get("state", "")).lower() != "closed":
            raise ClosureError("incomplete", "merged PR exists but GitHub-native Issue closure is absent")
        return _finish_cleanup(value, current, runner, cwd, reconciled=True)
    current = _snapshot(request, runner)
    if current["head_sha"] != value["head_sha"] or current["issue_number"] != value["governing_issue"] or current["pr"].get("base", {}).get("sha") != value["base_sha"] or hashlib.sha256(str(current["pr"].get("body") or "").encode()).hexdigest() != value["body_sha256"] or hashlib.sha256(str(current["pr"].get("title") or "").encode()).hexdigest() != value["title_sha256"]:
        raise ClosureError("drift", "mutable PR or Issue authority drifted before merge")
    observed_checks = [{"name": item.get("name"), "status": item.get("status"), "conclusion": item.get("conclusion")} for item in current["checks"]]
    if observed_checks != value["checks"]:
        raise ClosureError("drift", "current-head check evidence drifted before merge")
    merge = value["merge"]
    result = runner.run(["gh", "api", "--hostname", GITHUB_HOST, "--method", "PUT", f"repos/{value['repository']}/pulls/{value['pr_number']}/merge", "-f", f"sha={value['head_sha']}", "-f", f"merge_method={merge['method']}", "-f", f"commit_title={merge['commit_title']}", "-f", f"commit_message={merge['commit_message']}"], cwd=cwd)
    if result.returncode:
        try:
            readback = _pr(runner, cwd, value["repository"], value["pr_number"])
            if readback.get("merged_at") is not None and readback.get("head", {}).get("sha") == value["head_sha"]:
                current = {"pr": readback, "issue": _issue(runner, cwd, value["repository"], value["governing_issue"]), "issue_labels": [], "checks": [], "head_sha": value["head_sha"], "issue_number": value["governing_issue"]}
                if str(current["issue"].get("state", "")).lower() == "closed":
                    return _finish_cleanup(value, current, runner, cwd, reconciled=True)
        except ClosureError:
            pass
        raise ClosureError("unknown", "exact-head merge outcome is ambiguous; read PR and Issue", result)
    merged = _pr(runner, cwd, value["repository"], int(value["pr_number"]))
    merge_sha = merged.get("merge_commit_sha")
    closed = _issue(runner, cwd, value["repository"], int(value["governing_issue"]))
    if str(merged.get("state", "")).lower() != "closed" or merged.get("merged_at") is None or not isinstance(merge_sha, str) or not SHA_RE.fullmatch(merge_sha) or str(closed.get("state", "")).lower() != "closed":
        raise ClosureError("incomplete", "merge or GitHub-native Issue closure lacks exact readback")
    return _finish_cleanup(value, {"pr": merged, "issue": closed, "issue_labels": [], "checks": [], "head_sha": value["head_sha"], "issue_number": value["governing_issue"]}, runner, cwd, reconciled=False, merge_sha=merge_sha)


def _finish_cleanup(value: Mapping[str, Any], current: Mapping[str, Any], runner: CommandExecutor, cwd: Path, *, reconciled: bool, merge_sha: str | None = None) -> dict[str, Any]:
    closed = current["issue"]
    labels = [str(item.get("name") if isinstance(item, dict) else item) for item in closed.get("labels", [])]
    retained = [label for label in labels if not label.startswith("agent:")]
    if set(labels) != set(retained):
        _api(runner, cwd, str(value["repository"]), "PATCH", f"/issues/{value['governing_issue']}", "-f", f"labels={json.dumps(retained)}")
    dispatcher = value["post_merge"].get("dispatcher_task_id")
    if dispatcher:
        completed = runner.run([sys.executable, "-m", "app.dispatcher", "complete", "--task-id", str(dispatcher)], cwd=cwd)
        if completed.returncode:
            raise ClosureError("incomplete", "merge succeeded but dispatcher completion failed", completed)
    merge_sha = merge_sha or current["pr"].get("merge_commit_sha")
    receipt = {"schema": RECEIPT_SCHEMA, "outcome": "success", "reconciled": reconciled, "plan_sha256": value["plan_sha256"], "repository": value["repository"], "pr_number": value["pr_number"], "head_sha": value["head_sha"], "merge_sha": merge_sha, "issue": {"number": value["governing_issue"], "state": "closed", "closure_attribution": "GitHub-native closing keyword"}, "cleanup": {"removed_agent_labels": sorted(set(labels) - set(retained)), "dispatcher_task_id": dispatcher, "project_projection": "optional/unmodified"}, "remaining_action": "post-merge-owner-doc"}
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
