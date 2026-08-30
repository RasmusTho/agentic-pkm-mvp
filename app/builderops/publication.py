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
GIT_SHA_RE = re.compile(r"[0-9a-f]{40,64}\Z")
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
        super().__init__(f"publication command exited {result.returncode}")


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


@dataclass(frozen=True)
class PublicationAuthoritySnapshot:
    """Credential-free authority bound to one normal-path publication."""

    fetch_identity: Mapping[str, str]
    push_identity: Mapping[str, str]
    base_ref: str
    base_sha: str

    def as_mapping(self) -> dict[str, Any]:
        return {
            "fetch_identity": dict(self.fetch_identity),
            "push_identity": dict(self.push_identity),
            "base_ref": self.base_ref,
            "base_sha": self.base_sha,
        }


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
    base_remote_ref = f"origin/{request.base_ref}"
    base_sha = _git_text(runner, actual_worktree, "rev-parse", base_remote_ref)
    head_sha = _git_text(runner, actual_worktree, "rev-parse", "HEAD")
    if head_sha != base_sha:
        raise PublicationRefusal(
            "unsupported",
            "normal new-PR plan requires HEAD to equal the bound base",
        )
    authority = _read_authority_snapshot(
        runner,
        actual_worktree,
        request.repository,
        request.base_ref,
    )
    if authority.base_sha != base_sha:
        raise PublicationRefusal("drift", "local base changed while building the plan")

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
    path_states = [_path_state(runner, actual_worktree, path, base_sha) for path in intended_paths]
    issue = _read_issue(runner, actual_worktree, request.repository, request.governing_issue)
    _require_publishable_issue(issue, request.governing_issue)
    remote_head = _read_remote_head(runner, actual_worktree, request.branch)
    if remote_head is not None:
        raise PublicationRefusal(
            "unsupported", "normal new-PR plan requires an absent remote publication branch"
        )
    if _read_pr_history(runner, actual_worktree, request.repository, request.branch):
        raise PublicationRefusal(
            "unsupported",
            "normal new-PR plan requires empty all-state PR history for the publication branch",
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
        "authority": authority.as_mapping(),
        "git": {
            "branch": request.branch,
            "base_ref": request.base_ref,
            "base_remote_ref": base_remote_ref,
            "base_sha": base_sha,
            "head_sha": head_sha,
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
    authority = _assert_authority_unchanged(runner, worktree, normalized)
    local_state, commit_sha = _observe_local_state(runner, worktree, normalized)
    _assert_issue_unchanged(runner, worktree, normalized)
    remote_head = _read_remote_head(runner, worktree, normalized["git"]["branch"])
    prs = _read_pr_history(
        runner,
        worktree,
        normalized["repository"],
        normalized["git"]["branch"],
    )
    reconciled = local_state == "committed"
    existing = _resolve_pr_history(normalized, prs, commit_sha)
    if existing is not None:
        if local_state != "committed" or commit_sha is None or remote_head != commit_sha:
            raise PublicationRefusal("unknown", "exact PR exists without exact local/remote commit")
        return _receipt(normalized, authority, commit_sha, existing, reconciled=True)
    if local_state != "committed" and remote_head is not None:
        raise PublicationRefusal(
            "unknown", "remote reservation exists without the exact local publication commit"
        )
    if remote_head not in {None, normalized["authority"]["base_sha"], commit_sha}:
        raise PublicationRefusal(
            "unknown", "remote branch is outside the publication state machine"
        )

    if local_state != "committed":
        _run_workspace_gate(runner, worktree, normalized)
        _assert_issue_unchanged(runner, worktree, normalized)
        state_before_stage, _ = _observe_local_state(runner, worktree, normalized)
        if state_before_stage not in {"uncommitted", "staged"}:
            raise PublicationRefusal("drift", "local state changed before staging")
        stage = runner.run(["git", "add", "--", *normalized["git"]["intended_paths"]], cwd=worktree)
        if stage.returncode != 0:
            raise PublicationCommandError(stage)
        _assert_staged_plan(runner, worktree, normalized)
        _assert_issue_unchanged(runner, worktree, normalized)
        commit = runner.run(["git", "commit", "-m", normalized["commit"]["message"]], cwd=worktree)
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
                raise PublicationRefusal(
                    "unknown", "commit command succeeded without exact readback"
                )

    if commit_sha is None:
        raise PublicationRefusal("unknown", "publication commit identity is unavailable")
    _run_review_gate(runner, worktree, normalized)
    regenerated_body = _generate_pr_body(runner, worktree, normalized["pr"]["body_inputs"])
    if (
        regenerated_body != normalized["pr"]["body"]
        or _sha256_text(regenerated_body) != normalized["pr"]["body_sha256"]
    ):
        raise PublicationRefusal("drift", "generated PR body drifted from the plan")

    _run_workspace_gate(runner, worktree, normalized)
    authority, remote_head, prs = _transition_readback(runner, worktree, normalized, commit_sha)
    existing = _resolve_pr_history(normalized, prs, commit_sha)
    if existing is not None:
        if remote_head != commit_sha:
            raise PublicationRefusal("unknown", "exact PR exists without exact remote commit")
        return _receipt(normalized, authority, commit_sha, existing, reconciled=True)
    base_sha = normalized["authority"]["base_sha"]
    if remote_head not in {None, base_sha, commit_sha}:
        raise PublicationRefusal(
            "unknown", "remote branch is outside the publication state machine"
        )

    if remote_head is None:
        reserve = runner.run(
            [
                "gh",
                "api",
                "--method",
                "POST",
                f"repos/{normalized['repository']}/git/refs",
                "-f",
                f"ref=refs/heads/{normalized['git']['branch']}",
                "-f",
                f"sha={base_sha}",
            ],
            cwd=worktree,
        )
        try:
            authority, remote_head, prs = _transition_readback(
                runner, worktree, normalized, commit_sha
            )
        except PublicationCommandError:
            raise PublicationRefusal(
                "unknown", "reservation outcome lacks immediate complete readback"
            ) from None
        existing = _resolve_pr_history(normalized, prs, commit_sha)
        if existing is not None:
            if remote_head != commit_sha:
                raise PublicationRefusal("unknown", "exact PR exists without exact remote commit")
            return _receipt(normalized, authority, commit_sha, existing, reconciled=True)
        if remote_head not in {None, base_sha, commit_sha}:
            raise PublicationRefusal(
                "unknown", "reservation raced with a conflicting remote branch state"
            )
        if reserve.returncode != 0:
            if remote_head is None:
                raise PublicationCommandError(reserve)
            reconciled = True
        elif remote_head is None:
            raise PublicationRefusal(
                "unknown", "reservation command succeeded without exact remote readback"
            )

    if remote_head == base_sha:
        authority, remote_head, prs = _transition_readback(runner, worktree, normalized, commit_sha)
        existing = _resolve_pr_history(normalized, prs, commit_sha)
        if existing is not None:
            raise PublicationRefusal("unknown", "PR appeared before the exact commit transition")
        if remote_head != base_sha:
            if remote_head == commit_sha:
                reconciled = True
            else:
                raise PublicationRefusal(
                    "unknown", "remote branch moved before the exact commit transition"
                )

    if remote_head == base_sha:
        push = runner.run(
            [
                "git",
                "push",
                "origin",
                f"{commit_sha}:refs/heads/{normalized['git']['branch']}",
            ],
            cwd=worktree,
        )
        try:
            authority, remote_head, prs = _transition_readback(
                runner, worktree, normalized, commit_sha
            )
        except PublicationCommandError:
            raise PublicationRefusal(
                "unknown", "push outcome lacks immediate complete readback"
            ) from None
        existing = _resolve_pr_history(normalized, prs, commit_sha)
        if push.returncode != 0:
            if remote_head == base_sha:
                raise PublicationCommandError(push)
            if remote_head != commit_sha:
                raise PublicationRefusal("unknown", "push raced with a conflicting remote head")
            reconciled = True
        elif remote_head != commit_sha:
            raise PublicationRefusal("unknown", "push succeeded without exact remote readback")
        if existing is not None:
            raise PublicationRefusal("unknown", "PR appeared during the exact commit transition")

    if remote_head != commit_sha:
        raise PublicationRefusal("unknown", "remote branch is not the exact publication commit")

    authority, remote_head, prs = _transition_readback(runner, worktree, normalized, commit_sha)
    if remote_head != commit_sha:
        raise PublicationRefusal("unknown", "remote branch moved before PR creation")
    existing = _resolve_pr_history(normalized, prs, commit_sha)
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
                authority, remote_head, prs = _transition_readback(
                    runner, worktree, normalized, commit_sha
                )
            except PublicationCommandError:
                raise PublicationRefusal(
                    "unknown",
                    "PR create failed and immediate readback was unavailable",
                ) from None
            if remote_head != commit_sha:
                raise PublicationRefusal("unknown", "remote branch moved during PR creation")
            existing = _resolve_pr_history(normalized, prs, commit_sha)
            if existing is None:
                raise PublicationRefusal(
                    "unknown", "PR create failed and immediate readback did not prove the outcome"
                )
            reconciled = True

    try:
        authority, final_remote, final_prs = _transition_readback(
            runner, worktree, normalized, commit_sha
        )
    except PublicationCommandError:
        raise PublicationRefusal(
            "unknown", "final publication readback was unavailable after external effect"
        ) from None
    final_pr = _resolve_pr_history(normalized, final_prs, commit_sha)
    if final_remote != commit_sha or final_pr is None or len(final_prs) != 1:
        raise PublicationRefusal("unknown", "publication effects lack one exact final readback")
    return _receipt(
        normalized,
        authority,
        commit_sha,
        final_pr,
        reconciled=reconciled,
    )


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
    if request.base_ref != "main":
        raise PublicationRefusal("unsupported", "the normal publication path is restricted to main")
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


def _changed_path_sets(executor: CommandExecutor, cwd: Path) -> tuple[set[str], set[str], set[str]]:
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


def _path_state(executor: CommandExecutor, cwd: Path, path: str, base_sha: str) -> dict[str, Any]:
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
                {
                    "kind": "file",
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
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


def _remote_identity(raw: str, *, role: str) -> dict[str, str]:
    lines = [line for line in raw.splitlines() if line]
    if len(lines) != 1 or lines[0] != lines[0].strip():
        raise PublicationRefusal(
            "unsupported", f"origin {role} authority must contain one canonical URL"
        )
    value = lines[0]
    patterns = (
        (
            "https",
            re.compile(
                r"https://github\.com/(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?)\Z"
            ),
        ),
        (
            "ssh",
            re.compile(r"git@github\.com:(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?)\Z"),
        ),
        (
            "ssh",
            re.compile(
                r"ssh://git@github\.com/(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?)\Z"
            ),
        ),
    )
    for transport, pattern in patterns:
        match = pattern.fullmatch(value)
        if match is None:
            continue
        repository = match.group("repo")
        if repository.endswith(".git"):
            repository = repository[:-4]
        if REPOSITORY_RE.fullmatch(repository):
            return {
                "host": "github.com",
                "repository": repository,
                "transport": transport,
            }
    raise PublicationRefusal(
        "unsupported", f"origin {role} authority is not a canonical credential-free GitHub URL"
    )


def _read_remote_identities(
    executor: CommandExecutor, cwd: Path, repository: str
) -> tuple[dict[str, str], dict[str, str]]:
    fetch_result = executor.run(["git", "remote", "get-url", "--all", "origin"], cwd=cwd)
    push_result = executor.run(["git", "remote", "get-url", "--push", "--all", "origin"], cwd=cwd)
    if fetch_result.returncode != 0 or push_result.returncode != 0:
        raise PublicationRefusal("unknown", "origin authority could not be read")
    fetch = _remote_identity(fetch_result.stdout, role="fetch")
    push = _remote_identity(push_result.stdout, role="push")
    if fetch["repository"] != repository:
        raise PublicationRefusal("drift", "origin fetch repository does not match the request")
    if push["repository"] != repository:
        raise PublicationRefusal("drift", "origin push repository does not match the request")
    if fetch["repository"] != push["repository"]:
        raise PublicationRefusal("drift", "origin fetch and push repositories differ")
    return fetch, push


def _read_github_ref(executor: CommandExecutor, cwd: Path, repository: str, ref: str) -> str:
    result = _checked(
        executor,
        ["gh", "api", "--method", "GET", f"repos/{repository}/git/ref/heads/{ref}"],
        cwd,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PublicationRefusal("unknown", "GitHub base ref readback was not JSON") from exc
    sha = _nested(payload, "object", "sha") if isinstance(payload, Mapping) else None
    if (
        not isinstance(payload, Mapping)
        or payload.get("ref") != f"refs/heads/{ref}"
        or _nested(payload, "object", "type") != "commit"
        or not isinstance(sha, str)
        or not GIT_SHA_RE.fullmatch(sha)
    ):
        raise PublicationRefusal("unknown", "GitHub base ref readback was malformed")
    return sha


def _read_authority_snapshot(
    executor: CommandExecutor,
    cwd: Path,
    repository: str,
    base_ref: str,
) -> PublicationAuthoritySnapshot:
    if base_ref != "main":
        raise PublicationRefusal("unsupported", "the normal publication path is restricted to main")
    fetch, push = _read_remote_identities(executor, cwd, repository)
    local_sha = _git_text(executor, cwd, "rev-parse", "origin/main")
    fetch_sha = _read_remote_head(executor, cwd, "main")
    github_sha = _read_github_ref(executor, cwd, repository, "main")
    if (
        not GIT_SHA_RE.fullmatch(local_sha)
        or fetch_sha is None
        or local_sha != fetch_sha
        or local_sha != github_sha
    ):
        raise PublicationRefusal(
            "drift", "local, fetch, and GitHub main authority do not name one exact commit"
        )
    return PublicationAuthoritySnapshot(
        fetch_identity=fetch,
        push_identity=push,
        base_ref="main",
        base_sha=local_sha,
    )


def _assert_authority_unchanged(
    executor: CommandExecutor, cwd: Path, plan: Mapping[str, Any]
) -> PublicationAuthoritySnapshot:
    snapshot = _read_authority_snapshot(
        executor,
        cwd,
        str(plan["repository"]),
        str(plan["git"]["base_ref"]),
    )
    if snapshot.as_mapping() != plan.get("authority"):
        raise PublicationRefusal("drift", "publication authority drift")
    return snapshot


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
    }


def _require_publishable_issue(issue: Mapping[str, Any], expected_number: int) -> None:
    if issue.get("number") != expected_number or issue.get("state") != "open":
        raise PublicationRefusal("drift", "governing Issue is not the expected open Issue")
    labels = set(issue.get("labels", []))
    if "agent:in-progress" not in labels or "agent:ready" in labels:
        raise PublicationRefusal("drift", "governing Issue is not actively claimed")


def _assert_issue_unchanged(executor: CommandExecutor, cwd: Path, plan: Mapping[str, Any]) -> None:
    issue = _read_issue(
        executor,
        cwd,
        str(plan["repository"]),
        int(plan["governing_issue"]["number"]),
    )
    if issue != plan["governing_issue"]:
        raise PublicationRefusal("drift", "governing Issue drift")
    _require_publishable_issue(issue, int(plan["governing_issue"]["number"]))


def _read_remote_head(executor: CommandExecutor, cwd: Path, branch: str) -> str | None:
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
    if (
        len(parts) != 2
        or parts[1] != f"refs/heads/{branch}"
        or not re.fullmatch(r"[0-9a-f]{40,64}", parts[0])
    ):
        raise PublicationRefusal("unknown", "remote branch readback was malformed")
    return parts[0]


def _read_pr_history(
    executor: CommandExecutor,
    cwd: Path,
    repository: str,
    branch: str,
) -> list[dict[str, Any]]:
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
            "state=all",
            "-f",
            f"head={owner}:{branch}",
            "-f",
            "per_page=2",
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


def _generate_pr_body(executor: CommandExecutor, cwd: Path, values: Mapping[str, Any]) -> str:
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
    if (
        normalized.get("lane") not in SUPPORTED_LANES
        or normalized.get("tier") not in SUPPORTED_TIERS
    ):
        raise PublicationRefusal("unsupported", "publication plan is outside the supported path")
    repository = normalized.get("repository")
    authority = normalized.get("authority")
    git = normalized.get("git")
    pr = normalized.get("pr")
    if not isinstance(repository, str) or not REPOSITORY_RE.fullmatch(repository):
        raise PublicationRefusal("drift", "publication plan repository is malformed")
    if not isinstance(authority, Mapping) or set(authority) != {
        "fetch_identity",
        "push_identity",
        "base_ref",
        "base_sha",
    }:
        raise PublicationRefusal("drift", "publication authority binding is malformed")
    for role in ("fetch_identity", "push_identity"):
        identity = authority.get(role)
        if (
            not isinstance(identity, Mapping)
            or set(identity) != {"host", "repository", "transport"}
            or identity.get("host") != "github.com"
            or identity.get("repository") != repository
            or identity.get("transport") not in {"https", "ssh"}
        ):
            raise PublicationRefusal("drift", f"publication {role} binding is malformed")
    if (
        authority.get("base_ref") != "main"
        or not isinstance(authority.get("base_sha"), str)
        or not GIT_SHA_RE.fullmatch(authority["base_sha"])
        or not isinstance(git, Mapping)
        or "origin_url" in git
        or git.get("base_ref") != "main"
        or git.get("base_remote_ref") != "origin/main"
        or git.get("base_sha") != authority.get("base_sha")
        or git.get("head_sha") != authority.get("base_sha")
        or not isinstance(pr, Mapping)
        or pr.get("base_ref") != "main"
    ):
        raise PublicationRefusal("drift", "publication main authority binding is inconsistent")
    body = pr.get("body")
    if not isinstance(body, str) or _sha256_text(body) != pr.get("body_sha256"):
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
    if (
        _git_text(executor, cwd, "rev-parse", plan["git"]["base_remote_ref"])
        != plan["authority"]["base_sha"]
    ):
        raise PublicationRefusal("drift", "base ref drift")
    current_head = _git_text(executor, cwd, "rev-parse", "HEAD")
    unstaged, staged, untracked = _changed_path_sets(executor, cwd)
    planned_paths = set(plan["git"]["intended_paths"])
    dirty = unstaged | staged | untracked
    if current_head == plan["git"]["head_sha"]:
        if dirty != planned_paths or not staged.issubset(planned_paths):
            raise PublicationRefusal("drift", "planned local paths drifted before commit")
        for expected in plan["git"]["path_states"]:
            observed = _path_state(executor, cwd, expected["path"], plan["git"]["base_sha"])
            if _content_binding(observed) != _content_binding(expected):
                raise PublicationRefusal("drift", f"planned content drift: {expected['path']}")
        state = (
            "staged" if staged == planned_paths and not (unstaged | untracked) else "uncommitted"
        )
        return state, None
    if dirty:
        raise PublicationRefusal("drift", "working tree is dirty after publication commit")
    parents = _git_text(executor, cwd, "rev-list", "--parents", "-n", "1", "HEAD").split()
    if parents != [current_head, plan["authority"]["base_sha"]]:
        raise PublicationRefusal("drift", "publication commit parent does not match the plan")
    message = _checked(executor, ["git", "show", "-s", "--format=%B", "HEAD"], cwd).stdout.rstrip(
        "\n"
    )
    if message != plan["commit"]["message"]:
        raise PublicationRefusal("drift", "publication commit message does not match the plan")
    committed_paths = _nul_paths(
        _checked(
            executor,
            [
                "git",
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                "-z",
                "--no-renames",
                "HEAD",
            ],
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


def _assert_staged_plan(executor: CommandExecutor, cwd: Path, plan: Mapping[str, Any]) -> None:
    unstaged, staged, untracked = _changed_path_sets(executor, cwd)
    if staged != set(plan["git"]["intended_paths"]) or unstaged or untracked:
        raise PublicationRefusal("drift", "staged paths do not exactly match the plan")
    for expected in plan["git"]["path_states"]:
        observed = _path_state(executor, cwd, expected["path"], plan["git"]["base_sha"])
        if _content_binding(observed) != _content_binding(expected):
            raise PublicationRefusal("drift", f"staged content drift: {expected['path']}")


def _run_workspace_gate(executor: CommandExecutor, cwd: Path, plan: Mapping[str, Any]) -> None:
    _checked(
        executor,
        [
            str(REPO_ROOT / "scripts/agent_workspace_preflight.sh"),
            "--expected-branch",
            plan["git"]["branch"],
            "--expected-worktree",
            plan["worktree"],
            "--base-branch",
            "main",
            "--allow-dirty",
        ],
        cwd,
    )


def _run_review_gate(executor: CommandExecutor, cwd: Path, plan: Mapping[str, Any]) -> None:
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


def _transition_readback(
    executor: CommandExecutor,
    cwd: Path,
    plan: Mapping[str, Any],
    commit_sha: str,
) -> tuple[PublicationAuthoritySnapshot, str | None, list[dict[str, Any]]]:
    authority = _assert_authority_unchanged(executor, cwd, plan)
    _assert_issue_unchanged(executor, cwd, plan)
    local_state, observed_commit = _observe_local_state(executor, cwd, plan)
    if local_state != "committed" or observed_commit != commit_sha:
        raise PublicationRefusal(
            "drift", "local publication commit drifted before an external transition"
        )
    remote_head = _read_remote_head(executor, cwd, plan["git"]["branch"])
    prs = _read_pr_history(
        executor,
        cwd,
        plan["repository"],
        plan["git"]["branch"],
    )
    return authority, remote_head, prs


def _resolve_pr_history(
    plan: Mapping[str, Any], prs: Sequence[Mapping[str, Any]], commit_sha: str | None
) -> dict[str, Any] | None:
    if not prs:
        return None
    if len(prs) != 1 or commit_sha is None:
        raise PublicationRefusal("unknown", "all-state PR history is not uniquely reconcilable")
    pr = dict(prs[0])
    expected = {
        "title": plan["pr"]["title"],
        "body": plan["pr"]["body"],
        "base_repo": plan["repository"],
        "base_ref": plan["git"]["base_ref"],
        "base_sha": plan["authority"]["base_sha"],
        "head_repo": plan["repository"],
        "head_ref": plan["git"]["branch"],
        "head_sha": commit_sha,
    }
    observed = {
        "title": pr.get("title"),
        "body": pr.get("body") or "",
        "base_repo": _nested(pr, "base", "repo", "full_name"),
        "base_ref": _nested(pr, "base", "ref"),
        "base_sha": _nested(pr, "base", "sha"),
        "head_repo": _nested(pr, "head", "repo", "full_name"),
        "head_ref": _nested(pr, "head", "ref"),
        "head_sha": _nested(pr, "head", "sha"),
    }
    if observed != expected:
        raise PublicationRefusal("unknown", "all-state PR history does not match the plan")
    state = str(pr.get("state", "")).lower()
    if state == "open" and pr.get("merged_at") is None:
        return pr
    if state == "closed" or pr.get("merged_at") is not None:
        raise PublicationRefusal(
            "terminal", "publication branch has exact closed or merged PR history"
        )
    raise PublicationRefusal("unknown", "all-state PR history has an unknown lifecycle state")


def _nested(value: Mapping[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _receipt(
    plan: Mapping[str, Any],
    authority: PublicationAuthoritySnapshot,
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
        "authority": authority.as_mapping(),
        "remote": {
            "repository": plan["repository"],
            "ref": f"refs/heads/{plan['git']['branch']}",
            "sha": commit_sha,
        },
        "pr": {
            "number": pr.get("number"),
            "state": str(pr.get("state", "")).lower(),
            "title": pr.get("title"),
            "body_sha256": _sha256_text(str(pr.get("body") or "")),
            "base_repository": _nested(pr, "base", "repo", "full_name"),
            "base_ref": _nested(pr, "base", "ref"),
            "base_sha": _nested(pr, "base", "sha"),
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
    plan.add_argument("--base-ref", choices=("main",), default="main")
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
                    "argv_sha256": _sha256_text(canonical_json(list(exc.result.argv))),
                    "stderr_sha256": _sha256_text(exc.result.stderr),
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
        print(
            canonical_json({"ok": False, "outcome": "invalid", "reason": str(exc)}), file=sys.stderr
        )
        return 2
    print(canonical_json(result))
    return 0


__all__ = [
    "CommandResult",
    "PublicationCommandError",
    "PublicationAuthoritySnapshot",
    "PublicationRefusal",
    "PublicationRequest",
    "SubprocessExecutor",
    "apply_publication_plan",
    "build_publication_plan",
    "canonical_json",
    "cli_main",
    "publication_plan_hash",
]
