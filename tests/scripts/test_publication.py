from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Sequence

import pytest

from app.builderops.publication import (
    CommandResult,
    PublicationCommandError,
    PublicationRefusal,
    PublicationRequest,
    SubprocessExecutor,
    apply_publication_plan,
    build_publication_plan,
    canonical_json,
    publication_plan_hash,
)
from scripts.pr_body_generator import generate_pr_body_from_mapping
from scripts.publication import main as publication_main


BASE_SHA = "a" * 40
HEAD_SHA = BASE_SHA
COMMIT_SHA = "c" * 40
RACED_HEAD_SHA = "e" * 40
CONFLICT_SHA = "d" * 40
BASE_BLOB = "1" * 40
STAGED_BLOB = "2" * 40
REPOSITORY = "RasmusTho/agentic-pkm-mvp"
BRANCH = "codex/publication-test"
GITHUB_HOST = "github.com"
HOST_QUALIFIED_REPOSITORY = f"{GITHUB_HOST}/{REPOSITORY}"
BODY_INPUTS = {
    "lane": "governance",
    "issue_number": 5230,
    "summary": ["Add deterministic publication plan/apply."],
    "sbs_impact": {
        "primary_subsystem": "Builder System / CES boundary",
        "secondary_subsystems": "delivery publication adapter",
        "write_class": "governance/docs/process",
        "persistence_impact": "Git commit, remote branch, and GitHub PR",
        "derived_rebuildable_impact": "Plan and receipt are rebuildable evidence",
        "new_or_changed_contract": "builder.publication-plan.v1",
        "owner_doc_impact": "updated in this PR",
        "transition_debt_impact": "reduces D11/D12",
        "boundary_risk": "no merge, closure, release, or deployment authority",
    },
    "owner_doc_resolution": "updated",
    "final_review_rounds": 0,
    "builderops_records": "none",
    "builderops_reason": "The governing Issue fully represents the planned work.",
    "notes": "Focused validation recorded in the publication receipt.",
}


def _request(worktree: Path) -> PublicationRequest:
    return PublicationRequest(
        repository=REPOSITORY,
        worktree=worktree,
        branch=BRANCH,
        base_ref="main",
        intended_paths=("feature.txt",),
        lane="governance",
        tier=2,
        risk_surfaces=(),
        risk_assessment_complete=True,
        review_gate_complete=True,
        governing_issue=5230,
        commit_message="Add deterministic publication adapter\n\nRefs #5230",
        pr_title="Add deterministic publication adapter",
        pr_body_inputs=BODY_INPUTS,
    )


def _issue() -> dict[str, object]:
    return {
        "number": 5230,
        "state": "open",
        "title": "builder: make normal PR publication deterministic with plan/apply",
        "body": "contract body",
        "labels": [{"name": "agent:in-progress"}, {"name": "lane:governance"}],
        "html_url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/5230",
    }


def _is_gh_api_call(call: Sequence[str], method: str | None = None) -> bool:
    args = tuple(call)
    if args[:4] != ("gh", "api", "--hostname", GITHUB_HOST):
        return False
    return method is None or args[4:6] == ("--method", method)


def _assert_gh_call_is_host_bound(call: tuple[str, ...]) -> None:
    if _is_gh_api_call(call):
        assert call[2:4] == ("--hostname", GITHUB_HOST)
        assert call[4] == "--method"
        return
    if call[:3] == ("gh", "pr", "create"):
        repository_index = call.index("--repo") + 1
        assert call[repository_index] == HOST_QUALIFIED_REPOSITORY
        return
    raise AssertionError(f"unrecognized gh call: {call}")


