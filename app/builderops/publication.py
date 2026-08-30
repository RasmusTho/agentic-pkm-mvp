"""Hash-bound plan/apply adapter for the normal new-PR publication path."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from app.dispatcher.verification_contract import has_closing_issue_attempt


PLAN_SCHEMA = "builder.publication-plan.v1"
RECEIPT_SCHEMA = "builder.publication-receipt.v1"
SUPPORTED_LANES = frozenset({"implementation", "docs-authoring", "governance"})
SUPPORTED_TIERS = frozenset({1, 2})
RISK_SURFACES = frozenset(
    {
        "auth",
        "security",
        "data",
        "migration",
        "concurrency",
        "external-api",
        "credential-durability",
        "state-machine",
    }
)
REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class CommandExecutor(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        input_text: str | None = None,
    ) -> CommandResult: ...


class SubprocessExecutor:
    """Execute one explicit argv without shell composition."""

    def __init__(self, *, timeout_seconds: float = 120.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        input_text: str | None = None,
    ) -> CommandResult:
        command = tuple(str(item) for item in argv)
        try:
            completed = subprocess.run(
                list(command),
                cwd=cwd,
                input=input_text,
                capture_output=True,
                text=True,
                check=False,
                shell=False,
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return CommandResult(command, 125, "", f"command unavailable or timed out: {exc}")
        return CommandResult(
            command,
            completed.returncode,
            completed.stdout,
            completed.stderr,
        )


class PublicationCommandError(RuntimeError):
    def __init__(self, result: CommandResult) -> None:
        self.result = result
        super().__init__(
            f"command exited {result.returncode}: {' '.join(result.argv)}"
        )


class PublicationRefusal(RuntimeError):
    def __init__(self, outcome: str, reason: str) -> None:
        self.outcome = outcome
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class PublicationRequest:
    repository: str
    worktree: Path
    branch: str
    base_ref: str
    intended_paths: tuple[str, ...]
    lane: str
    tier: int
    risk_surfaces: tuple[str, ...]
    risk_assessment_complete: bool
    review_gate_complete: bool
    governing_issue: int
    commit_message: str
    pr_title: str
    pr_body_inputs: Mapping[str, Any]


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def publication_plan_hash(plan: Mapping[str, Any]) -> str:
    payload = dict(plan)
    payload.pop("plan_sha256", None)
    return _sha256_text(canonical_json(payload))


def build_publication_plan(
    request: PublicationRequest,
    *,
    executor: CommandExecutor | None = None,
) -> dict[str, Any]:
    """Observe local/GitHub authority and return a canonical, effect-free plan."""

    runner = executor or SubprocessExecutor()
    _validate_request(request)
    requested_worktree = request.worktree.resolve()
    actual_worktree = Path(
        _checked(runner, ["git", "rev-parse", "--show-toplevel"], requested_worktree).stdout.strip()
    ).resolve()
    if actual_worktree != requested_worktree:
        raise PublicationRefusal("drift", "canonical worktree does not match requested worktree")
    branch = _git_text(runner, actual_worktree, "branch", "--show-current")
    if branch != request.branch:
        raise PublicationRefusal("drift", "branch does not match requested publication branch")
    origin_url = _git_text(runner, actual_worktree, "remote", "get-url", "origin")
    if _repository_from_origin(origin_url) != request.repository:
        raise PublicationRefusal("drift", "origin repository does not match requested repository")
    base_remote_ref = f"origin/{request.base_ref}"
    base_sha = _git_text(runner, actual_worktree, "rev-parse", base_remote_ref)
    head_sha = _git_text(runner, actual_worktree, "rev-parse", "HEAD")
    if head_sha != base_sha:
        raise PublicationRefusal(
            "unsupported",
            "normal new-PR plan requires HEAD to equal the bound base",
        )

    intended_paths = _normalize_paths(request.intended_paths, actual_worktree)
    unstaged, staged, untracked = _changed_path_sets(runner, actual_worktree)
    if staged:
        raise PublicationRefusal("drift", "publication plan requires an initially clean index")
    dirty_paths = unstaged | untracked
    if dirty_paths != set(intended_paths):
        raise PublicationRefusal(
            "drift",
            "planned paths do not exactly match the dirty working-tree paths",
        )
    path_states = [
        _path_state(runner, actual_worktree, path, base_sha) for path in intended_paths
    ]
    issue = _read_issue(runner, actual_worktree, request.repository, request.governing_issue)
    _require_publishable_issue(issue, request.governing_issue)
    remote_head = _read_remote_head(runner, actual_worktree, request.branch)
    if remote_head is not None:
        raise PublicationRefusal(
            "unsupported", "normal new-PR plan requires an absent remote publication branch"
        )
    if _read_open_prs(runner, actual_worktree, request.repository, request.branch, request.base_ref):
        raise PublicationRefusal(
            "unsupported", "normal new-PR plan requires no open PR for the publication branch"
        )
    pr_body_inputs = json.loads(canonical_json(request.pr_body_inputs))
    _validate_pr_body_inputs(request, pr_body_inputs)
    body = _generate_pr_body(runner, actual_worktree, pr_body_inputs)

    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "repository": request.repository,
        "worktree": str(actual_worktree),
        "lane": request.lane,
        "tier": request.tier,
        "risk_surfaces": sorted(request.risk_surfaces),
        "risk_assessment_complete": request.risk_assessment_complete,
        "review_gate_complete": request.review_gate_complete,
        "governing_issue": issue,
        "git": {
            "branch": request.branch,
            "base_ref": request.base_ref,
            "base_remote_ref": base_remote_ref,
            "base_sha": base_sha,
            "head_sha": head_sha,
            "origin_url": origin_url,
            "intended_paths": list(intended_paths),
            "path_states": path_states,
            "remote_head": None,
        },
        "commit": {
            "message": request.commit_message.rstrip("\n"),
            "message_sha256": _sha256_text(request.commit_message.rstrip("\n")),
        },
        "pr": {
            "title": request.pr_title.strip(),
            "body_inputs": pr_body_inputs,
            "body": body,
            "body_sha256": _sha256_text(body),
            "base_ref": request.base_ref,
            "head_ref": request.branch,
        },
    }
    plan["plan_sha256"] = publication_plan_hash(plan)
    return plan


def apply_publication_plan(
    plan: Mapping[str, Any],
    *,
    expected_plan_sha256: str,
    executor: CommandExecutor | None = None,
) -> dict[str, Any]:
    """Apply or reconcile one exact normal-path publication plan."""

    runner = executor or SubprocessExecutor()
    normalized = _validated_plan(plan, expected_plan_sha256)
    worktree = Path(normalized["worktree"])
    local_state, commit_sha = _observe_local_state(runner, worktree, normalized)
    _assert_issue_unchanged(runner, worktree, normalized)
    remote_head = _read_remote_head(runner, worktree, normalized["git"]["branch"])
    prs = _read_open_prs(
        runner,
        worktree,
        normalized["repository"],
        normalized["git"]["branch"],
        normalized["git"]["base_ref"],
    )
    reconciled = local_state == "committed"
    existing = _resolve_existing_pr(normalized, prs, commit_sha)
    if existing is not None:
        if local_state != "committed" or commit_sha is None or remote_head != commit_sha:
            raise PublicationRefusal("unknown", "exact PR exists without exact local/remote commit")
        return _receipt(normalized, commit_sha, existing, reconciled=True)
    if prs:
        raise PublicationRefusal("unknown", "open PR state is ambiguous or does not match the plan")
    if remote_head is not None and (local_state != "committed" or remote_head != commit_sha):
        raise PublicationRefusal("unknown", "remote branch head does not match the planned result")

    if local_state != "committed":
        _run_workspace_gate(runner, worktree, normalized)
        _assert_issue_unchanged(runner, worktree, normalized)
        state_before_stage, _ = _observe_local_state(runner, worktree, normalized)
        if state_before_stage not in {"uncommitted", "staged"}:
            raise PublicationRefusal("drift", "local state changed before staging")
        stage = runner.run(
            ["git", "add", "--", *normalized["git"]["intended_paths"]], cwd=worktree
        )
        if stage.returncode != 0:
            raise PublicationCommandError(stage)
        _assert_staged_plan(runner, worktree, normalized)
        _assert_issue_unchanged(runner, worktree, normalized)
        commit = runner.run(
            ["git", "commit", "-m", normalized["commit"]["message"]], cwd=worktree
        )
        if commit.returncode != 0:
            try:
                state_after_failure, observed_commit = _observe_local_state(
                    runner, worktree, normalized
                )
            except PublicationRefusal:
                raise PublicationCommandError(commit) from None
            if state_after_failure != "committed":
                raise PublicationCommandError(commit)
            commit_sha = observed_commit
            reconciled = True
        else:
            local_state, commit_sha = _observe_local_state(runner, worktree, normalized)
            if local_state != "committed" or commit_sha is None:
                raise PublicationRefusal("unknown", "commit command succeeded without exact readback")

    if commit_sha is None:
        raise PublicationRefusal("unknown", "publication commit identity is unavailable")
    _run_review_gate(runner, worktree, normalized)
    regenerated_body = _generate_pr_body(
        runner, worktree, normalized["pr"]["body_inputs"]
    )
    if (
        regenerated_body != normalized["pr"]["body"]
        or _sha256_text(regenerated_body) != normalized["pr"]["body_sha256"]
    ):
        raise PublicationRefusal("drift", "generated PR body drifted from the plan")

    _assert_issue_unchanged(runner, worktree, normalized)
    state_before_push, checked_commit = _observe_local_state(runner, worktree, normalized)
    if state_before_push != "committed" or checked_commit != commit_sha:
        raise PublicationRefusal("drift", "local commit drifted before push")
    _run_workspace_gate(runner, worktree, normalized)
    remote_head = _read_remote_head(runner, worktree, normalized["git"]["branch"])
    prs = _read_open_prs(
        runner,
        worktree,
        normalized["repository"],
        normalized["git"]["branch"],
        normalized["git"]["base_ref"],
    )
    existing = _resolve_existing_pr(normalized, prs, commit_sha)
    if existing is not None and remote_head == commit_sha:
        return _receipt(normalized, commit_sha, existing, reconciled=True)
    if prs or (remote_head is not None and remote_head != commit_sha):
        raise PublicationRefusal("unknown", "publication state became ambiguous before push")
    push_may_have_succeeded = remote_head == commit_sha
    if remote_head is None:
        push = runner.run(
            [
                "git",
                "push",
                "origin",
                f"{commit_sha}:refs/heads/{normalized['git']['branch']}",
            ],
            cwd=worktree,
        )
        push_may_have_succeeded = True
        if push.returncode != 0:
            try:
                observed_remote = _read_remote_head(
                    runner, worktree, normalized["git"]["branch"]
                )
            except PublicationCommandError:
                raise PublicationRefusal(
                    "unknown",
                    "push failed and immediate remote readback was unavailable",
                ) from None
            if observed_remote is None:
                raise PublicationRefusal(
                    "unknown",
                    "push failed and immediate readback did not prove the remote state",
                )
            if observed_remote != commit_sha:
                raise PublicationRefusal("unknown", "push failed with a conflicting remote head")
            reconciled = True

    try:
        _assert_issue_unchanged(runner, worktree, normalized)
        observed_remote = _read_remote_head(
            runner, worktree, normalized["git"]["branch"]
        )
        prs = _read_open_prs(
            runner,
            worktree,
            normalized["repository"],
            normalized["git"]["branch"],
            normalized["git"]["base_ref"],
        )
    except PublicationCommandError:
        if push_may_have_succeeded:
            raise PublicationRefusal(
                "unknown", "post-push publication readback was unavailable"
            ) from None
        raise
    if observed_remote != commit_sha:
        raise PublicationRefusal("unknown", "remote branch readback is not the exact commit")
    existing = _resolve_existing_pr(normalized, prs, commit_sha)
    if existing is None and prs:
        raise PublicationRefusal("unknown", "PR state became ambiguous before creation")
    if existing is None:
        create = runner.run(
            [
                "gh",
                "pr",
                "create",
                "--repo",
                normalized["repository"],
                "--base",
                normalized["git"]["base_ref"],
                "--head",
                normalized["git"]["branch"],
                "--title",
                normalized["pr"]["title"],
                "--body",
                normalized["pr"]["body"],
            ],
            cwd=worktree,
        )
        if create.returncode != 0:
            try:
                prs = _read_open_prs(
                    runner,
                    worktree,
                    normalized["repository"],
                    normalized["git"]["branch"],
                    normalized["git"]["base_ref"],
                )
            except PublicationCommandError:
                raise PublicationRefusal(
                    "unknown",
                    "PR create failed and immediate readback was unavailable",
                ) from None
            existing = _resolve_existing_pr(normalized, prs, commit_sha)
            if existing is None:
                if not prs:
                    raise PublicationRefusal(
                        "unknown",
                        "PR create failed and immediate readback did not prove the outcome",
                    )
                raise PublicationRefusal("unknown", "PR create failed with ambiguous readback")
            reconciled = True

    try:
        final_remote = _read_remote_head(
            runner, worktree, normalized["git"]["branch"]
        )
        final_prs = _read_open_prs(
            runner,
            worktree,
            normalized["repository"],
            normalized["git"]["branch"],
            normalized["git"]["base_ref"],
        )
    except PublicationCommandError:
        raise PublicationRefusal(
            "unknown", "final publication readback was unavailable after external effect"
        ) from None
    final_pr = _resolve_existing_pr(normalized, final_prs, commit_sha)
    if final_remote != commit_sha or final_pr is None or len(final_prs) != 1:
        raise PublicationRefusal("unknown", "publication effects lack one exact final readback")
    return _receipt(normalized, commit_sha, final_pr, reconciled=reconciled)


def _validate_request(request: PublicationRequest) -> None:
    if not REPOSITORY_RE.fullmatch(request.repository):
        raise PublicationRefusal("unsupported", "repository must be owner/name")
    if request.lane not in SUPPORTED_LANES:
        raise PublicationRefusal("unsupported", "lane is outside the normal publication path")
    if request.tier not in SUPPORTED_TIERS:
        raise PublicationRefusal("unsupported", "only Tier 1/2 publication is supported")
    invalid_risks = set(request.risk_surfaces) - RISK_SURFACES
    if invalid_risks:
        raise PublicationRefusal("unsupported", f"unknown risk surfaces: {sorted(invalid_risks)}")
    if request.risk_surfaces:
        raise PublicationRefusal(
            "unsupported",
            "TCD high-risk publication remains on the governed full path",
        )
    if not isinstance(request.risk_assessment_complete, bool) or not isinstance(
        request.review_gate_complete, bool
    ):
        raise PublicationRefusal("unsupported", "gate attestations must be explicit booleans")
    if request.governing_issue <= 0:
        raise PublicationRefusal("unsupported", "governing Issue must be positive")
    if not request.branch.strip() or not request.base_ref.strip():
        raise PublicationRefusal("unsupported", "branch and base ref are required")
    if not request.intended_paths:
        raise PublicationRefusal("unsupported", "at least one intended path is required")
    if not request.commit_message.strip() or not request.pr_title.strip():
        raise PublicationRefusal("unsupported", "commit message and PR title are required")
    if has_closing_issue_attempt(request.commit_message):
        raise PublicationRefusal("unsupported", "commit message contains a closing Issue reference")


def _validate_pr_body_inputs(request: PublicationRequest, values: Mapping[str, Any]) -> None:
    if values.get("lane") != request.lane:
        raise PublicationRefusal("drift", "PR body lane does not match publication lane")
    if values.get("issue_number") != request.governing_issue:
        raise PublicationRefusal("drift", "PR body Issue does not match governing Issue")
    if values.get("final_review_rounds", 0) != 0:
        raise PublicationRefusal(
            "unsupported", "normal Tier 1/2 plan requires Final-Review-Rounds 0"
        )


def _normalize_paths(paths: Sequence[str], worktree: Path) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw in paths:
        path = Path(raw)
        if path.is_absolute() or not raw or ".." in path.parts:
            raise PublicationRefusal("unsupported", f"unsafe intended path: {raw}")
        clean = path.as_posix().removeprefix("./")
        resolved_parent = (worktree / clean).parent.resolve()
        if resolved_parent != worktree and worktree not in resolved_parent.parents:
            raise PublicationRefusal("unsupported", f"intended path escapes worktree: {raw}")
        normalized.append(clean)
    if len(normalized) != len(set(normalized)):
        raise PublicationRefusal("unsupported", "intended paths contain duplicates")
    return tuple(sorted(normalized))


def _checked(
    executor: CommandExecutor,
    argv: Sequence[str],
    cwd: Path,
    *,
    input_text: str | None = None,
) -> CommandResult:
    result = executor.run(argv, cwd=cwd, input_text=input_text)
    if result.returncode != 0:
        raise PublicationCommandError(result)
    return result


def _git_text(executor: CommandExecutor, cwd: Path, *args: str) -> str:
    return _checked(executor, ["git", *args], cwd).stdout.strip()


def _nul_paths(raw: str) -> set[str]:
    return {item for item in raw.split("\0") if item}


def _changed_path_sets(
    executor: CommandExecutor, cwd: Path
) -> tuple[set[str], set[str], set[str]]:
    unstaged = _nul_paths(
        _checked(
            executor,
            ["git", "diff", "--name-only", "-z", "--no-renames"],
            cwd,
        ).stdout
    )
    staged = _nul_paths(
        _checked(
            executor,
            ["git", "diff", "--name-only", "-z", "--no-renames", "--cached"],
            cwd,
        ).stdout
    )
    untracked = _nul_paths(
        _checked(
            executor,
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd,
        ).stdout
    )
    return unstaged, staged, untracked


def _path_state(
    executor: CommandExecutor, cwd: Path, path: str, base_sha: str
) -> dict[str, Any]:
    absolute = cwd / path
    state: dict[str, Any] = {"path": path}
    try:
        metadata = absolute.lstat()
    except FileNotFoundError:
        state.update({"kind": "missing", "mode": None, "size": 0, "sha256": None})
    else:
        state["mode"] = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISREG(metadata.st_mode):
            content = absolute.read_bytes()
            state.update(
                {"kind": "file", "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            )
        elif stat.S_ISLNK(metadata.st_mode):
            target = os.readlink(absolute)
            encoded = target.encode("utf-8")
            state.update(
                {
                    "kind": "symlink",
                    "size": len(encoded),
                    "sha256": hashlib.sha256(encoded).hexdigest(),
                    "target": target,
                }
            )
        else:
            raise PublicationRefusal("unsupported", f"unsupported path type: {path}")
    state["base_entry"] = _checked(
        executor, ["git", "ls-tree", base_sha, "--", path], cwd
    ).stdout.strip()
    state["index_entry"] = _checked(
        executor, ["git", "ls-files", "--stage", "--", path], cwd
    ).stdout.strip()
    return state


def _content_binding(state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: state.get(key)
        for key in ("path", "kind", "mode", "size", "sha256", "target", "base_entry")
        if key in state
    }


def _repository_from_origin(origin_url: str) -> str:
    match = re.search(
        r"(?:github\.com[:/])(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?\Z",
        origin_url,
    )
    if not match:
        raise PublicationRefusal("unsupported", "origin is not a canonical GitHub repository URL")
    return match.group("repo")


def _read_issue(
    executor: CommandExecutor, cwd: Path, repository: str, issue_number: int
) -> dict[str, Any]:
    result = _checked(
        executor,
        ["gh", "api", "--method", "GET", f"repos/{repository}/issues/{issue_number}"],
        cwd,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PublicationRefusal("unknown", "GitHub Issue readback was not JSON") from exc
    if not isinstance(payload, dict) or "pull_request" in payload:
        raise PublicationRefusal("unknown", "GitHub Issue readback was not an Issue")
    labels = payload.get("labels")
    if not isinstance(labels, list):
        raise PublicationRefusal("unknown", "GitHub Issue labels were not a list")
    label_names: list[str] = []
    for item in labels:
        name = item.get("name") if isinstance(item, dict) else item
        if not isinstance(name, str):
            raise PublicationRefusal("unknown", "GitHub Issue label was malformed")
        label_names.append(name)
    body = payload.get("body") or ""
    if not isinstance(body, str):
        raise PublicationRefusal("unknown", "GitHub Issue body was malformed")
    return {
        "number": payload.get("number"),
        "state": str(payload.get("state", "")).lower(),
        "title": payload.get("title"),
        "body_sha256": _sha256_text(body),
        "labels": sorted(label_names),
        "url": payload.get("html_url"),
    }


def _require_publishable_issue(issue: Mapping[str, Any], expected_number: int) -> None:
    if issue.get("number") != expected_number or issue.get("state") != "open":
        raise PublicationRefusal("drift", "governing Issue is not the expected open Issue")
    labels = set(issue.get("labels", []))
    if "agent:in-progress" not in labels or "agent:ready" in labels:
        raise PublicationRefusal("drift", "governing Issue is not actively claimed")


def _assert_issue_unchanged(
    executor: CommandExecutor, cwd: Path, plan: Mapping[str, Any]
) -> None:
    issue = _read_issue(
        executor,
        cwd,
        str(plan["repository"]),
        int(plan["governing_issue"]["number"]),
    )
    if issue != plan["governing_issue"]:
        raise PublicationRefusal("drift", "governing Issue drift")
    _require_publishable_issue(issue, int(plan["governing_issue"]["number"]))


def _read_remote_head(
    executor: CommandExecutor, cwd: Path, branch: str
) -> str | None:
    result = _checked(
        executor,
        ["git", "ls-remote", "--heads", "origin", f"refs/heads/{branch}"],
        cwd,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return None
    if len(lines) != 1:
        raise PublicationRefusal("unknown", "remote branch readback was not unique")
    parts = lines[0].split()
    if len(parts) != 2 or parts[1] != f"refs/heads/{branch}" or not re.fullmatch(r"[0-9a-f]{40,64}", parts[0]):
        raise PublicationRefusal("unknown", "remote branch readback was malformed")
    return parts[0]


def _read_open_prs(
    executor: CommandExecutor,
    cwd: Path,
    repository: str,
    branch: str,
    base_ref: str,
) -> list[dict[str, Any]]:
    del base_ref
    owner = repository.split("/", 1)[0]
    result = _checked(
        executor,
        [
            "gh",
            "api",
            "--method",
            "GET",
            f"repos/{repository}/pulls",
            "-f",
            "state=open",
            "-f",
            f"head={owner}:{branch}",
            "-f",
            "per_page=100",
        ],
        cwd,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PublicationRefusal("unknown", "GitHub PR readback was not JSON") from exc
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise PublicationRefusal("unknown", "GitHub PR readback was not a list")
    return [dict(item) for item in payload]


def _generate_pr_body(
    executor: CommandExecutor, cwd: Path, values: Mapping[str, Any]
) -> str:
    argv = [sys.executable, str(REPO_ROOT / "scripts/pr_body_generator.py")]
    argv.extend(["--lane", str(values.get("lane", ""))])
    if values.get("issue_number") is not None:
        argv.extend(["--issue-number", str(values["issue_number"])])
    summary = values.get("summary", [])
    if isinstance(summary, str):
        summary = [summary]
    for item in summary:
        argv.extend(["--summary", str(item)])
    sbs = values.get("sbs_impact", {})
    if isinstance(sbs, Mapping):
        for key in sorted(sbs):
            argv.extend(["--sbs", f"{key}={sbs[key]}"])
    argv.extend(["--owner-doc-resolution", str(values.get("owner_doc_resolution", ""))])
    if values.get("owner_doc_followup_issue") is not None:
        argv.extend(["--owner-doc-followup-issue", str(values["owner_doc_followup_issue"])])
    argv.extend(["--final-review-rounds", str(values.get("final_review_rounds", 0))])
    if values.get("builderops_records") is not None:
        argv.extend(["--builderops-records", str(values["builderops_records"])])
    if values.get("builderops_reason") is not None:
        argv.extend(["--builderops-reason", str(values["builderops_reason"])])
    if values.get("notes") is not None:
        argv.extend(["--notes", str(values["notes"])])
    return _checked(executor, argv, cwd).stdout


def _validated_plan(plan: Mapping[str, Any], expected_hash: str) -> dict[str, Any]:
    normalized = json.loads(canonical_json(plan))
    if normalized.get("schema") != PLAN_SCHEMA:
        raise PublicationRefusal("unsupported", "unsupported publication plan schema")
    actual_hash = publication_plan_hash(normalized)
    if (
        not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
        or normalized.get("plan_sha256") != expected_hash
        or actual_hash != expected_hash
    ):
        raise PublicationRefusal("drift", "publication plan hash mismatch")
    if normalized.get("risk_surfaces"):
        raise PublicationRefusal("unsupported", "high-risk publication is outside the normal path")
    if normalized.get("risk_assessment_complete") is not True:
        raise PublicationRefusal("drift", "publication plan lacks bound risk assessment completion")
    if normalized.get("review_gate_complete") is not True:
        raise PublicationRefusal("drift", "publication plan lacks bound review gate completion")
    if normalized.get("lane") not in SUPPORTED_LANES or normalized.get("tier") not in SUPPORTED_TIERS:
        raise PublicationRefusal("unsupported", "publication plan is outside the supported path")
    body = normalized.get("pr", {}).get("body")
    if not isinstance(body, str) or _sha256_text(body) != normalized.get("pr", {}).get("body_sha256"):
        raise PublicationRefusal("drift", "publication plan PR body digest mismatch")
    return normalized


def _observe_local_state(
    executor: CommandExecutor, cwd: Path, plan: Mapping[str, Any]
) -> tuple[str, str | None]:
    actual = Path(_git_text(executor, cwd, "rev-parse", "--show-toplevel")).resolve()
    if actual != Path(plan["worktree"]).resolve():
        raise PublicationRefusal("drift", "worktree drift")
    if _git_text(executor, cwd, "branch", "--show-current") != plan["git"]["branch"]:
        raise PublicationRefusal("drift", "branch drift")
    if _git_text(executor, cwd, "remote", "get-url", "origin") != plan["git"]["origin_url"]:
        raise PublicationRefusal("drift", "origin drift")
    if _git_text(executor, cwd, "rev-parse", plan["git"]["base_remote_ref"]) != plan["git"]["base_sha"]:
        raise PublicationRefusal("drift", "base ref drift")
    current_head = _git_text(executor, cwd, "rev-parse", "HEAD")
    unstaged, staged, untracked = _changed_path_sets(executor, cwd)
    planned_paths = set(plan["git"]["intended_paths"])
    dirty = unstaged | staged | untracked
    if current_head == plan["git"]["head_sha"]:
        if dirty != planned_paths or not staged.issubset(planned_paths):
            raise PublicationRefusal("drift", "planned local paths drifted before commit")
        for expected in plan["git"]["path_states"]:
            observed = _path_state(
                executor, cwd, expected["path"], plan["git"]["base_sha"]
            )
            if _content_binding(observed) != _content_binding(expected):
                raise PublicationRefusal("drift", f"planned content drift: {expected['path']}")
        state = "staged" if staged == planned_paths and not (unstaged | untracked) else "uncommitted"
        return state, None
    if dirty:
        raise PublicationRefusal("drift", "working tree is dirty after publication commit")
    parents = _git_text(executor, cwd, "rev-list", "--parents", "-n", "1", "HEAD").split()
    if parents != [current_head, plan["git"]["head_sha"]]:
        raise PublicationRefusal("drift", "publication commit parent does not match the plan")
    message = _checked(executor, ["git", "show", "-s", "--format=%B", "HEAD"], cwd).stdout.rstrip("\n")
    if message != plan["commit"]["message"]:
        raise PublicationRefusal("drift", "publication commit message does not match the plan")
    committed_paths = _nul_paths(
        _checked(
            executor,
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", "--no-renames", "HEAD"],
            cwd,
        ).stdout
    )
    if committed_paths != planned_paths:
        raise PublicationRefusal("drift", "publication commit paths do not match the plan")
    for expected in plan["git"]["path_states"]:
        observed = _path_state(executor, cwd, expected["path"], plan["git"]["base_sha"])
        if _content_binding(observed) != _content_binding(expected):
            raise PublicationRefusal("drift", f"committed content drift: {expected['path']}")
    return "committed", current_head


def _assert_staged_plan(
    executor: CommandExecutor, cwd: Path, plan: Mapping[str, Any]
) -> None:
    unstaged, staged, untracked = _changed_path_sets(executor, cwd)
    if staged != set(plan["git"]["intended_paths"]) or unstaged or untracked:
        raise PublicationRefusal("drift", "staged paths do not exactly match the plan")
    for expected in plan["git"]["path_states"]:
        observed = _path_state(executor, cwd, expected["path"], plan["git"]["base_sha"])
        if _content_binding(observed) != _content_binding(expected):
            raise PublicationRefusal("drift", f"staged content drift: {expected['path']}")


def _run_workspace_gate(
    executor: CommandExecutor, cwd: Path, plan: Mapping[str, Any]
) -> None:
    _checked(
        executor,
        [
            str(REPO_ROOT / "scripts/agent_workspace_preflight.sh"),
            "--expected-branch",
            plan["git"]["branch"],
            "--expected-worktree",
            plan["worktree"],
            "--allow-dirty",
        ],
        cwd,
    )


def _run_review_gate(
    executor: CommandExecutor, cwd: Path, plan: Mapping[str, Any]
) -> None:
    argv = [
        sys.executable,
        str(REPO_ROOT / "scripts/review_before_ci_gate.py"),
        "--lane",
        plan["lane"],
    ]
    if plan["review_gate_complete"] is True:
        argv.append("--review-gate-complete")
    if plan["risk_assessment_complete"] is True:
        argv.append("--risk-assessment-complete")
    for path in plan["git"]["intended_paths"]:
        argv.extend(["--changed-file", path])
    for risk in plan["risk_surfaces"]:
        argv.extend(["--risk-surface", risk])
    argv.extend(["--publication-mode", "new", "--github-repository", plan["repository"]])
    _checked(executor, argv, cwd)


def _resolve_existing_pr(
    plan: Mapping[str, Any], prs: Sequence[Mapping[str, Any]], commit_sha: str | None
) -> dict[str, Any] | None:
    if not prs:
        return None
    if len(prs) != 1 or commit_sha is None:
        return None
    pr = dict(prs[0])
    expected = {
        "state": "open",
        "title": plan["pr"]["title"],
        "body": plan["pr"]["body"],
        "base_repo": plan["repository"],
        "base_ref": plan["git"]["base_ref"],
        "head_repo": plan["repository"],
        "head_ref": plan["git"]["branch"],
        "head_sha": commit_sha,
    }
    observed = {
        "state": str(pr.get("state", "")).lower(),
        "title": pr.get("title"),
        "body": pr.get("body") or "",
        "base_repo": _nested(pr, "base", "repo", "full_name"),
        "base_ref": _nested(pr, "base", "ref"),
        "head_repo": _nested(pr, "head", "repo", "full_name"),
        "head_ref": _nested(pr, "head", "ref"),
        "head_sha": _nested(pr, "head", "sha"),
    }
    return pr if observed == expected else None


def _nested(value: Mapping[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _receipt(
    plan: Mapping[str, Any],
    commit_sha: str,
    pr: Mapping[str, Any],
    *,
    reconciled: bool,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "outcome": "success",
        "reconciled": reconciled,
        "plan_sha256": plan["plan_sha256"],
        "repository": plan["repository"],
        "worktree": plan["worktree"],
        "branch": plan["git"]["branch"],
        "commit_sha": commit_sha,
        "remote": {
            "repository": plan["repository"],
            "ref": f"refs/heads/{plan['git']['branch']}",
            "sha": commit_sha,
        },
        "pr": {
            "number": pr.get("number"),
            "url": pr.get("html_url"),
            "state": str(pr.get("state", "")).lower(),
            "title": pr.get("title"),
            "body_sha256": _sha256_text(str(pr.get("body") or "")),
            "base_repository": _nested(pr, "base", "repo", "full_name"),
            "base_ref": _nested(pr, "base", "ref"),
            "head_repository": _nested(pr, "head", "repo", "full_name"),
            "head_ref": _nested(pr, "head", "ref"),
            "head_sha": _nested(pr, "head", "sha"),
        },
    }
    receipt["receipt_sha256"] = _sha256_text(canonical_json(receipt))
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--repository", required=True)
    plan.add_argument("--worktree", type=Path, default=Path.cwd())
    plan.add_argument("--branch", required=True)
    plan.add_argument("--base-ref", default="main")
    plan.add_argument("--path", action="append", dest="paths", required=True)
    plan.add_argument("--lane", choices=sorted(SUPPORTED_LANES), required=True)
    plan.add_argument("--tier", type=int, choices=sorted(SUPPORTED_TIERS), required=True)
    plan.add_argument("--risk-surface", action="append", default=[])
    plan.add_argument("--risk-assessment-complete", action="store_true")
    plan.add_argument("--review-gate-complete", action="store_true")
    plan.add_argument("--governing-issue", type=int, required=True)
    plan.add_argument("--commit-message", required=True)
    plan.add_argument("--pr-title", required=True)
    plan.add_argument("--pr-body-input-json", type=Path, required=True)
    apply = commands.add_parser("apply")
    apply.add_argument("--plan-file", type=Path, required=True)
    apply.add_argument("--expected-plan-sha256", required=True)
    return parser


def cli_main(
    argv: Sequence[str] | None = None,
    *,
    executor: CommandExecutor | None = None,
) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            body_inputs = json.loads(args.pr_body_input_json.read_text(encoding="utf-8"))
            result = build_publication_plan(
                PublicationRequest(
                    repository=args.repository,
                    worktree=args.worktree,
                    branch=args.branch,
                    base_ref=args.base_ref,
                    intended_paths=tuple(args.paths),
                    lane=args.lane,
                    tier=args.tier,
                    risk_surfaces=tuple(args.risk_surface),
                    risk_assessment_complete=args.risk_assessment_complete,
                    review_gate_complete=args.review_gate_complete,
                    governing_issue=args.governing_issue,
                    commit_message=args.commit_message,
                    pr_title=args.pr_title,
                    pr_body_inputs=body_inputs,
                ),
                executor=executor,
            )
        else:
            plan = json.loads(args.plan_file.read_text(encoding="utf-8"))
            result = apply_publication_plan(
                plan,
                expected_plan_sha256=args.expected_plan_sha256,
                executor=executor,
            )
    except PublicationCommandError as exc:
        print(
            canonical_json(
                {
                    "ok": False,
                    "outcome": "command-failed",
                    "returncode": exc.result.returncode,
                    "argv": list(exc.result.argv),
                    "stderr": exc.result.stderr,
                }
            ),
            file=sys.stderr,
        )
        return exc.result.returncode
    except PublicationRefusal as exc:
        print(
            canonical_json({"ok": False, "outcome": exc.outcome, "reason": exc.reason}),
            file=sys.stderr,
        )
        return 4 if exc.outcome == "unknown" else 3
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(canonical_json({"ok": False, "outcome": "invalid", "reason": str(exc)}), file=sys.stderr)
        return 2
    print(canonical_json(result))
    return 0


__all__ = [
    "CommandResult",
    "PublicationCommandError",
    "PublicationRefusal",
    "PublicationRequest",
    "SubprocessExecutor",
    "apply_publication_plan",
    "build_publication_plan",
    "canonical_json",
    "cli_main",
    "publication_plan_hash",
]
