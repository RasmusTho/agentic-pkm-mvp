"""Hash-bound, light-path-only GitHub closure adapter.

This module deliberately owns effect sequencing, not closure policy.  The
verification-and-closure skill remains the authority for deciding whether a PR
belongs on this path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from app.builderops.publication import CommandExecutor, CommandResult, SubprocessExecutor
from app.builderops.issue_contract_validation import is_resolvable_verify_target
from app.dispatcher.sync_github import github_issue_task_id
from app.dispatcher.verification_contract import CLOSING_ISSUE_PATTERN, resolve_issue_authority

PLAN_SCHEMA = "builder.closure-plan.v1"
RECEIPT_SCHEMA = "builder.closure-receipt.v1"
VERIFY_EVIDENCE_SCHEMA = "builder.closure-verify-evidence.v1"
GITHUB_HOST = "github.com"
SHA_RE = re.compile(r"[0-9a-f]{40,64}\Z")
REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")
PR_CONTRACT_NAME = "pr-contract"
DISPATCHER_MODE = "dispatcher-backed"
DEGRADED_MODE = "github-label-only-fallback"
CHECK_CONCLUSIONS_ACCEPTED = {"success", "neutral"}
CLEANUP_GUARD_TTL_SECONDS = 900
CLEANUP_GUARD_MAX_COMMAND_SECONDS = CLEANUP_GUARD_TTL_SECONDS / 2
PICKUP_RECEIPT_RE = re.compile(
    r"Pickup intent receipt: agent=(?P<agent>\S+) session=(?P<session>\S+) "
    r"branch=(?P<branch>\S+) worktree=(?P<worktree>.+?) "
    r"coordination_mode=(?P<mode>\S+) fallback_reason=(?P<reason>\S+) "
    r"issue=(?P<issue>[1-9][0-9]*)\Z"
)


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
    coordination_mode: str | None = None
    fallback_reason: str | None = None
    coordination_evidence: str | None = None
    caller_agent: str | None = None
    caller_session: str | None = None
    caller_branch: str | None = None


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
    result = _run(
        executor,
        cwd,
        [
            "gh",
            "api",
            "--hostname",
            GITHUB_HOST,
            "--method",
            "GET",
            f"repos/{repository}/issues/{number}/events",
            "--paginate",
            "--slurp",
            "-f",
            "per_page=100",
        ],
    )
    try:
        pages = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ClosureError("unknown", "Issue event readback was not JSON") from exc
    if not isinstance(pages, list) or not pages or not all(isinstance(page, list) for page in pages):
        raise ClosureError("incomplete", "Issue event pagination was incomplete")
    events = [event for page in pages for event in page]
    if not all(isinstance(event, dict) for event in events):
        raise ClosureError("unknown", "Issue event readback was malformed")
    return [dict(event) for event in events]


def _issue_number(body: str) -> int:
    authority = resolve_issue_authority(body)
    if (
        authority is None
        or authority.closing_issues != (authority.governing_issue,)
        or len(CLOSING_ISSUE_PATTERN.findall(body)) != 1
    ):
        raise ClosureError("unsupported", "PR must have one exact governing and closing Issue")
    return authority.governing_issue


def _parse_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ClosureError("incomplete", f"{field} revision timestamp is unavailable")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ClosureError("incomplete", f"{field} revision timestamp is malformed") from exc
    if parsed.tzinfo is None:
        raise ClosureError("incomplete", f"{field} revision timestamp is malformed")
    return parsed


def _latest_row(rows: Sequence[Mapping[str, Any]], *, kind: str) -> dict[str, Any]:
    """Resolve one latest rerun while refusing an unorderable history."""
    if not rows:
        raise ClosureError("incomplete", f"{kind} evidence is unavailable")
    if len(rows) == 1:
        return dict(rows[0])
    ranked: list[tuple[datetime, int, dict[str, Any]]] = []
    seen_ids: set[int] = set()
    for row in rows:
        row_id = row.get("id")
        if not isinstance(row_id, int) or isinstance(row_id, bool) or row_id <= 0 or row_id in seen_ids:
            raise ClosureError("incomplete", f"{kind} rerun history is malformed or ambiguous")
        seen_ids.add(row_id)
        timestamps = [
            _parse_timestamp(row[field], f"{kind}.{field}")
            for field in ("completed_at", "updated_at", "started_at", "created_at")
            if row.get(field) is not None
        ]
        if not timestamps:
            raise ClosureError("incomplete", f"{kind} rerun history has no ordering evidence")
        ranked.append((max(timestamps), row_id, dict(row)))
    return max(ranked, key=lambda item: (item[0], item[1]))[2]


def _check_identity(run: Mapping[str, Any]) -> tuple[str, int]:
    name = run.get("name")
    app = run.get("app")
    app_id = app.get("id") if isinstance(app, Mapping) else None
    if not isinstance(name, str) or not name or not isinstance(app, Mapping):
        raise ClosureError("incomplete", "check-run identity is malformed")
    if not isinstance(app_id, int) or isinstance(app_id, bool) or app_id <= 0:
        raise ClosureError("incomplete", "check-run application identity is malformed")
    return name, app_id


def _check_snapshot(run: Mapping[str, Any]) -> dict[str, Any]:
    name, app_id = _check_identity(run)
    row: dict[str, Any] = {
        "id": run.get("id"),
        "name": name,
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "app_id": app_id,
        "head_sha": run.get("head_sha"),
    }
    for field in ("started_at", "completed_at", "updated_at", "created_at"):
        if run.get(field) is not None:
            row[field] = run[field]
    return row


def _checks(executor: CommandExecutor, cwd: Path, repository: str, sha: str) -> list[dict[str, Any]]:
    value = _api(executor, cwd, repository, "GET", f"/commits/{sha}/check-runs", "-f", "per_page=100")
    runs = value.get("check_runs") if isinstance(value, dict) else None
    if not isinstance(runs, list) or not runs:
        raise ClosureError("incomplete", "current-head check evidence is unavailable")
    normalized = [dict(run) for run in runs if isinstance(run, dict)]
    if len(normalized) != len(runs):
        raise ClosureError("incomplete", "current-head check evidence is malformed")
    histories: dict[str, list[dict[str, Any]]] = {}
    for run in normalized:
        if run.get("head_sha") != sha:
            raise ClosureError("incomplete", "current-head check evidence is foreign")
        name, _ = _check_identity(run)
        histories.setdefault(name, []).append(run)
    latest: list[dict[str, Any]] = []
    for history in histories.values():
        executed = [run for run in history if run.get("conclusion") != "skipped"]
        selected = _latest_row(executed or history, kind="check-run")
        if selected.get("conclusion") != "skipped":
            latest.append(selected)
    if any(
        run.get("status") != "completed"
        or run.get("conclusion") not in {"success", "neutral"}
        for run in latest
    ):
        raise ClosureError("incomplete", "current-head checks are not all successful")
    return sorted(latest, key=lambda run: canonical_json(_check_snapshot(run)))


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
    if not contexts and not checks:
        raise ClosureError("incomplete", "required-check authority is empty")
    by_name: dict[str, dict[str, Any]] = {}
    for context in contexts:
        if not isinstance(context, str) or not context:
            raise ClosureError("incomplete", "required-check authority is malformed")
        # GitHub can expose one logical requirement in both the legacy
        # contexts list and the app-bound checks list.  Union by context name;
        # the app-bound form is the stronger identity when both are present.
        by_name.setdefault(context, {"kind": "status", "name": context})
    for check in checks:
        if not isinstance(check, Mapping) or not isinstance(check.get("context"), str) or not check["context"]:
            raise ClosureError("incomplete", "required-check authority is malformed")
        app_id = check.get("app_id")
        if app_id is not None and (not isinstance(app_id, int) or isinstance(app_id, bool)):
            raise ClosureError("incomplete", "required-check authority is malformed")
        name = check["context"]
        candidate = {"kind": "check", "name": name, "app_id": app_id}
        existing = by_name.get(name)
        if existing is not None and existing.get("kind") == "check" and existing.get("app_id") != app_id:
            raise ClosureError("incomplete", "required-check authority is ambiguous")
        by_name[name] = candidate
    required = list(by_name.values())
    canonical = sorted(required, key=canonical_json)
    return canonical


def _statuses(
    executor: CommandExecutor, cwd: Path, repository: str, sha: str
) -> list[dict[str, Any]]:
    value = _api(executor, cwd, repository, "GET", f"/commits/{sha}/status")
    rows = value.get("statuses") if isinstance(value, Mapping) else None
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise ClosureError("incomplete", "current-head status evidence is unavailable")
    histories: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        context = row.get("context")
        if not isinstance(context, str) or not context:
            raise ClosureError("incomplete", "current-head status evidence is malformed")
        histories.setdefault(context, []).append(dict(row))
    return sorted(
        [_latest_row(history, kind="status") for history in histories.values()],
        key=lambda row: canonical_json({"context": row.get("context"), "id": row.get("id")}),
    )


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
                and (
                    requirement["app_id"] is None
                    or check["app"].get("id") == requirement["app_id"]
                )
            ]
            if requirement["kind"] == "check"
            else [status for status in statuses if status.get("context") == requirement["name"]]
        )
        if len(candidates) != 1:
            raise ClosureError("incomplete", "required-check evidence is unavailable or ambiguous")
        candidate = candidates[0]
        successful = (
            candidate.get("status") == "completed"
            and candidate.get("conclusion") in CHECK_CONCLUSIONS_ACCEPTED
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


def _closing_issue_references(
    executor: CommandExecutor, cwd: Path, repository: str, pr_number: int
) -> list[int]:
    owner, name = repository.split("/", 1)
    query = """
      query($owner: String!, $name: String!, $number: Int!) {
        repository(owner: $owner, name: $name) {
          pullRequest(number: $number) {
            closingIssuesReferences(first: 11) {
              nodes { number repository { nameWithOwner } }
              pageInfo { hasNextPage }
            }
          }
        }
      }
    """
    result = _run(
        executor,
        cwd,
        [
            "gh",
            "api",
            "--hostname",
            GITHUB_HOST,
            "graphql",
            "-f",
            f"query={query}",
            "-f",
            f"owner={owner}",
            "-f",
            f"name={name}",
            "-F",
            f"number={pr_number}",
        ],
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ClosureError("unknown", "GitHub closing-reference readback was not JSON") from exc
    data = payload.get("data") if isinstance(payload, Mapping) else None
    repository_row = data.get("repository") if isinstance(data, Mapping) else None
    pull = repository_row.get("pullRequest") if isinstance(repository_row, Mapping) else None
    references = pull.get("closingIssuesReferences") if isinstance(pull, Mapping) else None
    nodes = references.get("nodes") if isinstance(references, Mapping) else None
    page_info = references.get("pageInfo") if isinstance(references, Mapping) else None
    if (
        not isinstance(nodes, list)
        or not isinstance(page_info, Mapping)
        or page_info.get("hasNextPage") is not False
    ):
        raise ClosureError("incomplete", "GitHub closing-reference evidence is unavailable or incomplete")
    numbers: list[int] = []
    for node in nodes:
        number = node.get("number") if isinstance(node, Mapping) else None
        node_repository = node.get("repository") if isinstance(node, Mapping) else None
        if (
            not isinstance(number, int)
            or isinstance(number, bool)
            or number <= 0
            or not isinstance(node_repository, Mapping)
            or node_repository.get("nameWithOwner") != repository
        ):
            raise ClosureError("incomplete", "GitHub closing-reference identity is malformed")
        numbers.append(number)
    if len(numbers) != len(set(numbers)):
        raise ClosureError("incomplete", "GitHub closing-reference evidence is ambiguous")
    return sorted(numbers)


def _verify_target_path(target: str) -> str | None:
    canonical = target.strip()
    annotated = re.fullmatch(r"`(?P<inner>[^`]+)` \S.*", canonical)
    if annotated is not None:
        canonical = annotated.group("inner")
    else:
        diff_target = re.fullmatch(r"diff of `(?P<path>[^`]+)`(?: \S.*)?", canonical)
        if diff_target is not None:
            return diff_target.group("path")
        presence_target = re.fullmatch(
            r"`[^`]+` present in `(?P<path>[^`]+)`(?:[,;]? \S.*)?", canonical
        )
        if presence_target is not None:
            return presence_target.group("path")
    if canonical.startswith("runtime receipt: "):
        return None
    for prefix in ("doc writeback at ", "roadmap diff: "):
        if canonical.startswith(prefix):
            canonical = canonical.removeprefix(prefix).strip("`")
            path, separator, _ = canonical.partition(" :: ")
            return path if separator else None
    canonical = canonical.strip("`")
    path, separator, _ = canonical.partition(" :: ")
    if separator:
        return path
    path, separator, _ = canonical.partition("::")
    return path if separator else None


def _acceptance_criteria(issue_body: object, *, repo_root: Path | None = None) -> list[dict[str, Any]]:
    if not isinstance(issue_body, str):
        raise ClosureError("incomplete", "governing Issue acceptance criteria are unavailable")
    section_match = re.search(
        r"(?ims)^##\s+Acceptance Criteria\s*$([\s\S]*?)(?=^##\s|^---\s*$|\Z)",
        issue_body,
    )
    if section_match is None:
        raise ClosureError("incomplete", "governing Issue acceptance criteria are unavailable")
    section = section_match.group(1).strip()
    starts = list(re.finditer(r"(?m)^\s*[-*]\s+\[[ xX]\]\s+.+$", section))
    if not starts:
        raise ClosureError("incomplete", "governing Issue acceptance criteria are malformed")
    criteria: list[dict[str, Any]] = []
    for index, start in enumerate(starts, start=1):
        end = starts[index].start() if index < len(starts) else len(section)
        item = section[start.start() : end].strip()
        targets = [
            match.group(1).strip()
            for match in re.finditer(r"(?im)(?:^|\b)Verify:[ \t]*(.*)$", item)
            if match.group(1).strip()
        ]
        if not targets:
            raise ClosureError("incomplete", "governing Issue acceptance criteria lack Verify evidence")
        root = (repo_root or Path(__file__).resolve().parents[2]).resolve()
        for target in targets:
            if not is_resolvable_verify_target(target):
                raise ClosureError("incomplete", "governing Issue Verify target is not resolvable")
            path = _verify_target_path(target)
            if path is not None:
                candidate = Path(path)
                if candidate.is_absolute() or ".." in candidate.parts or not (root / candidate).is_file():
                    raise ClosureError("incomplete", "governing Issue Verify target file is unavailable")
        criteria.append(
            {
                "index": index,
                "criterion_sha256": hashlib.sha256(item.encode()).hexdigest(),
                "verify_targets": targets,
            }
        )
    return criteria


def _validate_verify_evidence(
    evidence: object,
    *,
    repository: str,
    pr_number: int,
    pr: Mapping[str, Any],
    issue: Mapping[str, Any],
    issue_number: int,
    head_sha: str,
    body: str,
    repo_root: Path,
) -> dict[str, Any]:
    if not isinstance(evidence, Mapping):
        raise ClosureError("incomplete", "Verify evidence is unavailable")
    required_fields = {
        "schema",
        "verified",
        "head_sha",
        "tier",
        "final_review_rounds",
        "tcd",
        "scope",
        "pr",
        "issue",
        "acceptance_criteria",
    }
    if set(evidence) != required_fields:
        raise ClosureError("incomplete", "Verify evidence schema is incomplete or ambiguous")
    if (
        evidence.get("schema") != VERIFY_EVIDENCE_SCHEMA
        or evidence.get("verified") is not True
        or evidence.get("head_sha") != head_sha
        or not isinstance(evidence.get("tier"), int)
        or isinstance(evidence.get("tier"), bool)
        or evidence.get("tier") not in (1, 2)
        or evidence.get("final_review_rounds") != 0
    ):
        raise ClosureError("incomplete", "Verify evidence is not bound to the light path")
    tcd = evidence.get("tcd")
    if (
        not isinstance(tcd, Mapping)
        or set(tcd) != {"risk_surfaces", "risk_assessment_complete", "stateful_fallback"}
        or tcd.get("risk_surfaces") != []
        or tcd.get("risk_assessment_complete") is not True
        or tcd.get("stateful_fallback") is not False
    ):
        raise ClosureError("incomplete", "Verify evidence does not authenticate the TCD decision")
    base = pr.get("base")
    base_sha = base.get("sha") if isinstance(base, Mapping) else None
    scope = evidence.get("scope")
    if (
        not isinstance(scope, Mapping)
        or set(scope) != {"repository", "pr_number", "base_ref", "base_sha", "head_sha", "governing_issue", "closing_issues"}
        or scope.get("repository") != repository
        or scope.get("pr_number") != pr_number
        or scope.get("base_ref") != "main"
        or scope.get("base_sha") != base_sha
        or scope.get("head_sha") != head_sha
        or scope.get("governing_issue") != issue_number
        or scope.get("closing_issues") != [issue_number]
    ):
        raise ClosureError("incomplete", "Verify evidence does not authenticate the exact scope")
    expected_criteria = _acceptance_criteria(issue.get("body"), repo_root=repo_root)
    pr_evidence = evidence.get("pr")
    expected_pr = {
        "number": pr_number,
        "title_sha256": hashlib.sha256(str(pr.get("title") or "").encode()).hexdigest(),
        "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "updated_at": pr.get("updated_at"),
    }
    if not isinstance(pr_evidence, Mapping) or set(pr_evidence) != set(expected_pr) or dict(pr_evidence) != expected_pr:
        raise ClosureError("incomplete", "Verify evidence is not bound to the PR body revision")
    issue_hashes = _issue_hashes(issue)
    issue_evidence = evidence.get("issue")
    if (
        not isinstance(issue_evidence, Mapping)
        or set(issue_evidence) != {"number", "title_sha256", "body_sha256", "updated_at"}
        or issue_evidence.get("number") != issue_number
        or issue_evidence.get("title_sha256") != issue_hashes["title_sha256"]
        or issue_evidence.get("body_sha256") != issue_hashes["body_sha256"]
        or issue_evidence.get("updated_at") != issue.get("updated_at")
        or not isinstance(issue.get("updated_at"), str)
    ):
        raise ClosureError("incomplete", "Verify evidence is not bound to the governing Issue revision")
    supplied_criteria = evidence.get("acceptance_criteria")
    if not isinstance(supplied_criteria, list) or len(supplied_criteria) != len(expected_criteria):
        raise ClosureError("incomplete", "Verify evidence does not cover every Acceptance Criterion")
    for expected, supplied in zip(expected_criteria, supplied_criteria):
        if (
            not isinstance(supplied, Mapping)
            or set(supplied) != {"index", "criterion_sha256", "verify_targets", "verified", "evidence_sha256"}
            or supplied.get("index") != expected["index"]
            or supplied.get("criterion_sha256") != expected["criterion_sha256"]
            or supplied.get("verify_targets") != expected["verify_targets"]
            or supplied.get("verified") is not True
            or not isinstance(supplied.get("evidence_sha256"), str)
            or HEX64_RE.fullmatch(supplied["evidence_sha256"]) is None
        ):
            raise ClosureError("incomplete", "Verify evidence has incomplete per-criterion authority")
    return json.loads(canonical_json(evidence))


def _pr_contract_revision(
    pr: Mapping[str, Any], checks: Sequence[Mapping[str, Any]], sha: str
) -> dict[str, Any]:
    candidates = [run for run in checks if run.get("name") == PR_CONTRACT_NAME]
    if len(candidates) != 1:
        raise ClosureError("incomplete", "exact pr-contract evidence is unavailable or ambiguous")
    run = candidates[0]
    if run.get("head_sha") != sha:
        raise ClosureError("incomplete", "pr-contract evidence is foreign")
    if not isinstance(run.get("id"), int) or isinstance(run.get("id"), bool) or run["id"] <= 0:
        raise ClosureError("incomplete", "pr-contract evidence identity is malformed")
    if not isinstance(pr.get("updated_at"), str):
        raise ClosureError("incomplete", "PR body revision is unavailable")
    body_revision = _parse_timestamp(pr["updated_at"], "PR body")
    started_at = _parse_timestamp(run.get("started_at"), "pr-contract")
    if started_at <= body_revision:
        raise ClosureError("incomplete", "pr-contract evidence predates the current PR body revision")
    return {
        "check_run_id": run.get("id"),
        "head_sha": sha,
        "started_at": run.get("started_at"),
        "body_revision_updated_at": pr.get("updated_at"),
    }


def _degraded_coordination_snapshot(
    executor: CommandExecutor,
    cwd: Path,
    repository: str,
    issue_number: int,
    fallback_reason: str | None,
    coordination_evidence: str | None,
    caller_agent: str | None,
    caller_session: str | None,
    caller_branch: str | None,
) -> dict[str, Any]:
    if (
        not isinstance(fallback_reason, str)
        or not fallback_reason
        or fallback_reason == "none"
        or not isinstance(coordination_evidence, str)
        or not isinstance(caller_agent, str)
        or not caller_agent
        or not isinstance(caller_session, str)
        or not caller_session
        or not isinstance(caller_branch, str)
        or not caller_branch
    ):
        raise ClosureError("unsupported", "degraded coordination requires explicit caller identity, fallback reason, and receipt")
    match = re.fullmatch(r"github-comment:([1-9][0-9]*)", coordination_evidence)
    if match is None:
        raise ClosureError("unsupported", "degraded coordination evidence must identify a GitHub pickup comment")
    comment_id = int(match.group(1))
    result = _run(
        executor,
        cwd,
        [
            "gh",
            "api",
            "--hostname",
            GITHUB_HOST,
            "--method",
            "GET",
            "--paginate",
            "--slurp",
            f"repos/{repository}/issues/{issue_number}/comments?per_page=100",
        ],
    )
    try:
        pages = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ClosureError("unknown", "degraded coordination comments were not JSON") from exc
    if not isinstance(pages, list):
        raise ClosureError("incomplete", "degraded coordination comments are incomplete")
    comments: list[Mapping[str, Any]] = []
    for page in pages:
        if not isinstance(page, list):
            raise ClosureError("incomplete", "degraded coordination comments are malformed")
        for item in page:
            if isinstance(item, Mapping):
                comments.append(item)
    comment = next((item for item in comments if item.get("id") == comment_id), None)
    if comment is None:
        raise ClosureError("incomplete", "degraded coordination pickup receipt is unavailable")
    user = comment.get("user")
    body = comment.get("body")
    issue_url = comment.get("issue_url")
    if not isinstance(body, str):
        raise ClosureError("incomplete", "degraded coordination pickup receipt is malformed")
    receipt_match = PICKUP_RECEIPT_RE.fullmatch(body)
    if (
        comment.get("id") != comment_id
        or issue_url != f"https://api.github.com/repos/{repository}/issues/{issue_number}"
        or receipt_match is None
        or not isinstance(user, Mapping)
        or not isinstance(user.get("login"), str)
        or not user["login"]
        or not isinstance(comment.get("created_at"), str)
    ):
        raise ClosureError("incomplete", "degraded coordination pickup receipt is not authenticated")
    receipt = receipt_match.groupdict()
    if (
        receipt["agent"] != caller_agent
        or receipt["session"] != caller_session
        or receipt["branch"] != caller_branch
        or receipt["worktree"] != str(cwd)
        or receipt["mode"] != DEGRADED_MODE
        or receipt["reason"] != fallback_reason
        or int(receipt["issue"]) != issue_number
    ):
        raise ClosureError("incomplete", "degraded coordination caller does not match the pickup receipt")
    pickup_receipts: list[tuple[datetime, int]] = []
    for candidate in comments:
        candidate_body = candidate.get("body")
        candidate_created_at = candidate.get("created_at")
        if not isinstance(candidate_body, str) or not isinstance(candidate_created_at, str):
            continue
        candidate_match = PICKUP_RECEIPT_RE.fullmatch(candidate_body)
        if candidate_match is None or candidate_match.group("mode") != DEGRADED_MODE or int(candidate_match.group("issue")) != issue_number:
            continue
        candidate_id = candidate.get("id")
        if not isinstance(candidate_id, int):
            continue
        pickup_receipts.append((_parse_timestamp(candidate_created_at, "degraded coordination receipt"), candidate_id))
    if not pickup_receipts or max(pickup_receipts, key=lambda item: (item[0], item[1]))[1] != comment_id:
        raise ClosureError("incomplete", "degraded coordination pickup receipt is not the current claimant authority")
    _parse_timestamp(comment["created_at"], "degraded coordination receipt")
    return {
        "mode": DEGRADED_MODE,
        "fallback_reason": fallback_reason,
        "evidence": coordination_evidence,
        "comment_id": comment_id,
        "comment_created_at": comment["created_at"],
        "comment_author": user["login"],
        "caller_agent": caller_agent,
        "caller_session": caller_session,
        "caller_branch": caller_branch,
    }


def _dispatcher_snapshot(
    executor: CommandExecutor,
    cwd: Path,
    task_id: str | None,
    *,
    repository: str,
    issue_number: int,
    pr_number: int,
    allow_expired: bool = False,
) -> dict[str, str] | None:
    if task_id is None:
        return None
    task, _, lease = _dispatcher_inspect(executor, cwd, task_id)
    return _dispatcher_snapshot_from_task(
        task,
        task_id,
        repository=repository,
        issue_number=issue_number,
        pr_number=pr_number,
        allow_expired=allow_expired,
        lease=lease,
    )


def _dispatcher_snapshot_from_task(
    task: Mapping[str, Any],
    task_id: str,
    *,
    repository: str,
    issue_number: int,
    pr_number: int,
    allow_expired: bool = False,
    lease: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    if task.get("task_id") != task_id:
        raise ClosureError("unknown", "dispatcher task identity was not exact")
    if task.get("repo") != repository or task.get("issue_number") != issue_number:
        raise ClosureError("incomplete", "dispatcher task is not bound to the governing repository and Issue")
    holder, lease_id, linked_pr = task.get("claimed_by"), task.get("lease_id"), task.get("linked_pr")
    lease_expires_at = task.get("lease_expires_at")
    if task.get("status") != "claimed" or not isinstance(holder, str) or not holder or not isinstance(lease_id, str) or not lease_id:
        raise ClosureError("incomplete", "dispatcher task has no active lease-holder identity")
    if not isinstance(lease_expires_at, str):
        raise ClosureError("incomplete", "dispatcher lease expiry is unavailable")
    if (
        not isinstance(lease, Mapping)
        or lease.get("lease_id") != lease_id
        or lease.get("holder") != holder
        or lease.get("resource") != f"issue:{issue_number}"
        or lease.get("expires_at") != lease_expires_at
        or lease.get("released_at") is not None
    ):
        raise ClosureError("incomplete", "dispatcher lease row is not the exact unreleased active lease")
    lease_expiry = _parse_timestamp(lease_expires_at, "dispatcher lease")
    if not allow_expired and lease_expiry <= datetime.now(timezone.utc):
        raise ClosureError("incomplete", "dispatcher lease is expired")
    if str(linked_pr) != str(pr_number):
        raise ClosureError("incomplete", "dispatcher task is not linked to the exact PR")
    return {
        "task_id": task_id,
        "repository": repository,
        "issue_number": str(issue_number),
        "lease_holder": holder,
        "lease_id": lease_id,
        "lease_expires_at": lease_expires_at,
        "linked_pr": str(pr_number),
    }


def _dispatcher_inspect(
    executor: CommandExecutor, cwd: Path, task_id: str
) -> tuple[Mapping[str, Any], list[Mapping[str, Any]], Mapping[str, Any] | None]:
    result = _run(
        executor,
        cwd,
        [sys.executable, "-m", "app.dispatcher", "show", task_id, "--events", "--json"],
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ClosureError("unknown", "dispatcher inspection was not JSON") from exc
    task = payload.get("task") if isinstance(payload, Mapping) else None
    events = payload.get("events") if isinstance(payload, Mapping) else None
    lease = payload.get("lease") if isinstance(payload, Mapping) else None
    if (
        not isinstance(task, Mapping)
        or not isinstance(events, list)
        or not all(isinstance(row, Mapping) for row in events)
        or (lease is not None and not isinstance(lease, Mapping))
    ):
        raise ClosureError("unknown", "dispatcher inspection was malformed")
    return task, events, lease


def _validate_claimant_history(
    events: Sequence[Mapping[str, Any]], dispatcher: Mapping[str, Any]
) -> None:
    task_id = dispatcher.get("task_id")
    holder = dispatcher.get("lease_holder")
    lease_id = dispatcher.get("lease_id")
    claims = [
        row
        for row in events
        if row.get("task_id") == task_id
        and row.get("event_type") == "task.claimed"
        and row.get("actor") == holder
        and row.get("lease_id") == lease_id
    ]
    if len(claims) != 1:
        raise ClosureError("incomplete", "dispatcher exact claimant event is unavailable or ambiguous")
    claim_index = next(index for index, row in enumerate(events) if row is claims[0])
    for row in events[claim_index + 1 :]:
        if row.get("task_id") != task_id:
            continue
        if row.get("event_type") in {"task.claimed", "task.released", "task.completed"}:
            raise ClosureError("drift", "dispatcher claimant history changed before completion")


def _planned_release_index(
    events: Sequence[Mapping[str, Any]], dispatcher: Mapping[str, Any]
) -> int:
    task_id = dispatcher.get("task_id")
    lease_id = dispatcher.get("lease_id")
    releases = [
        (index, row)
        for index, row in enumerate(events)
        if row.get("task_id") == task_id
        and row.get("event_type") == "task.released"
        and row.get("lease_id") == lease_id
        and isinstance(row.get("actor"), str)
        and row.get("actor")
        and isinstance(row.get("payload"), Mapping)
        and row["payload"].get("reason") == "expired"
    ]
    if len(releases) != 1:
        raise ClosureError("incomplete", "dispatcher planned lease expiry-release evidence is unavailable or ambiguous")
    release_index, release = releases[0]
    release_timestamp = release.get("timestamp")
    planned_expiry = dispatcher.get("lease_expires_at")
    if not isinstance(release_timestamp, str) or not isinstance(planned_expiry, str):
        raise ClosureError("incomplete", "dispatcher expiry-release evidence lacks timestamps")
    if _parse_timestamp(release_timestamp, "dispatcher expiry release") < _parse_timestamp(planned_expiry, "dispatcher lease"):
        raise ClosureError("incomplete", "dispatcher expiry-release predates the planned lease expiry")
    return release_index


def _dispatcher_completion(
    executor: CommandExecutor,
    cwd: Path,
    dispatcher: Mapping[str, Any],
    *,
    repository: str,
    issue_number: int,
    pr_number: int,
    allow_expired_claim: bool = False,
) -> dict[str, str]:
    task_id = dispatcher.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise ClosureError("unknown", "dispatcher completion identity is malformed")
    task, events, lease = _dispatcher_inspect(executor, cwd, task_id)
    if (
        not isinstance(task, Mapping)
        or task.get("task_id") != task_id
        or task.get("repo") != repository
        or task.get("issue_number") != issue_number
        or str(task.get("linked_pr")) != str(pr_number)
    ):
        raise ClosureError("incomplete", "dispatcher completion task identity drifted")
    if task.get("status") == "claimed":
        active = _dispatcher_snapshot_from_task(
            task,
            task_id,
            repository=repository,
            issue_number=issue_number,
            pr_number=pr_number,
            allow_expired=allow_expired_claim,
            lease=lease,
        )
        if active != dispatcher:
            raise ClosureError("drift", "dispatcher task or lease-holder drifted")
        _validate_claimant_history(events, dispatcher)
        return {"status": "claimed", **active}
    if task.get("status") == "ready":
        if any(task.get(field) is not None for field in ("claimed_by", "lease_id", "lease_expires_at")):
            raise ClosureError("incomplete", "dispatcher ready task retains lease-holder identity")
        release_index = _planned_release_index(events, dispatcher)
        for row in events[release_index + 1 :]:
            if row.get("task_id") == task_id and row.get("event_type") == "task.claimed":
                raise ClosureError("drift", "dispatcher task was claimed after the planned lease was reclaimed")
        return {"status": "released", **dispatcher}
    if task.get("status") != "completed" or task.get("claimed_by") is not None or task.get("lease_id") is not None:
        raise ClosureError("incomplete", "dispatcher completion is unavailable")

    matches = [row for row in events if isinstance(row, Mapping) and row.get("task_id") == task_id and row.get("event_type") == "task.completed" and row.get("actor") == dispatcher.get("lease_holder") and row.get("lease_id") == dispatcher.get("lease_id")]
    if len(matches) != 1:
        raise ClosureError("incomplete", "dispatcher completion receipt is unavailable or ambiguous")
    return {
        "status": "completed",
        **{
            key: str(dispatcher[key])
            for key in (
                "task_id",
                "repository",
                "issue_number",
                "lease_holder",
                "lease_id",
                "linked_pr",
            )
        },
    }


def _dispatcher_reclaim(
    executor: CommandExecutor,
    cwd: Path,
    dispatcher: Mapping[str, Any],
    *,
    repository: str,
    issue_number: int,
    pr_number: int,
) -> dict[str, str]:
    task_id = dispatcher.get("task_id")
    holder = dispatcher.get("lease_holder")
    old_lease_id = dispatcher.get("lease_id")
    if (
        not isinstance(task_id, str)
        or not task_id
        or not isinstance(holder, str)
        or not holder
        or not isinstance(old_lease_id, str)
        or not old_lease_id
    ):
        raise ClosureError("incomplete", "dispatcher planned lease identity is malformed")
    result = _run(
        executor,
        cwd,
        [sys.executable, "-m", "app.dispatcher", "claim", task_id, "--agent", holder, "--json"],
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ClosureError("unknown", "dispatcher lease recovery was not JSON") from exc
    task = payload.get("task") if isinstance(payload, Mapping) else None
    lease = payload.get("lease") if isinstance(payload, Mapping) else None
    if (
        not isinstance(task, Mapping)
        or not isinstance(lease, Mapping)
        or task.get("task_id") != task_id
        or task.get("repo") != repository
        or task.get("issue_number") != issue_number
        or str(task.get("linked_pr")) != str(pr_number)
        or task.get("status") != "claimed"
        or task.get("claimed_by") != holder
        or not isinstance(task.get("lease_id"), str)
        or task.get("lease_id") == old_lease_id
        or task.get("lease_id") != lease.get("lease_id")
        or lease.get("holder") != holder
        or lease.get("resource") != f"issue:{issue_number}"
    ):
        raise ClosureError("drift", "dispatcher lease recovery was not an exact same-agent claim")
    recovered_task, recovered_events, recovered_lease = _dispatcher_inspect(executor, cwd, task_id)
    recovered = _dispatcher_snapshot_from_task(
        recovered_task,
        task_id,
        repository=repository,
        issue_number=issue_number,
        pr_number=pr_number,
        lease=recovered_lease,
    )
    if recovered["lease_holder"] != holder or recovered["lease_id"] != task["lease_id"]:
        raise ClosureError("drift", "dispatcher lease recovery readback drifted")
    release_index = _planned_release_index(recovered_events, dispatcher)
    recovery_claims = [
        (index, row)
        for index, row in enumerate(recovered_events)
        if row.get("task_id") == task_id
        and row.get("event_type") == "task.claimed"
        and row.get("actor") == recovered["lease_holder"]
        and row.get("lease_id") == recovered["lease_id"]
    ]
    if len(recovery_claims) != 1 or recovery_claims[0][0] <= release_index:
        raise ClosureError("incomplete", "dispatcher recovery claimant event is unavailable or out of order")
    recovery_claim_index = recovery_claims[0][0]
    for row in recovered_events[release_index + 1 : recovery_claim_index]:
        if row.get("task_id") == task_id and row.get("event_type") in {
            "task.claimed",
            "task.released",
            "task.completed",
        }:
            raise ClosureError("drift", "dispatcher replacement claimant history changed before recovery")
    _validate_claimant_history(recovered_events, recovered)
    return recovered


def _reject_dispatcher_lease_for_fallback(
    executor: CommandExecutor,
    cwd: Path,
    *,
    repository: str,
    issue_number: int,
    pr_number: int,
) -> None:
    task_id = github_issue_task_id(repository, issue_number)
    result = executor.run(
        [sys.executable, "-m", "app.dispatcher", "show", task_id, "--events", "--json"],
        cwd=cwd,
    )
    if result.returncode:
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ClosureError("unknown", "dispatcher fallback conflict readback was not JSON", result) from exc
        error = payload.get("error") if isinstance(payload, Mapping) else None
        if isinstance(error, str) and (
            error == f"Task {task_id} not found"
            or error.startswith("dispatcher not initialised")
        ):
            return
        raise ClosureError("unknown", "dispatcher fallback conflict readback was unavailable", result)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ClosureError("unknown", "dispatcher fallback conflict readback was not JSON", result) from exc
    task = payload.get("task") if isinstance(payload, Mapping) else None
    if not isinstance(task, Mapping):
        raise ClosureError("unknown", "dispatcher fallback conflict readback was malformed", result)
    if (
        task.get("task_id") != task_id
        or task.get("repo") != repository
        or task.get("issue_number") != issue_number
    ):
        raise ClosureError("drift", "dispatcher fallback task identity drifted")
    linked_pr = task.get("linked_pr")
    if linked_pr is not None and str(linked_pr) != str(pr_number):
        raise ClosureError("drift", "dispatcher fallback task is linked to a different PR")
    if task.get("status") == "claimed":
        if any(
            not isinstance(task.get(field), str) or not task.get(field)
            for field in ("claimed_by", "lease_id", "lease_expires_at")
        ):
            raise ClosureError("incomplete", "dispatcher fallback task has malformed active lease identity")
        raise ClosureError("drift", "fallback coordination conflicts with the current dispatcher lease")
    if any(task.get(field) is not None for field in ("claimed_by", "lease_id", "lease_expires_at")):
        raise ClosureError("incomplete", "dispatcher fallback task retains lease identity")


def _dispatcher_cleanup_guard(
    executor: CommandExecutor,
    cwd: Path,
    *,
    action: str,
    task_id: str,
    owner: str,
    token: str | None = None,
) -> str | None:
    argv = [
        sys.executable,
        "-m",
        "app.dispatcher",
        "cleanup-guard",
        action,
        "--task-id",
        task_id,
        "--owner",
        owner,
    ]
    if action in {"acquire", "refresh"}:
        argv.extend(["--ttl-seconds", str(CLEANUP_GUARD_TTL_SECONDS)])
    if action in {"refresh", "release"} and token is not None:
        argv.extend(["--token", token])
    elif action == "release":
        raise ClosureError("unknown", "dispatcher cleanup guard release token is missing")
    elif action not in {"acquire", "refresh"}:
        raise ClosureError("unknown", "unknown dispatcher cleanup guard action")
    argv.append("--json")
    result = _run(executor, cwd, argv)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ClosureError("unknown", "dispatcher cleanup guard was not JSON", result) from exc
    if not isinstance(payload, Mapping) or payload.get("ok") is not True:
        raise ClosureError("unknown", "dispatcher cleanup guard response was malformed", result)
    if action in {"acquire", "refresh"}:
        guard = payload.get("guard")
        if (
            not isinstance(guard, Mapping)
            or guard.get("task_id") != task_id
            or guard.get("owner") != owner
            or not isinstance(guard.get("token"), str)
            or not guard["token"]
        ):
            raise ClosureError("unknown", "dispatcher cleanup guard identity was malformed", result)
        return guard["token"]
    if payload.get("released") is not True or payload.get("task_id") != task_id:
        raise ClosureError("unknown", "dispatcher cleanup guard release was not confirmed", result)
    return None


def _require_bounded_cleanup_executor(executor: CommandExecutor) -> None:
    """Refuse degraded cleanup unless every guarded command ends before expiry."""
    timeout_seconds = getattr(executor, "timeout_seconds", None)
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
        or timeout_seconds > CLEANUP_GUARD_MAX_COMMAND_SECONDS
    ):
        raise ClosureError(
            "unsupported",
            "degraded cleanup requires a bounded command timeout below the cleanup guard safety window",
        )


def _closed_event_evidence(
    executor: CommandExecutor, cwd: Path, repository: str, number: int
) -> list[dict[str, Any]]:
    owner, name = repository.split("/", 1)
    query = """
      query($owner: String!, $name: String!, $number: Int!) {
        repository(owner: $owner, name: $name) {
          issue(number: $number) {
            state
            closedAt
            timelineItems(last: 1, itemTypes: [CLOSED_EVENT]) {
              nodes {
                ... on ClosedEvent {
                  __typename
                  createdAt
                  actor { login }
                  closer {
                    __typename
                    ... on PullRequest {
                      number
                      mergedAt
                      mergeCommit { oid }
                      repository { nameWithOwner }
                    }
                  }
                }
              }
              pageInfo { hasNextPage }
            }
          }
        }
      }
    """
    result = _run(
        executor,
        cwd,
        [
            "gh",
            "api",
            "--hostname",
            GITHUB_HOST,
            "graphql",
            "-f",
            f"query={query}",
            "-f",
            f"owner={owner}",
            "-f",
            f"name={name}",
            "-F",
            f"number={number}",
        ],
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ClosureError("unknown", "GitHub closed-event evidence was not JSON") from exc
    data = payload.get("data") if isinstance(payload, Mapping) else None
    repository_row = data.get("repository") if isinstance(data, Mapping) else None
    issue = repository_row.get("issue") if isinstance(repository_row, Mapping) else None
    timeline = issue.get("timelineItems") if isinstance(issue, Mapping) else None
    issue_state = issue.get("state") if isinstance(issue, Mapping) else None
    issue_closed_at = issue.get("closedAt") if isinstance(issue, Mapping) else None
    nodes = timeline.get("nodes") if isinstance(timeline, Mapping) else None
    if not isinstance(nodes, list) or len(nodes) != 1 or issue_state != "CLOSED":
        raise ClosureError("incomplete", "GitHub closed-event evidence is unavailable or incomplete")
    if not isinstance(issue_closed_at, str):
        raise ClosureError("incomplete", "GitHub Issue closure timestamp is unavailable")
    issue_closed_time = _parse_timestamp(issue_closed_at, "GitHub Issue closure")
    evidence: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, Mapping):
            raise ClosureError("incomplete", "GitHub closed-event evidence is malformed")
        if node.get("__typename") != "ClosedEvent":
            raise ClosureError("incomplete", "GitHub closed-event evidence is not a ClosedEvent")
        created_at = node.get("createdAt")
        actor = node.get("actor")
        actor_login = actor.get("login") if isinstance(actor, Mapping) else None
        closer = node.get("closer")
        closer_evidence: dict[str, Any] | None = None
        if closer is not None:
            if not isinstance(closer, Mapping) or not isinstance(closer.get("__typename"), str):
                raise ClosureError("incomplete", "GitHub closer evidence is malformed")
            closer_evidence = {"type": closer["__typename"]}
            if closer["__typename"] == "PullRequest":
                merge_commit = closer.get("mergeCommit")
                closer_repository = closer.get("repository")
                if (
                    not isinstance(closer.get("number"), int)
                    or isinstance(closer.get("number"), bool)
                    or closer["number"] <= 0
                    or not isinstance(closer.get("mergedAt"), str)
                    or not isinstance(merge_commit, Mapping)
                    or not isinstance(merge_commit.get("oid"), str)
                    or not SHA_RE.fullmatch(merge_commit["oid"])
                    or not isinstance(closer_repository, Mapping)
                    or closer_repository.get("nameWithOwner") != repository
                ):
                    raise ClosureError("incomplete", "GitHub pull-request closer evidence is malformed")
                _parse_timestamp(closer["mergedAt"], "GitHub closer merge")
                closer_evidence.update(
                    {
                        "number": closer["number"],
                        "repository": closer_repository["nameWithOwner"],
                        "merged_at": closer["mergedAt"],
                        "merge_sha": merge_commit["oid"],
                    }
                )
        if not isinstance(created_at, str) or not actor_login:
            raise ClosureError("incomplete", "GitHub closed-event actor or timestamp is unavailable")
        created_time = _parse_timestamp(created_at, "GitHub closed event")
        if abs(issue_closed_time - created_time).total_seconds() > 1:
            raise ClosureError("incomplete", "GitHub Issue closure timestamp is not authoritative")
        evidence.append(
            {
                "created_at": created_at,
                "actor": actor_login,
                "closer": closer_evidence,
                "closed_at": issue_closed_at,
            }
        )
    return evidence


def _closure_evidence(
    executor: CommandExecutor,
    cwd: Path,
    repository: str,
    issue_number: int,
    events: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    del events
    return _closed_event_evidence(executor, cwd, repository, issue_number)


def _validate_closure_attribution(
    events: Sequence[Mapping[str, Any]],
    closed_evidence: Sequence[Mapping[str, Any]],
    repository: str,
    issue_number: int,
    merge_sha: str,
    pr_number: int,
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
    if len(closed_evidence) != 1:
        raise ClosureError(
            "incomplete",
            "exact closing Issue attribution was not proven: current authoritative evidence is unavailable",
        )
    authoritative = closed_evidence[0]
    authoritative_actor = authoritative.get("actor")
    authoritative_created_at = authoritative.get("created_at")
    if not isinstance(authoritative_actor, str) or not authoritative_actor or not isinstance(authoritative_created_at, str):
        raise ClosureError("incomplete", "current authoritative close lacks actor or timestamp")
    authoritative_time = _parse_timestamp(authoritative_created_at, "GitHub closed event")
    authoritative_closer = authoritative.get("closer")
    exact_pr_closer = isinstance(authoritative_closer, Mapping) and (
        authoritative_closer.get("type") == "PullRequest"
        and authoritative_closer.get("number") == pr_number
        and authoritative_closer.get("repository") == repository
        and authoritative_closer.get("merge_sha") == merge_sha
        and isinstance(authoritative_closer.get("merged_at"), str)
        and _parse_timestamp(authoritative_closer["merged_at"], "GitHub closer merge") <= authoritative_time
    )
    if len(matches) == 1:
        current_merge = matches[0]
        current_actor = current_merge.get("actor")
        current_actor_login = current_actor.get("login") if isinstance(current_actor, Mapping) else None
        current_created_at = current_merge.get("created_at")
        if (
            exact_pr_closer
            and current_actor_login == authoritative_actor
            and isinstance(current_created_at, str)
            and _parse_timestamp(current_created_at, "REST closed event") == authoritative_time
        ):
            return "GitHub-native closing keyword and exact merge event"
    current_null_close: list[Mapping[str, Any]] = []
    for event in events:
        if event.get("event") != "closed" or event.get("commit_id") is not None:
            continue
        close_actor = event.get("actor")
        close_actor_login = close_actor.get("login") if isinstance(close_actor, Mapping) else None
        close_created_at = event.get("created_at")
        if not isinstance(close_actor_login, str) or not close_actor_login or not isinstance(close_created_at, str):
            raise ClosureError("incomplete", "null-commit close lacks authoritative actor or timestamp")
        if (
            close_actor_login == authoritative_actor
            and _parse_timestamp(close_created_at, "REST closed event") == authoritative_time
        ):
            current_null_close.append(event)
    if len(current_null_close) != 1:
        raise ClosureError("incomplete", "exact closing Issue attribution is unavailable or ambiguous")
    if exact_pr_closer:
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
    closing_references = _closing_issue_references(executor, cwd, request.repository, request.pr_number)
    if closing_references != [issue_number]:
        raise ClosureError("unsupported", "PR GitHub closing references are not the exact singleton Issue")
    issue = _issue(executor, cwd, request.repository, issue_number)
    _issue_hashes(issue)
    labels = sorted(str(item.get("name") if isinstance(item, dict) else item) for item in issue.get("labels", []))
    if str(issue.get("state", "")).lower() != "open" or "agent:in-progress" not in labels:
        raise ClosureError("incomplete", "governing Issue is not the active open claim")
    verify_evidence = _validate_verify_evidence(
        request.verify_evidence,
        repository=request.repository,
        pr_number=request.pr_number,
        pr=pr,
        issue=issue,
        issue_number=issue_number,
        head_sha=sha,
        body=body,
        repo_root=cwd,
    )
    checks = _checks(executor, cwd, request.repository, sha)
    statuses = _statuses(executor, cwd, request.repository, sha)
    required_checks = _required_check_authority(executor, cwd, request.repository)
    required_evidence = _required_check_evidence(checks, statuses, required_checks)
    pr_contract = _pr_contract_revision(pr, checks, sha)
    if request.dispatcher_task_id is None:
        if request.coordination_mode != DEGRADED_MODE:
            raise ClosureError("unsupported", "closure requires explicit dispatcher or degraded coordination evidence")
        dispatcher = None
        coordination = _degraded_coordination_snapshot(
            executor,
            cwd,
            request.repository,
            issue_number,
            request.fallback_reason,
            request.coordination_evidence,
            request.caller_agent,
            request.caller_session,
            request.caller_branch,
        )
    else:
        if request.coordination_mode not in (None, DISPATCHER_MODE):
            raise ClosureError("unsupported", "dispatcher task conflicts with degraded coordination mode")
        dispatcher = _dispatcher_snapshot(
            executor,
            cwd,
            request.dispatcher_task_id,
            repository=request.repository,
            issue_number=issue_number,
            pr_number=request.pr_number,
        )
        coordination = {"mode": DISPATCHER_MODE, "dispatcher": dispatcher}
    return {
        "pr": pr,
        "issue": issue,
        "issue_labels": labels,
        "checks": checks,
        "statuses": statuses,
        "required_checks": required_checks,
        "required_evidence": required_evidence,
        "verify_evidence": verify_evidence,
        "pr_contract": pr_contract,
        "coordination": coordination,
        "closing_references": closing_references,
        "head_sha": sha,
        "issue_number": issue_number,
        "dispatcher": dispatcher,
    }


def build_closure_plan(request: ClosureRequest, *, executor: CommandExecutor | None = None) -> dict[str, Any]:
    runner = executor or SubprocessExecutor()
    before = _snapshot(request, runner)
    plan = {
        "schema": PLAN_SCHEMA, "repository": request.repository, "worktree": str(request.worktree.resolve()),
        "pr_number": request.pr_number, "base_sha": before["pr"]["base"].get("sha"), "head_sha": before["head_sha"],
        "title_sha256": hashlib.sha256(str(before["pr"].get("title") or "").encode()).hexdigest(),
        "body_sha256": hashlib.sha256(str(before["pr"].get("body") or "").encode()).hexdigest(),
        "pr_body_revision": before["pr_contract"]["body_revision_updated_at"],
        "governing_issue": before["issue_number"], "closing_issues": [before["issue_number"]],
        "closing_issue": {"number": before["issue_number"], **_issue_hashes(before["issue"])},
        "tier": before["verify_evidence"]["tier"], "final_review_rounds": 0, "verify_evidence": before["verify_evidence"],
        "checks": [_check_snapshot(item) for item in before["checks"]],
        "required_checks": before["required_checks"], "required_check_evidence": before["required_evidence"],
        "pr_contract": before["pr_contract"],
        "coordination": before["coordination"],
        "merge": {"method": "squash", "commit_title": f"Merge PR #{request.pr_number}", "commit_message": "Governed light-path closure."},
        "post_merge": {"remove_label_prefix": "agent:", "remove_label_prefixes": ["agent:", "action:"], "dispatcher": before["dispatcher"], "remaining_action": "post-merge-owner-doc"},
    }
    plan["plan_sha256"] = closure_plan_hash(plan)
    return plan


def _validate_planned_pr(
    pr: Mapping[str, Any], plan: Mapping[str, Any], *, phase: str, check_revision: bool = True
) -> None:
    base = pr.get("base")
    head = pr.get("head")
    if (
        pr.get("number") != plan.get("pr_number")
        or str(pr.get("state", "")).lower() not in {"open", "closed"}
        or not isinstance(base, Mapping)
        or base.get("ref") != "main"
        or base.get("repo", {}).get("full_name") != plan.get("repository")
        or not isinstance(head, Mapping)
        or head.get("repo", {}).get("full_name") != plan.get("repository")
        or head.get("sha") != plan.get("head_sha")
        or hashlib.sha256(str(pr.get("body") or "").encode()).hexdigest() != plan.get("body_sha256")
        or hashlib.sha256(str(pr.get("title") or "").encode()).hexdigest() != plan.get("title_sha256")
        or (check_revision and pr.get("updated_at") != plan.get("pr_body_revision"))
    ):
        raise ClosureError("drift", f"{phase} PR body/head authority drifted")
    if _issue_number(str(pr.get("body") or "")) != plan.get("governing_issue"):
        raise ClosureError("drift", f"{phase} PR closing Issue authority drifted")


def _validated(plan: Mapping[str, Any], expected: str) -> dict[str, Any]:
    value = json.loads(canonical_json(plan))
    if value.get("schema") != PLAN_SCHEMA or value.get("plan_sha256") != expected or closure_plan_hash(value) != expected:
        raise ClosureError("drift", "closure plan hash mismatch")
    closing_issue = value.get("closing_issue")
    post_merge = value.get("post_merge")
    coordination = value.get("coordination")
    if (
        value.get("tier") not in (1, 2)
        or value.get("final_review_rounds") != 0
        or value.get("closing_issues") != [value.get("governing_issue")]
        or not isinstance(closing_issue, Mapping)
        or closing_issue.get("number") != value.get("governing_issue")
        or not all(isinstance(closing_issue.get(field), str) and re.fullmatch(r"[0-9a-f]{64}", closing_issue[field]) for field in ("title_sha256", "body_sha256"))
        or not isinstance(value.get("required_checks"), list)
        or not isinstance(value.get("required_check_evidence"), list)
        or not isinstance(value.get("checks"), list)
        or not isinstance(value.get("pr_body_revision"), str)
        or not isinstance(value.get("pr_contract"), Mapping)
        or not isinstance(value.get("verify_evidence"), Mapping)
        or not isinstance(post_merge, Mapping)
        or post_merge.get("remove_label_prefixes") != ["agent:", "action:"]
        or not isinstance(coordination, Mapping)
        or coordination.get("mode") not in {DISPATCHER_MODE, DEGRADED_MODE}
    ):
        raise ClosureError("unsupported", "plan is outside the light path")
    if coordination["mode"] == DISPATCHER_MODE:
        if not isinstance(coordination.get("dispatcher"), Mapping) or post_merge.get("dispatcher") != coordination["dispatcher"]:
            raise ClosureError("unsupported", "dispatcher coordination evidence is incomplete")
    else:
        if (
            post_merge.get("dispatcher") is not None
            or set(coordination) != {"mode", "fallback_reason", "evidence", "comment_id", "comment_created_at", "comment_author", "caller_agent", "caller_session", "caller_branch"}
            or not isinstance(coordination.get("fallback_reason"), str)
            or not coordination["fallback_reason"]
            or not isinstance(coordination.get("evidence"), str)
            or not isinstance(coordination.get("comment_id"), int)
            or not isinstance(coordination.get("comment_created_at"), str)
            or not isinstance(coordination.get("comment_author"), str)
            or not isinstance(coordination.get("caller_agent"), str)
            or not coordination["caller_agent"]
            or not isinstance(coordination.get("caller_session"), str)
            or not coordination["caller_session"]
            or not isinstance(coordination.get("caller_branch"), str)
            or not coordination["caller_branch"]
        ):
            raise ClosureError("unsupported", "degraded coordination evidence is incomplete")
    return value


def apply_closure_plan(plan: Mapping[str, Any], *, expected_plan_sha256: str, executor: CommandExecutor | None = None) -> dict[str, Any]:
    value = _validated(plan, expected_plan_sha256); runner = executor or SubprocessExecutor(); cwd = Path(value["worktree"])
    dispatcher = value["post_merge"].get("dispatcher") or {}
    task_id = dispatcher.get("task_id") if isinstance(dispatcher, Mapping) else None
    coordination = value["coordination"]
    if coordination["mode"] == DEGRADED_MODE:
        _require_bounded_cleanup_executor(runner)
        current_coordination = _degraded_coordination_snapshot(
            runner,
            cwd,
            str(value["repository"]),
            int(value["governing_issue"]),
            coordination.get("fallback_reason"),
            coordination.get("evidence"),
            coordination.get("caller_agent"),
            coordination.get("caller_session"),
            coordination.get("caller_branch"),
        )
        if current_coordination != coordination:
            raise ClosureError("drift", "degraded coordination pickup authority drifted")
        _reject_dispatcher_lease_for_fallback(
            runner,
            cwd,
            repository=str(value["repository"]),
            issue_number=int(value["governing_issue"]),
            pr_number=int(value["pr_number"]),
        )
    current_pr = _pr(runner, cwd, value["repository"], value["pr_number"])
    if str(current_pr.get("state", "")).lower() == "closed" and current_pr.get("merged_at") is not None:
        if current_pr.get("merge_commit_sha") is None or current_pr.get("head", {}).get("sha") != value["head_sha"]:
            raise ClosureError("unknown", "closed PR does not prove the planned exact merge")
        _validate_planned_pr(current_pr, value, phase="post-merge", check_revision=False)
        if _closing_issue_references(runner, cwd, value["repository"], int(value["pr_number"])) != [value["governing_issue"]]:
            raise ClosureError("incomplete", "post-merge PR closing references are not the planned singleton")
        current = {"pr": current_pr, "issue": _issue(runner, cwd, value["repository"], value["governing_issue"]), "issue_labels": [], "checks": [], "head_sha": value["head_sha"], "issue_number": value["governing_issue"], "dispatcher": dispatcher}
        _validate_planned_issue(current["issue"], value, phase="post-merge")
        if str(current["issue"].get("state", "")).lower() != "closed":
            raise ClosureError("incomplete", "merged PR exists but GitHub-native Issue closure is absent")
        events = _issue_events(runner, cwd, value["repository"], int(value["governing_issue"]))
        attribution = _validate_closure_attribution(
            events,
            _closure_evidence(
                runner, cwd, str(value["repository"]), int(value["governing_issue"]), events
            ),
            str(value["repository"]),
            int(value["governing_issue"]),
            str(current_pr["merge_commit_sha"]),
            int(value["pr_number"]),
        )
        current["closure_attribution"] = attribution
        return _finish_cleanup(value, current, runner, cwd, reconciled=True)
    request = ClosureRequest(
        value["repository"],
        cwd,
        int(value["pr_number"]),
        value["verify_evidence"],
        task_id,
        coordination["mode"],
        coordination.get("fallback_reason"),
        coordination.get("evidence"),
        coordination.get("caller_agent"),
        coordination.get("caller_session"),
        coordination.get("caller_branch"),
    )
    planned_dispatcher = (
        _dispatcher_snapshot(
            runner,
            cwd,
            task_id,
            repository=str(value["repository"]),
            issue_number=int(value["governing_issue"]),
            pr_number=int(value["pr_number"]),
        )
        if task_id
        else {}
    )
    if planned_dispatcher != dispatcher:
        raise ClosureError("drift", "dispatcher task or lease-holder drifted before merge")
    current = _snapshot(request, runner)
    _validate_planned_issue(current["issue"], value, phase="pre-merge")
    if current["head_sha"] != value["head_sha"] or current["issue_number"] != value["governing_issue"] or current["pr"].get("base", {}).get("sha") != value["base_sha"] or hashlib.sha256(str(current["pr"].get("body") or "").encode()).hexdigest() != value["body_sha256"] or hashlib.sha256(str(current["pr"].get("title") or "").encode()).hexdigest() != value["title_sha256"]:
        raise ClosureError("drift", "mutable PR or Issue authority drifted before merge")
    observed_checks = [_check_snapshot(item) for item in current["checks"]]
    if observed_checks != value["checks"]:
        raise ClosureError("drift", "current-head check evidence drifted before merge")
    if (
        current["required_checks"] != value["required_checks"]
        or current["required_evidence"] != value["required_check_evidence"]
        or current["pr_contract"] != value["pr_contract"]
        or current["verify_evidence"] != value["verify_evidence"]
        or current["coordination"] != value["coordination"]
    ):
        raise ClosureError("drift", "required-check authority or evidence drifted before merge")
    if coordination["mode"] == DEGRADED_MODE:
        _reject_dispatcher_lease_for_fallback(
            runner,
            cwd,
            repository=str(value["repository"]),
            issue_number=int(value["governing_issue"]),
            pr_number=int(value["pr_number"]),
        )
    else:
        current_dispatcher = _dispatcher_snapshot(
            runner,
            cwd,
            task_id,
            repository=str(value["repository"]),
            issue_number=int(value["governing_issue"]),
            pr_number=int(value["pr_number"]),
        )
        if current_dispatcher != dispatcher:
            raise ClosureError(
                "drift", "dispatcher task or lease-holder drifted immediately before merge"
            )
    merge = value["merge"]
    result = runner.run(["gh", "api", "--hostname", GITHUB_HOST, "--method", "PUT", f"repos/{value['repository']}/pulls/{value['pr_number']}/merge", "-f", f"sha={value['head_sha']}", "-f", f"merge_method={merge['method']}", "-f", f"commit_title={merge['commit_title']}", "-f", f"commit_message={merge['commit_message']}"], cwd=cwd)
    if result.returncode:
        try:
            readback = _pr(runner, cwd, value["repository"], value["pr_number"])
            if readback.get("merged_at") is not None and readback.get("head", {}).get("sha") == value["head_sha"]:
                current = {"pr": readback, "issue": _issue(runner, cwd, value["repository"], value["governing_issue"]), "issue_labels": [], "checks": [], "head_sha": value["head_sha"], "issue_number": value["governing_issue"], "dispatcher": dispatcher}
                _validate_planned_pr(readback, value, phase="post-merge", check_revision=False)
                if _closing_issue_references(runner, cwd, value["repository"], int(value["pr_number"])) != [value["governing_issue"]]:
                    raise ClosureError("incomplete", "post-merge PR closing references are not the planned singleton")
                _validate_planned_issue(current["issue"], value, phase="post-merge")
                if str(current["issue"].get("state", "")).lower() == "closed":
                    events = _issue_events(runner, cwd, value["repository"], int(value["governing_issue"]))
                    attribution = _validate_closure_attribution(
                        events,
                        _closure_evidence(
                            runner,
                            cwd,
                            str(value["repository"]),
                            int(value["governing_issue"]),
                            events,
                        ),
                        str(value["repository"]),
                        int(value["governing_issue"]),
                        str(readback["merge_commit_sha"]),
                        int(value["pr_number"]),
                    )
                    current["closure_attribution"] = attribution
                    return _finish_cleanup(value, current, runner, cwd, reconciled=True)
        except ClosureError:
            pass
        raise ClosureError("unknown", "exact-head merge outcome is ambiguous; read PR and Issue", result)
    merged = _pr(runner, cwd, value["repository"], int(value["pr_number"]))
    _validate_planned_pr(merged, value, phase="post-merge", check_revision=False)
    if _closing_issue_references(runner, cwd, value["repository"], int(value["pr_number"])) != [value["governing_issue"]]:
        raise ClosureError("incomplete", "post-merge PR closing references are not the planned singleton")
    merge_sha = merged.get("merge_commit_sha")
    closed = _issue(runner, cwd, value["repository"], int(value["governing_issue"]))
    if str(merged.get("state", "")).lower() != "closed" or merged.get("merged_at") is None or not isinstance(merge_sha, str) or not SHA_RE.fullmatch(merge_sha) or str(closed.get("state", "")).lower() != "closed":
        raise ClosureError("incomplete", "merge or GitHub-native Issue closure lacks exact readback")
    _validate_planned_issue(closed, value, phase="post-merge")
    events = _issue_events(runner, cwd, value["repository"], int(value["governing_issue"]))
    attribution = _validate_closure_attribution(
        events,
        _closure_evidence(
            runner, cwd, str(value["repository"]), int(value["governing_issue"]), events
        ),
        str(value["repository"]),
        int(value["governing_issue"]),
        merge_sha,
        int(value["pr_number"]),
    )
    return _finish_cleanup(value, {"pr": merged, "issue": closed, "issue_labels": [], "checks": [], "head_sha": value["head_sha"], "issue_number": value["governing_issue"], "dispatcher": dispatcher, "closure_attribution": attribution}, runner, cwd, reconciled=False, merge_sha=merge_sha)


def _complete_dispatcher_after_merge(
    value: Mapping[str, Any],
    dispatcher: Mapping[str, Any],
    runner: CommandExecutor,
    cwd: Path,
) -> dict[str, str]:
    state = _dispatcher_completion(
        runner,
        cwd,
        dispatcher,
        repository=str(value["repository"]),
        issue_number=int(value["governing_issue"]),
        pr_number=int(value["pr_number"]),
        allow_expired_claim=True,
    )
    if state["status"] == "released":
        dispatcher = _dispatcher_reclaim(
            runner,
            cwd,
            dispatcher,
            repository=str(value["repository"]),
            issue_number=int(value["governing_issue"]),
            pr_number=int(value["pr_number"]),
        )
        state = _dispatcher_completion(
            runner,
            cwd,
            dispatcher,
            repository=str(value["repository"]),
            issue_number=int(value["governing_issue"]),
            pr_number=int(value["pr_number"]),
        )
    if state["status"] == "claimed":
        completed = runner.run(
            [
                sys.executable,
                "-m",
                "app.dispatcher",
                "complete",
                str(dispatcher["task_id"]),
                "--agent",
                str(dispatcher["lease_holder"]),
                "--lease-id",
                str(dispatcher["lease_id"]),
                "--json",
            ],
            cwd=cwd,
        )
        if completed.returncode:
            raise ClosureError("incomplete", "merge succeeded but dispatcher completion failed", completed)
        state = _dispatcher_completion(
            runner,
            cwd,
            dispatcher,
            repository=str(value["repository"]),
            issue_number=int(value["governing_issue"]),
            pr_number=int(value["pr_number"]),
            allow_expired_claim=True,
        )
    if state["status"] != "completed":
        raise ClosureError("incomplete", "post-merge dispatcher completion is not final")
    return state


def _finish_cleanup(
    value: Mapping[str, Any],
    current: Mapping[str, Any],
    runner: CommandExecutor,
    cwd: Path,
    *,
    reconciled: bool,
    merge_sha: str | None = None,
) -> dict[str, Any]:
    coordination = value.get("coordination")
    if not isinstance(coordination, Mapping) or coordination.get("mode") != DEGRADED_MODE:
        return _finish_cleanup_effects(
            value,
            current,
            runner,
            cwd,
            reconciled=reconciled,
            merge_sha=merge_sha,
        )
    task_id = github_issue_task_id(str(value["repository"]), int(value["governing_issue"]))
    owner = (
        f"closure-cleanup:{value['repository']}:{value['pr_number']}:{value['plan_sha256']}"
        f":invocation-{uuid.uuid4().hex}"
    )
    token = _dispatcher_cleanup_guard(
        runner,
        cwd,
        action="acquire",
        task_id=task_id,
        owner=owner,
    )
    if token is None:
        raise ClosureError("incomplete", "dispatcher cleanup guard acquisition returned no token")
    try:
        return _finish_cleanup_effects(
            value,
            current,
            runner,
            cwd,
            reconciled=reconciled,
            merge_sha=merge_sha,
            cleanup_guard=(task_id, owner, token),
        )
    finally:
        _dispatcher_cleanup_guard(
            runner,
            cwd,
            action="release",
            task_id=task_id,
            owner=owner,
            token=token,
        )


def _finish_cleanup_effects(
    value: Mapping[str, Any],
    current: Mapping[str, Any],
    runner: CommandExecutor,
    cwd: Path,
    *,
    reconciled: bool,
    merge_sha: str | None = None,
    cleanup_guard: tuple[str, str, str] | None = None,
) -> dict[str, Any]:
    def refresh_guard() -> None:
        if cleanup_guard is not None:
            _require_bounded_cleanup_executor(runner)
            task_id, owner, token = cleanup_guard
            _dispatcher_cleanup_guard(
                runner,
                cwd,
                action="refresh",
                task_id=task_id,
                owner=owner,
                token=token,
            )

    refresh_guard()
    closed = current["issue"]
    dispatcher = value["post_merge"].get("dispatcher")
    coordination = value.get("coordination")
    if isinstance(dispatcher, Mapping):
        dispatcher = _complete_dispatcher_after_merge(value, dispatcher, runner, cwd)
    elif isinstance(coordination, Mapping) and coordination.get("mode") == DEGRADED_MODE:
        _reject_dispatcher_lease_for_fallback(
            runner,
            cwd,
            repository=str(value["repository"]),
            issue_number=int(value["governing_issue"]),
            pr_number=int(value["pr_number"]),
        )
    refresh_guard()
    labels = [str(item.get("name") if isinstance(item, dict) else item) for item in closed.get("labels", [])]
    configured_prefixes = value.get("post_merge", {}).get("remove_label_prefixes")
    if not isinstance(configured_prefixes, list) or sorted(configured_prefixes) != ["action:", "agent:"]:
        raise ClosureError("unsupported", "closure plan does not authorize exact terminal label cleanup")
    removable_labels = sorted(
        {
            label
            for label in labels
            if any(label.startswith(prefix) for prefix in configured_prefixes)
        }
    )
    for label in removable_labels:
        refresh_guard()
        result = runner.run(
            [
                "gh",
                "api",
                "--hostname",
                GITHUB_HOST,
                "--method",
                "DELETE",
                f"repos/{value['repository']}/issues/{value['governing_issue']}/labels/{quote(label, safe='')}",
            ],
            cwd=cwd,
        )
        if result.returncode and "404" not in f"{result.stdout}\n{result.stderr}":
            raise ClosureError("incomplete", "agent label cleanup failed", result)
    refresh_guard()
    after_cleanup = _issue(runner, cwd, str(value["repository"]), int(value["governing_issue"]))
    final_labels = [
        str(item.get("name") if isinstance(item, dict) else item)
        for item in after_cleanup.get("labels", [])
    ]
    if str(after_cleanup.get("state", "")).lower() != "closed":
        raise ClosureError("incomplete", "terminal Issue readback does not prove closed state")
    remaining_action_labels = sorted(
        {
            label
            for label in final_labels
            if any(label.startswith(prefix) for prefix in configured_prefixes)
        }
    )
    if remaining_action_labels:
        raise ClosureError("incomplete", "terminal Issue readback retains agent/action labels")
    refresh_guard()
    if isinstance(dispatcher, Mapping):
        dispatcher = _dispatcher_completion(
            runner,
            cwd,
            dispatcher,
            repository=str(value["repository"]),
            issue_number=int(value["governing_issue"]),
            pr_number=int(value["pr_number"]),
            allow_expired_claim=True,
        )
    elif isinstance(coordination, Mapping) and coordination.get("mode") == DEGRADED_MODE:
        _reject_dispatcher_lease_for_fallback(
            runner,
            cwd,
            repository=str(value["repository"]),
            issue_number=int(value["governing_issue"]),
            pr_number=int(value["pr_number"]),
        )
    merge_sha = merge_sha or current["pr"].get("merge_commit_sha")
    receipt = {"schema": RECEIPT_SCHEMA, "outcome": "success", "reconciled": reconciled, "plan_sha256": value["plan_sha256"], "repository": value["repository"], "pr_number": value["pr_number"], "head_sha": value["head_sha"], "merge_sha": merge_sha, "issue": {"number": value["governing_issue"], "state": "closed", "closure_attribution": current.get("closure_attribution", "GitHub-native closing keyword and exact merge event")}, "cleanup": {"removed_agent_labels": [label for label in removable_labels if label.startswith("agent:")], "removed_action_labels": [label for label in removable_labels if label.startswith("action:")], "remaining_labels": sorted(set(final_labels)), "dispatcher": dispatcher, "project_projection": "optional/unmodified"}, "remaining_action": "post-merge-owner-doc"}
    receipt["receipt_sha256"] = _digest(receipt)
    return receipt


def cli_main(argv: Sequence[str] | None = None, *, executor: CommandExecutor | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); subs = parser.add_subparsers(dest="command", required=True)
    p = subs.add_parser("plan"); p.add_argument("--repository", required=True); p.add_argument("--worktree", type=Path, default=Path.cwd()); p.add_argument("--pr-number", type=int, required=True); p.add_argument("--verify-evidence-json", type=Path, required=True); p.add_argument("--dispatcher-task-id"); p.add_argument("--coordination-mode", choices=(DISPATCHER_MODE, DEGRADED_MODE)); p.add_argument("--fallback-reason"); p.add_argument("--coordination-evidence"); p.add_argument("--caller-agent"); p.add_argument("--caller-session"); p.add_argument("--caller-branch")
    a = subs.add_parser("apply"); a.add_argument("--plan-file", type=Path, required=True); a.add_argument("--expected-plan-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan": result = build_closure_plan(ClosureRequest(args.repository, args.worktree, args.pr_number, json.loads(args.verify_evidence_json.read_text()), args.dispatcher_task_id, args.coordination_mode, args.fallback_reason, args.coordination_evidence, args.caller_agent, args.caller_session, args.caller_branch), executor=executor)
        else: result = apply_closure_plan(json.loads(args.plan_file.read_text()), expected_plan_sha256=args.expected_plan_sha256, executor=executor)
    except ClosureError as exc:
        print(canonical_json({"ok": False, "outcome": exc.outcome, "reason": exc.reason, "returncode": exc.result.returncode if exc.result else None}), file=sys.stderr); return exc.result.returncode if exc.result else (4 if exc.outcome in {"unknown", "incomplete"} else 3)
    print(canonical_json(result)); return 0