class FakeExecutor:
    def __init__(self, worktree: Path) -> None:
        self.worktree = worktree.resolve()
        self.phase = "uncommitted"
        self.head_sha = HEAD_SHA
        self.base_sha = BASE_SHA
        self.live_base_sha = BASE_SHA
        self.github_base_sha = BASE_SHA
        self.fetch_url = f"https://github.com/{REPOSITORY}.git"
        self.push_url = f"https://github.com/{REPOSITORY}.git"
        self.remote_head: str | None = None
        self.issue = _issue()
        self.prs: list[dict[str, object]] = []
        self.calls: list[tuple[str, ...]] = []
        self.failures: dict[str, int] = {}
        self.failure_stderr: dict[str, str] = {}
        self.effect_then_fail: set[str] = set()
        self.post_effect_readback_failures: dict[str, int] = {}
        self.last_failed_effect: str | None = None
        self.post_success_readback_failures: dict[tuple[str, str], int] = {}
        self.last_successful_effect: str | None = None
        self.advance_branch_during_push = False
        self.move_remote_before_push_to: str | None = None
        self.drift_main_after_review_to: str | None = None
        self.mutable_branch_tip = COMMIT_SHA
        self.pr_body = generate_pr_body_from_mapping(BODY_INPUTS)

    def _result(
        self,
        argv: Sequence[str],
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> CommandResult:
        return CommandResult(tuple(argv), returncode, stdout, stderr)

    def _failure(self, key: str, argv: Sequence[str]) -> CommandResult | None:
        if key not in self.failures:
            return None
        return self._result(
            argv,
            self.failures[key],
            stderr=self.failure_stderr.get(key, f"{key} failed"),
        )

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        input_text: str | None = None,
    ) -> CommandResult:
        del cwd, input_text
        args = tuple(argv)
        self.calls.append(args)

        if any(part.endswith("scripts/pr_body_generator.py") for part in args):
            return self._failure("pr-body", args) or self._result(args, stdout=self.pr_body)
        if any(part.endswith("scripts/agent_workspace_preflight.sh") for part in args):
            key = "workspace-prepush" if self.phase == "committed" else "workspace"
            return self._failure(key, args) or self._result(args, stdout='{"ok":true}\n')
        if any(part.endswith("scripts/review_before_ci_gate.py") for part in args):
            if self.drift_main_after_review_to is not None:
                self.live_base_sha = self.drift_main_after_review_to
                self.github_base_sha = self.drift_main_after_review_to
            return self._failure("review", args) or self._result(args, stdout='{"ok":true}\n')

        if args[:2] == ("git", "rev-parse"):
            if args[2:] == ("--show-toplevel",):
                return self._result(args, stdout=f"{self.worktree}\n")
            if args[2:] == ("HEAD",):
                head = COMMIT_SHA if self.phase == "committed" else self.head_sha
                return self._result(args, stdout=f"{head}\n")
            if args[2:] == ("origin/main",):
                return self._result(args, stdout=f"{self.base_sha}\n")
        if args[:2] == ("git", "branch"):
            return self._result(args, stdout=f"{BRANCH}\n")
        if args[:3] == ("git", "merge-base", "--is-ancestor"):
            return self._result(args)
        if args[:3] == ("git", "remote", "get-url"):
            url = self.push_url if "--push" in args else self.fetch_url
            return self._result(args, stdout=f"{url}\n")
        if args[:3] == ("git", "diff", "--name-only"):
            cached = "--cached" in args
            if cached:
                paths = ("feature.txt",) if self.phase == "staged" else ()
            else:
                paths = ("feature.txt",) if self.phase == "uncommitted" else ()
            return self._result(args, stdout="\0".join(paths) + ("\0" if paths else ""))
        if args[:3] == ("git", "ls-files", "--others"):
            return self._result(args)
        if args[:3] == ("git", "ls-files", "--stage"):
            blob = STAGED_BLOB if self.phase == "staged" else BASE_BLOB
            return self._result(args, stdout=f"100644 {blob} 0\tfeature.txt\n")
        if args[:2] == ("git", "ls-tree"):
            return self._result(args, stdout=f"100644 blob {BASE_BLOB}\tfeature.txt\n")
        if args[:2] == ("git", "ls-remote"):
            unavailable = self.post_success_readback_failures.get(
                (self.last_successful_effect or "", "remote")
            )
            if unavailable is not None:
                return self._result(args, unavailable, stderr="remote readback failed")
            if (
                self.last_failed_effect in {"reserve", "push"}
                and self.last_failed_effect in self.post_effect_readback_failures
            ):
                return self._result(
                    args,
                    self.post_effect_readback_failures[self.last_failed_effect],
                    stderr=f"{self.last_failed_effect} readback failed",
                )
            ref = args[-1]
            if ref == "refs/heads/main":
                value = f"{self.live_base_sha}\trefs/heads/main\n"
            else:
                value = (
                    "" if self.remote_head is None else f"{self.remote_head}\trefs/heads/{BRANCH}\n"
                )
            return self._result(args, stdout=value)
        if args[:2] == ("git", "add"):
            failed = self._failure("stage", args)
            if failed:
                return failed
            self.phase = "staged"
            return self._result(args)
        if args[:2] == ("git", "commit"):
            failed = self._failure("commit", args)
            if failed:
                return failed
            self.phase = "committed"
            return self._result(args, stdout=f"[{BRANCH} {COMMIT_SHA[:7]}] commit\n")
        if args[:2] == ("git", "rev-list"):
            return self._result(args, stdout=f"{COMMIT_SHA} {HEAD_SHA}\n")
        if args[:2] == ("git", "show"):
            return self._result(
                args, stdout="Add deterministic publication adapter\n\nRefs #5230\n"
            )
        if args[:2] == ("git", "diff-tree"):
            return self._result(args, stdout="feature.txt\0")
        if args[:2] == ("git", "push"):
            if self.move_remote_before_push_to is not None:
                self.remote_head = self.move_remote_before_push_to
            if self.advance_branch_during_push:
                self.mutable_branch_tip = RACED_HEAD_SHA
            source = args[-1].split(":", 1)[0]
            pushed_sha = self.mutable_branch_tip if source == BRANCH else source
            failed = self._failure("push", args)
            if failed:
                self.last_failed_effect = "push"
                if "push" in self.effect_then_fail:
                    self.remote_head = pushed_sha
                return failed
            if self.remote_head != BASE_SHA:
                return self._result(args, 1, stderr="non-fast-forward")
            self.remote_head = pushed_sha
            self.last_successful_effect = "push"
            return self._result(args, stdout="pushed\n")

        if _is_gh_api_call(args, "GET"):
            endpoint = args[6]
            if endpoint.endswith("/issues/5230"):
                unavailable = self.post_success_readback_failures.get(
                    (self.last_successful_effect or "", "issue")
                )
                if unavailable is not None:
                    return self._result(args, unavailable, stderr="Issue readback failed")
                return self._result(args, stdout=json.dumps(self.issue))
            if endpoint.endswith("/git/ref/heads/main"):
                return self._result(
                    args,
                    stdout=json.dumps(
                        {
                            "ref": "refs/heads/main",
                            "object": {"type": "commit", "sha": self.github_base_sha},
                        }
                    ),
                )
            if endpoint.endswith("/pulls"):
                unavailable = self.post_success_readback_failures.get(
                    (self.last_successful_effect or "", "pr")
                )
                if unavailable is not None:
                    return self._result(args, unavailable, stderr="PR readback failed")
                if (
                    self.last_failed_effect == "pr-create"
                    and "pr-create" in self.post_effect_readback_failures
                ):
                    return self._result(
                        args,
                        self.post_effect_readback_failures["pr-create"],
                        stderr="PR readback failed",
                    )
                return self._result(args, stdout=json.dumps(self.prs))
        if _is_gh_api_call(args, "POST"):
            endpoint = args[6]
            if endpoint.endswith("/git/refs"):
                failed = self._failure("reserve", args)
                if failed:
                    self.last_failed_effect = "reserve"
                    if "reserve" in self.effect_then_fail:
                        self.remote_head = BASE_SHA
                    return failed
                if self.remote_head is not None:
                    return self._result(args, 422, stderr="Reference already exists")
                self.remote_head = BASE_SHA
                self.last_successful_effect = "reserve"
                return self._result(
                    args,
                    stdout=json.dumps({"ref": f"refs/heads/{BRANCH}", "object": {"sha": BASE_SHA}}),
                )
        if args[:3] == ("gh", "pr", "create"):
            failed = self._failure("pr-create", args)
            if failed:
                self.last_failed_effect = "pr-create"
                if "pr-create" in self.effect_then_fail:
                    self.prs = [self._exact_pr()]
                return failed
            self.prs = [self._exact_pr()]
            self.last_successful_effect = "pr-create"
            return self._result(
                args, stdout="https://github.com/RasmusTho/agentic-pkm-mvp/pull/6000\n"
            )
        raise AssertionError(f"unexpected command: {args}")

    def _exact_pr(self, *, state: str = "open", merged: bool = False) -> dict[str, object]:
        return {
            "number": 6000,
            "html_url": "https://github.com/RasmusTho/agentic-pkm-mvp/pull/6000",
            "state": state,
            "merged_at": "2026-08-30T22:00:00Z" if merged else None,
            "title": "Add deterministic publication adapter",
            "body": self.pr_body,
            "base": {
                "ref": "main",
                "sha": BASE_SHA,
                "repo": {"full_name": REPOSITORY},
            },
            "head": {
                "ref": BRANCH,
                "sha": COMMIT_SHA,
                "repo": {"full_name": REPOSITORY},
            },
        }


class GitHubFakeExecutor:
    def __init__(self) -> None:
        self.real = SubprocessExecutor()
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        input_text: str | None = None,
    ) -> CommandResult:
        self.calls.append(tuple(argv))
        if argv[:3] == ["git", "remote", "get-url"]:
            return CommandResult(tuple(argv), 0, f"https://github.com/{REPOSITORY}.git\n", "")
        if _is_gh_api_call(argv, "GET"):
            if str(argv[6]).endswith("/issues/5230"):
                payload: object = _issue()
            elif str(argv[6]).endswith("/git/ref/heads/main"):
                payload = {
                    "ref": "refs/heads/main",
                    "object": {
                        "type": "commit",
                        "sha": _run("git", "rev-parse", "origin/main", cwd=cwd).strip(),
                    },
                }
            else:
                payload = []
            return CommandResult(tuple(argv), 0, json.dumps(payload), "")
        return self.real.run(argv, cwd=cwd, input_text=input_text)


def _run(*argv: str, cwd: Path) -> str:
    return subprocess.run(argv, cwd=cwd, check=True, capture_output=True, text=True).stdout


def test_publication_plan_is_canonical_hash_bound_and_read_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--bare", "--initial-branch=main", remote], check=True)
    subprocess.run(["git", "init", "--initial-branch=main", repo], check=True)
    _run("git", "config", "user.email", "test@example.com", cwd=repo)
    _run("git", "config", "user.name", "Test User", cwd=repo)
    (repo / "feature.txt").write_text("old\n", encoding="utf-8")
    _run("git", "add", "feature.txt", cwd=repo)
    _run("git", "commit", "-m", "base", cwd=repo)
    _run("git", "remote", "add", "origin", str(remote), cwd=repo)
    _run("git", "push", "origin", "main", cwd=repo)
    _run("git", "checkout", "-b", BRANCH, cwd=repo)
    (repo / "feature.txt").write_text("new\n", encoding="utf-8")
    before = {
        "status": subprocess.run(
            ["git", "status", "--porcelain=v2", "-z"], cwd=repo, check=True, capture_output=True
        ).stdout,
        "index": hashlib.sha256((repo / ".git/index").read_bytes()).hexdigest(),
        "refs": _run("git", "show-ref", cwd=repo),
        "objects": _run("git", "count-objects", "-v", cwd=repo),
        "head": _run("git", "rev-parse", "HEAD", cwd=repo),
    }
    executor = GitHubFakeExecutor()

    first = build_publication_plan(_request(repo), executor=executor)
    second = build_publication_plan(_request(repo), executor=executor)
    body_input = tmp_path / "pr-body.json"
    body_input.write_text(json.dumps(BODY_INPUTS), encoding="utf-8")
    assert (
        publication_main(
            [
                "plan",
                "--repository",
                REPOSITORY,
                "--worktree",
                str(repo),
                "--branch",
                BRANCH,
                "--path",
                "feature.txt",
                "--lane",
                "governance",
                "--tier",
                "2",
                "--risk-assessment-complete",
                "--review-gate-complete",
                "--governing-issue",
                "5230",
                "--commit-message",
                "Add deterministic publication adapter\n\nRefs #5230",
                "--pr-title",
                "Add deterministic publication adapter",
                "--pr-body-input-json",
                str(body_input),
            ],
            executor=executor,
        )
        == 0
    )
    cli_plan = json.loads(capsys.readouterr().out)

    assert canonical_json(first) == canonical_json(second)
    assert cli_plan == first
    assert first["schema"] == "builder.publication-plan.v1"
    assert first["plan_sha256"] == publication_plan_hash(first)
    assert (
        first["pr"]["body_sha256"]
        == hashlib.sha256(generate_pr_body_from_mapping(BODY_INPUTS).encode("utf-8")).hexdigest()
    )
    assert first["git"]["intended_paths"] == ["feature.txt"]
    assert first["authority"] == {
        "fetch_identity": {
            "host": "github.com",
            "repository": REPOSITORY,
            "transport": "https",
        },
        "push_identity": {
            "host": "github.com",
            "repository": REPOSITORY,
            "transport": "https",
        },
        "base_ref": "main",
        "base_sha": first["git"]["base_sha"],
    }
    assert "origin_url" not in first["git"]
    assert "https://github.com" not in canonical_json(first)
    after = {
        "status": subprocess.run(
            ["git", "status", "--porcelain=v2", "-z"], cwd=repo, check=True, capture_output=True
        ).stdout,
        "index": hashlib.sha256((repo / ".git/index").read_bytes()).hexdigest(),
        "refs": _run("git", "show-ref", cwd=repo),
        "objects": _run("git", "count-objects", "-v", cwd=repo),
        "head": _run("git", "rev-parse", "HEAD", cwd=repo),
    }
    assert after == before
    assert all(
        _is_gh_api_call(call, "GET") for call in executor.calls if call and call[0] == "gh"
    )
    pr_reads = [call for call in executor.calls if call and call[-1] == "per_page=2"]
    assert pr_reads
    assert all("state=all" in call for call in pr_reads)


def test_publication_plan_rejects_non_main_without_observation(tmp_path: Path) -> None:
    executor = FakeExecutor(tmp_path)

    with pytest.raises(PublicationRefusal, match="restricted to main") as raised:
        build_publication_plan(replace(_request(tmp_path), base_ref="release"), executor=executor)

    assert raised.value.outcome == "unsupported"
    assert executor.calls == []


def test_publication_plan_binds_effective_push_repository_before_github_reads(
    tmp_path: Path,
) -> None:
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    executor.push_url = "git@github.com:another-owner/another-repo.git"

    with pytest.raises(PublicationRefusal, match="push repository") as raised:
        build_publication_plan(_request(tmp_path), executor=executor)

    assert raised.value.outcome == "drift"
    assert not any(call and call[0] == "gh" for call in executor.calls)


def test_publication_pins_every_github_read_and_effect_when_gh_host_is_hostile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GH_HOST", "redirect.invalid")
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)

    plan = build_publication_plan(_request(tmp_path), executor=executor)
    apply_publication_plan(
        plan,
        expected_plan_sha256=plan["plan_sha256"],
        executor=executor,
    )

    gh_calls = [call for call in executor.calls if call and call[0] == "gh"]
    assert gh_calls
    assert any(call[:2] == ("gh", "api") and "GET" in call for call in gh_calls)
    assert any(call[:2] == ("gh", "api") and "POST" in call for call in gh_calls)
    assert any(call[:3] == ("gh", "pr", "create") for call in gh_calls)
    for call in gh_calls:
        _assert_gh_call_is_host_bound(call)


def test_publication_cli_never_emits_raw_credential_remote_url(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "publication-token-should-not-leak"
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    body_input = tmp_path / "pr-body.json"
    body_input.write_text(json.dumps(BODY_INPUTS), encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    executor.fetch_url = f"https://{secret}@github.com/{REPOSITORY}.git"

    result = publication_main(
        [
            "plan",
            "--repository",
            REPOSITORY,
            "--worktree",
            str(tmp_path),
            "--branch",
            BRANCH,
            "--path",
            "feature.txt",
            "--lane",
            "governance",
            "--tier",
            "2",
            "--risk-assessment-complete",
            "--review-gate-complete",
            "--governing-issue",
            "5230",
            "--commit-message",
            "Add deterministic publication adapter\n\nRefs #5230",
            "--pr-title",
            "Add deterministic publication adapter",
            "--pr-body-input-json",
            str(body_input),
        ],
        executor=executor,
    )

    captured = capsys.readouterr()
    assert result == 3
    assert secret not in captured.out
    assert secret not in captured.err
    assert "https://" not in captured.err


def test_publication_hashes_symlink_target_without_serializing_it_and_detects_drift(
    tmp_path: Path,
) -> None:
    secret_target = "https://user:publication-secret@github.com/private/repo.git"
    symlink = tmp_path / "feature.txt"
    symlink.symlink_to(secret_target)
    executor = FakeExecutor(tmp_path)

    plan = build_publication_plan(_request(tmp_path), executor=executor)

    path_state = plan["git"]["path_states"][0]
    encoded_target = secret_target.encode("utf-8")
    assert path_state["kind"] == "symlink"
    assert path_state["size"] == len(encoded_target)
    assert path_state["sha256"] == hashlib.sha256(encoded_target).hexdigest()
    assert "target" not in path_state
    assert secret_target not in canonical_json(plan)

    symlink.unlink()
    symlink.symlink_to(f"{secret_target}-changed")
    executor.calls.clear()
    with pytest.raises(PublicationRefusal, match="planned content drift") as raised:
        apply_publication_plan(
            plan,
            expected_plan_sha256=plan["plan_sha256"],
            executor=executor,
        )

    assert raised.value.outcome == "drift"
    assert not any(
        call[:2] in {("git", "add"), ("git", "commit"), ("git", "push")}
        or call[:3] == ("gh", "pr", "create")
        or (call[:2] == ("gh", "api") and "POST" in call)
        for call in executor.calls
    )


@pytest.mark.parametrize(
    "fetch_url",
    [
        f"https://github.com.evil.invalid/{REPOSITORY}.git",
        f"https://github.com/{REPOSITORY}.git?credential=value",
        f"https://github.com/{REPOSITORY}/extra.git",
        f"https://github.com/{REPOSITORY}.git\nhttps://github.com/other/repo.git",
    ],
)
def test_publication_plan_rejects_noncanonical_fetch_authority(
    tmp_path: Path, fetch_url: str
) -> None:
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    executor.fetch_url = fetch_url

    with pytest.raises(PublicationRefusal, match="fetch authority") as raised:
        build_publication_plan(_request(tmp_path), executor=executor)

    assert raised.value.outcome == "unsupported"
    assert not any(call and call[0] == "gh" for call in executor.calls)


def test_publication_plan_refuses_disagreeing_live_main_authorities(
    tmp_path: Path,
) -> None:
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    executor.live_base_sha = CONFLICT_SHA

    with pytest.raises(PublicationRefusal, match="main authority") as raised:
        build_publication_plan(_request(tmp_path), executor=executor)

    assert raised.value.outcome == "drift"
    assert not any(
        call[:2] in {("git", "add"), ("git", "commit"), ("git", "push")}
        or call[:3] == ("gh", "pr", "create")
        or _is_gh_api_call(call, "POST")
        for call in executor.calls
    )


def test_publication_plan_refuses_preexisting_commit_ahead_of_base_before_effects(
    tmp_path: Path,
) -> None:
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    executor.head_sha = "b" * 40

    with pytest.raises(PublicationRefusal, match="HEAD to equal the bound base") as raised:
        build_publication_plan(_request(tmp_path), executor=executor)

    assert raised.value.outcome == "unsupported"
    assert not any(call and call[0] == "gh" for call in executor.calls)
    assert not any(
        call[:2] in {("git", "add"), ("git", "commit"), ("git", "push")} for call in executor.calls
    )


@pytest.mark.parametrize(
    "commit_message",
    [
        "Add adapter because this fixes #5230",
        "Add adapter: Fix: #5230 after validation",
        "Add adapter\n\nCLOSES #5230 after validation",
        "Add adapter; Closed: octo-org/octo-repo#5230",
        "Add adapter; ReSoLvEd RasmusTho/agentic-pkm-mvp#5230",
        "Add adapter because this resolves https://github.com/octo-org/octo-repo/issues/5230",
    ],
)
def test_publication_plan_rejects_closing_issue_references_anywhere(
    tmp_path: Path, commit_message: str
) -> None:
    executor = FakeExecutor(tmp_path)

    with pytest.raises(PublicationRefusal, match="closing Issue reference") as raised:
        build_publication_plan(
            replace(_request(tmp_path), commit_message=commit_message),
            executor=executor,
        )

    assert raised.value.outcome == "unsupported"
    assert executor.calls == []


@pytest.mark.parametrize(
    "commit_message",
    [
        "Add adapter\n\nRefs #5230",
        "Add adapter\n\nRefs octo-org/octo-repo#5230",
        "Add adapter\n\nRefs https://github.com/octo-org/octo-repo/issues/5230",
    ],
)
def test_publication_plan_allows_non_closing_issue_references(
    tmp_path: Path, commit_message: str
) -> None:
    executor = FakeExecutor(tmp_path)

    plan = build_publication_plan(
        replace(_request(tmp_path), commit_message=commit_message),
        executor=executor,
    )

    assert plan["commit"]["message"] == commit_message


def test_publication_apply_revalidates_drift_and_orders_existing_gates(tmp_path: Path) -> None:
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    plan = build_publication_plan(_request(tmp_path), executor=executor)
    executor.calls.clear()
    executor.issue = {**executor.issue, "body": "changed contract"}

    with pytest.raises(PublicationRefusal, match="governing Issue drift") as raised:
        apply_publication_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=executor)
    assert raised.value.outcome == "drift"
    assert not any(
        call[:2] in {("git", "add"), ("git", "commit"), ("git", "push")} for call in executor.calls
    )

    executor.issue = _issue()
    executor.calls.clear()
    receipt = apply_publication_plan(
        plan, expected_plan_sha256=plan["plan_sha256"], executor=executor
    )
    assert receipt["schema"] == "builder.publication-receipt.v1"
    workspace_positions = [
        i
        for i, call in enumerate(executor.calls)
        if any(x.endswith("agent_workspace_preflight.sh") for x in call)
    ]
    assert len(workspace_positions) == 2
    positions = {
        "workspace_precommit": workspace_positions[0],
        "stage": next(i for i, call in enumerate(executor.calls) if call[:2] == ("git", "add")),
        "commit": next(i for i, call in enumerate(executor.calls) if call[:2] == ("git", "commit")),
        "review": next(
            i
            for i, call in enumerate(executor.calls)
            if any(x.endswith("review_before_ci_gate.py") for x in call)
        ),
        "pr_body": max(
            i
            for i, call in enumerate(executor.calls)
            if any(x.endswith("pr_body_generator.py") for x in call)
        ),
        "workspace_prepush": workspace_positions[1],
        "reserve": next(
            i
            for i, call in enumerate(executor.calls)
            if _is_gh_api_call(call, "POST")
        ),
        "push": next(i for i, call in enumerate(executor.calls) if call[:2] == ("git", "push")),
        "pr_create": next(
            i for i, call in enumerate(executor.calls) if call[:3] == ("gh", "pr", "create")
        ),
    }
    assert list(positions.values()) == sorted(positions.values())
    reserve = executor.calls[positions["reserve"]]
    assert f"ref=refs/heads/{BRANCH}" in reserve
    assert f"sha={BASE_SHA}" in reserve
    assert receipt["authority"]["base_sha"] == BASE_SHA
    assert receipt["pr"]["base_sha"] == BASE_SHA
    assert receipt["authority"]["fetch_identity"]["repository"] == REPOSITORY
    assert receipt["authority"]["push_identity"]["repository"] == REPOSITORY
    assert "https://" not in canonical_json(receipt)


def test_publication_effects_are_monotonic_and_never_force_delete_or_reset(
    tmp_path: Path,
) -> None:
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    plan = build_publication_plan(_request(tmp_path), executor=executor)
    executor.calls.clear()

    apply_publication_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=executor)

    effects = [
        call
        for call in executor.calls
        if _is_gh_api_call(call, "POST")
        or call[:2] == ("git", "push")
        or call[:3] == ("gh", "pr", "create")
    ]
    assert [call[:2] for call in effects] == [("gh", "api"), ("git", "push"), ("gh", "pr")]
    flattened = "\n".join(" ".join(call) for call in executor.calls)
    assert "--force" not in flattened
    assert "--delete" not in flattened
    assert "git reset" not in flattened
    assert not any(
        call[:2] == ("git", "push") and call[-1].startswith("+") for call in executor.calls
    )


def test_publication_reconciles_create_ref_nonzero_after_effect(tmp_path: Path) -> None:
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    plan = build_publication_plan(_request(tmp_path), executor=executor)
    executor.failures["reserve"] = 125
    executor.effect_then_fail.add("reserve")

    receipt = apply_publication_plan(
        plan, expected_plan_sha256=plan["plan_sha256"], executor=executor
    )

    assert receipt["outcome"] == "success"
    assert receipt["reconciled"] is True
    assert executor.remote_head == COMMIT_SHA
    assert sum(_is_gh_api_call(call, "POST") for call in executor.calls) == 1


def test_publication_create_ref_nonzero_without_effect_is_retryable(
    tmp_path: Path,
) -> None:
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    plan = build_publication_plan(_request(tmp_path), executor=executor)
    executor.failures["reserve"] = 42

    with pytest.raises(PublicationCommandError) as raised:
        apply_publication_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=executor)

    assert raised.value.result.returncode == 42
    assert executor.phase == "committed"
    assert executor.remote_head is None
    assert not any(
        call[:2] == ("git", "push") or call[:3] == ("gh", "pr", "create") for call in executor.calls
    )

    executor.failures.pop("reserve")
    receipt = apply_publication_plan(
        plan, expected_plan_sha256=plan["plan_sha256"], executor=executor
    )
    assert receipt["outcome"] == "success"


def test_publication_cli_hashes_raw_command_error_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "credential-like-value"
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    plan = build_publication_plan(_request(tmp_path), executor=executor)
    executor.failures["reserve"] = 55
    executor.failure_stderr["reserve"] = f"failed at https://{secret}@github.com/{REPOSITORY}.git"
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(canonical_json(plan), encoding="utf-8")

    result = publication_main(
        [
            "apply",
            "--plan-file",
            str(plan_file),
            "--expected-plan-sha256",
            plan["plan_sha256"],
        ],
        executor=executor,
    )

    output = capsys.readouterr().err
    assert result == 55
    assert secret not in output
    assert "https://" not in output
    assert "argv_sha256" in output
    assert "stderr_sha256" in output


def test_publication_create_ref_nonzero_with_unavailable_readback_is_unknown(
    tmp_path: Path,
) -> None:
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    plan = build_publication_plan(_request(tmp_path), executor=executor)
    executor.failures["reserve"] = 125
    executor.post_effect_readback_failures["reserve"] = 23

    with pytest.raises(PublicationRefusal) as raised:
        apply_publication_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=executor)

    assert raised.value.outcome == "unknown"
    assert not any(
        call[:2] == ("git", "push") or call[:3] == ("gh", "pr", "create") for call in executor.calls
    )


def test_publication_resumes_from_exact_base_reservation(tmp_path: Path) -> None:
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    plan = build_publication_plan(_request(tmp_path), executor=executor)
    executor.phase = "committed"
    executor.remote_head = BASE_SHA
    executor.calls.clear()

    receipt = apply_publication_plan(
        plan, expected_plan_sha256=plan["plan_sha256"], executor=executor
    )

    assert receipt["reconciled"] is True
    assert not any(_is_gh_api_call(call, "POST") for call in executor.calls)
    assert sum(call[:2] == ("git", "push") for call in executor.calls) == 1


def test_publication_stops_when_main_drifts_before_reservation(tmp_path: Path) -> None:
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    plan = build_publication_plan(_request(tmp_path), executor=executor)
    executor.drift_main_after_review_to = CONFLICT_SHA

    with pytest.raises(PublicationRefusal, match="authority") as raised:
        apply_publication_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=executor)

    assert raised.value.outcome == "drift"
    assert not any(
        _is_gh_api_call(call, "POST")
        or call[:2] == ("git", "push")
        or call[:3] == ("gh", "pr", "create")
        for call in executor.calls
    )


def test_publication_stops_after_concurrent_ref_movement(tmp_path: Path) -> None:
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    plan = build_publication_plan(_request(tmp_path), executor=executor)
    executor.move_remote_before_push_to = CONFLICT_SHA

    with pytest.raises(PublicationRefusal, match="conflicting remote") as raised:
        apply_publication_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=executor)

    assert raised.value.outcome == "unknown"
    assert executor.remote_head == CONFLICT_SHA
    assert not any(call[:3] == ("gh", "pr", "create") for call in executor.calls)


def test_publication_pushes_exact_commit_refspec_despite_mutable_branch_race(
    tmp_path: Path,
) -> None:
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    plan = build_publication_plan(_request(tmp_path), executor=executor)
    executor.advance_branch_during_push = True

    receipt = apply_publication_plan(
        plan, expected_plan_sha256=plan["plan_sha256"], executor=executor
    )

    push_calls = [call for call in executor.calls if call[:2] == ("git", "push")]
    assert push_calls == [("git", "push", "origin", f"{COMMIT_SHA}:refs/heads/{BRANCH}")]
    assert executor.mutable_branch_tip == RACED_HEAD_SHA
    assert executor.remote_head == receipt["commit_sha"] == COMMIT_SHA


@pytest.mark.parametrize("effect", ["reserve", "push", "pr-create"])
def test_publication_reconciles_effect_success_after_nonzero_command(
    tmp_path: Path, effect: str
) -> None:
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    plan = build_publication_plan(_request(tmp_path), executor=executor)
    executor.failures[effect] = 19
    executor.effect_then_fail.add(effect)

    receipt = apply_publication_plan(
        plan, expected_plan_sha256=plan["plan_sha256"], executor=executor
    )

    assert receipt["outcome"] == "success"
    assert receipt["reconciled"] is True
    assert executor.remote_head == COMMIT_SHA
    assert len(executor.prs) == 1


def test_publication_classifies_empty_or_delayed_pr_readback_as_unknown(
    tmp_path: Path,
) -> None:
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    plan = build_publication_plan(_request(tmp_path), executor=executor)
    executor.failures["pr-create"] = 20

    with pytest.raises(PublicationRefusal) as raised:
        apply_publication_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=executor)

    assert raised.value.outcome == "unknown"
    effect_calls = [
        call
        for call in executor.calls
        if call[:2] == ("git", "push") or call[:3] == ("gh", "pr", "create")
    ]
    assert len(effect_calls) == 2
    effect_position = max(i for i, call in enumerate(executor.calls) if call in effect_calls)
    post_effect_readbacks = [
        call
        for call in executor.calls[effect_position + 1 :]
        if call[:2] == ("git", "ls-remote")
        or (_is_gh_api_call(call, "GET") and call[6].endswith("/pulls"))
    ]
    assert len(post_effect_readbacks) == 3


@pytest.mark.parametrize("effect", ["reserve", "push", "pr-create"])
def test_publication_classifies_unavailable_post_effect_readback_as_unknown(
    tmp_path: Path, effect: str
) -> None:
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    plan = build_publication_plan(_request(tmp_path), executor=executor)
    executor.failures[effect] = 22
    executor.post_effect_readback_failures[effect] = 23

    with pytest.raises(PublicationRefusal) as raised:
        apply_publication_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=executor)

    assert raised.value.outcome == "unknown"


@pytest.mark.parametrize(
    ("effect", "surface"),
    [
        ("push", "issue"),
        ("push", "remote"),
        ("push", "pr"),
        ("pr-create", "remote"),
        ("pr-create", "pr"),
    ],
)
def test_publication_classifies_unavailable_readback_after_successful_effect_as_unknown(
    tmp_path: Path, effect: str, surface: str
) -> None:
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    plan = build_publication_plan(_request(tmp_path), executor=executor)
    executor.post_success_readback_failures[(effect, surface)] = 4

    with pytest.raises(PublicationRefusal) as raised:
        apply_publication_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=executor)

    assert raised.value.outcome == "unknown"


@pytest.mark.parametrize(
    ("effect", "surface"),
    [("push", "issue"), ("pr-create", "remote")],
)
def test_publication_cli_returns_exit_4_for_unavailable_readback_after_successful_effect(
    tmp_path: Path, effect: str, surface: str
) -> None:
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    plan = build_publication_plan(_request(tmp_path), executor=executor)
    executor.post_success_readback_failures[(effect, surface)] = 4
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(canonical_json(plan), encoding="utf-8")

    result = publication_main(
        [
            "apply",
            "--plan-file",
            str(plan_file),
            "--expected-plan-sha256",
            plan["plan_sha256"],
        ],
        executor=executor,
    )

    assert result == 4


def test_publication_apply_reconciles_exact_success_partial_and_unknown_states(
    tmp_path: Path,
) -> None:
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    plan = build_publication_plan(_request(tmp_path), executor=executor)

    first = apply_publication_plan(
        plan, expected_plan_sha256=plan["plan_sha256"], executor=executor
    )
    before_repeat = len(executor.calls)
    repeated = apply_publication_plan(
        plan, expected_plan_sha256=plan["plan_sha256"], executor=executor
    )
    repeated_calls = executor.calls[before_repeat:]
    assert first["pr"]["number"] == repeated["pr"]["number"] == 6000
    assert repeated["reconciled"] is True
    assert not any(
        call[:2] in {("git", "commit"), ("git", "push")} or call[:3] == ("gh", "pr", "create")
        for call in repeated_calls
    )

    partial = FakeExecutor(tmp_path)
    partial.phase = "committed"
    partial.remote_head = COMMIT_SHA
    partial_receipt = apply_publication_plan(
        plan, expected_plan_sha256=plan["plan_sha256"], executor=partial
    )
    assert partial_receipt["reconciled"] is True
    assert sum(call[:3] == ("gh", "pr", "create") for call in partial.calls) == 1
    assert not any(call[:2] in {("git", "commit"), ("git", "push")} for call in partial.calls)
    partial_workspace = [
        i
        for i, call in enumerate(partial.calls)
        if any(x.endswith("agent_workspace_preflight.sh") for x in call)
    ]
    assert len(partial_workspace) == 1
    assert partial_workspace[0] < next(
        i for i, call in enumerate(partial.calls) if call[:3] == ("gh", "pr", "create")
    )

    unknown = FakeExecutor(tmp_path)
    unknown.phase = "committed"
    unknown.remote_head = "d" * 40
    with pytest.raises(PublicationRefusal) as raised:
        apply_publication_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=unknown)
    assert raised.value.outcome == "unknown"
    assert not any(
        call[:2] == ("git", "push") or call[:3] == ("gh", "pr", "create") for call in unknown.calls
    )

    mismatched_pr = FakeExecutor(tmp_path)
    mismatched_pr.phase = "committed"
    mismatched_pr.remote_head = COMMIT_SHA
    wrong = mismatched_pr._exact_pr()
    wrong["base"] = {"ref": "other", "repo": {"full_name": REPOSITORY}}
    mismatched_pr.prs = [wrong]
    with pytest.raises(PublicationRefusal) as raised:
        apply_publication_plan(
            plan, expected_plan_sha256=plan["plan_sha256"], executor=mismatched_pr
        )
    assert raised.value.outcome == "unknown"
    assert not any(call[:3] == ("gh", "pr", "create") for call in mismatched_pr.calls)

    unreviewed = FakeExecutor(tmp_path)
    unreviewed_plan = dict(plan)
    unreviewed_plan["review_gate_complete"] = False
    unreviewed_plan["plan_sha256"] = publication_plan_hash(unreviewed_plan)
    with pytest.raises(PublicationRefusal, match="review gate completion") as raised:
        apply_publication_plan(
            unreviewed_plan,
            expected_plan_sha256=unreviewed_plan["plan_sha256"],
            executor=unreviewed,
        )
    assert raised.value.outcome == "drift"
    assert unreviewed.calls == []


@pytest.mark.parametrize(
    ("state", "merged"),
    [("closed", False), ("closed", True)],
)
def test_publication_refuses_exact_closed_or_merged_pr_history(
    tmp_path: Path, state: str, merged: bool
) -> None:
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    plan = build_publication_plan(_request(tmp_path), executor=executor)
    executor.phase = "committed"
    executor.remote_head = COMMIT_SHA
    executor.prs = [executor._exact_pr(state=state, merged=merged)]
    executor.calls.clear()

    with pytest.raises(PublicationRefusal, match="closed or merged") as raised:
        apply_publication_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=executor)

    assert raised.value.outcome == "terminal"
    assert not any(
        _is_gh_api_call(call, "POST")
        or call[:2] == ("git", "push")
        or call[:3] == ("gh", "pr", "create")
        for call in executor.calls
    )


def test_publication_refuses_duplicate_all_state_pr_history(tmp_path: Path) -> None:
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    plan = build_publication_plan(_request(tmp_path), executor=executor)
    executor.phase = "committed"
    executor.remote_head = COMMIT_SHA
    executor.prs = [executor._exact_pr(), executor._exact_pr(state="closed")]
    executor.calls.clear()

    with pytest.raises(PublicationRefusal, match="not uniquely reconcilable") as raised:
        apply_publication_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=executor)

    assert raised.value.outcome == "unknown"
    assert not any(call[:3] == ("gh", "pr", "create") for call in executor.calls)


@pytest.mark.parametrize(
    ("failure_key", "exit_code"),
    [
        ("pr-body", 11),
        ("workspace", 12),
        ("stage", 13),
        ("commit", 14),
        ("review", 15),
        ("workspace-prepush", 18),
    ],
)
def test_publication_cli_propagates_gate_failures_without_masking(
    tmp_path: Path, failure_key: str, exit_code: int
) -> None:
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    plan = build_publication_plan(_request(tmp_path), executor=executor)
    executor.failures[failure_key] = exit_code
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(canonical_json(plan), encoding="utf-8")

    result = publication_main(
        [
            "apply",
            "--plan-file",
            str(plan_file),
            "--expected-plan-sha256",
            plan["plan_sha256"],
        ],
        executor=executor,
    )

    assert result == exit_code


@pytest.mark.parametrize(
    ("failure_key", "expected_exit"),
    [("reserve", 21), ("push", 21), ("pr-create", 4)],
)
def test_publication_cli_types_external_effect_failures_from_exact_readback(
    tmp_path: Path, failure_key: str, expected_exit: int
) -> None:
    (tmp_path / "feature.txt").write_text("new\n", encoding="utf-8")
    executor = FakeExecutor(tmp_path)
    plan = build_publication_plan(_request(tmp_path), executor=executor)
    executor.failures[failure_key] = 21
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(canonical_json(plan), encoding="utf-8")

    result = publication_main(
        [
            "apply",
            "--plan-file",
            str(plan_file),
            "--expected-plan-sha256",
            plan["plan_sha256"],
        ],
        executor=executor,
    )

    assert result == expected_exit
