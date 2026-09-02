from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import pytest

from app.builderops.closure import (
    ClosureError,
    ClosureRequest,
    apply_closure_plan,
    build_closure_plan,
    closure_plan_hash,
)
from app.builderops.publication import CommandResult
from scripts.closure import main

REPO = "RasmusTho/agentic-pkm-mvp"
HEAD = "a" * 40
MERGE = "b" * 40


class Fake:
    def __init__(self, worktree: Path) -> None:
        self.worktree = worktree
        self.merged = False
        self.fail_merge = False
        self.calls: list[tuple[str, ...]] = []
        self.body = "Governing-Issue: #5245\n\nFixes #5245\n\nFinal-Review-Rounds: 0\n"

    def run(self, argv: Sequence[str], *, cwd: Path, input_text: str | None = None) -> CommandResult:
        del cwd, input_text
        args = tuple(argv); self.calls.append(args)
        endpoint = args[6] if args[:2] == ("gh", "api") else ""
        if endpoint.endswith("/pulls/99") and "GET" in args:
            return self._json(
                args,
                {
                    "number": 99,
                    "state": "closed" if self.merged else "open",
                    "merged_at": "now" if self.merged else None,
                    "merge_commit_sha": MERGE if self.merged else None,
                    "title": "closure",
                    "body": self.body,
                    "base": {"ref": "main", "sha": "c" * 40, "repo": {"full_name": REPO}},
                    "head": {"sha": HEAD, "repo": {"full_name": REPO}},
                },
            )
        if endpoint.endswith("/issues/5245") and "GET" in args:
            return self._json(args, {"number": 5245, "state": "closed" if self.merged else "open", "labels": [{"name": "agent:in-progress"}, {"name": "lane:governance"}]})
        if endpoint.endswith("check-runs"):
            return self._json(args, {"check_runs": [{"name": "CI", "status": "completed", "conclusion": "success"}]})
        if endpoint.endswith("/pulls/99/merge") and "PUT" in args:
            if self.fail_merge: return CommandResult(args, 1, "", "transport")
            self.merged = True; return self._json(args, {"sha": MERGE, "merged": True})
        if endpoint.endswith("/issues/5245") and "PATCH" in args: return self._json(args, {})
        if args[:3] == ("/usr/bin/python3", "-m", "app.dispatcher") or args[:3] == ("python3", "-m", "app.dispatcher"):
            return CommandResult(args, 0, "", "")
        raise AssertionError(args)

    @staticmethod
    def _json(argv: tuple[str, ...], value: object) -> CommandResult:
        return CommandResult(argv, 0, json.dumps(value), "")


def request(tmp_path: Path) -> ClosureRequest:
    return ClosureRequest(REPO, tmp_path, 99, {"head_sha": HEAD, "verified": True})


def test_closure_plan_is_canonical_hash_bound_read_only_and_strictly_light_path(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    first = build_closure_plan(request(tmp_path), executor=fake)
    second = build_closure_plan(request(tmp_path), executor=fake)
    assert first == second and first["schema"] == "builder.closure-plan.v1"
    assert first["plan_sha256"] == closure_plan_hash(first)
    assert all("GET" in call for call in fake.calls if call[:2] == ("gh", "api"))
    fake.body = "Governing-Issue: #5245\nFixes #5245\nFinal-Review-Rounds: 1"
    with pytest.raises(ClosureError, match="Final-Review-Rounds"):
        build_closure_plan(request(tmp_path), executor=fake)


def test_closure_apply_revalidates_all_authority_before_exact_head_merge(tmp_path: Path) -> None:
    fake = Fake(tmp_path); plan = build_closure_plan(request(tmp_path), executor=fake)
    fake.body += "changed"
    with pytest.raises(ClosureError, match="authority drift"):
        apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert not any(call[-1].endswith("/merge") for call in fake.calls if call[:2] == ("gh", "api"))


def test_closure_apply_reads_back_merge_closure_and_bounded_cleanup(tmp_path: Path) -> None:
    fake = Fake(tmp_path); plan = build_closure_plan(request(tmp_path), executor=fake)
    receipt = apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert receipt["merge_sha"] == MERGE and receipt["issue"]["state"] == "closed"
    assert receipt["remaining_action"] == "post-merge-owner-doc"
    assert any(any(part.endswith("/merge") for part in call) and "PUT" in call for call in fake.calls)


def test_closure_apply_reconciles_repeats_partial_results_and_ambiguity_without_retry(tmp_path: Path) -> None:
    fake = Fake(tmp_path); plan = build_closure_plan(request(tmp_path), executor=fake); fake.fail_merge = True
    with pytest.raises(ClosureError) as raised:
        apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert raised.value.outcome == "unknown"
    assert sum(any(part.endswith("/merge") for part in call) for call in fake.calls if call[:2] == ("gh", "api")) == 1


def test_closure_cli_propagates_gate_failures_without_masking(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake = Fake(tmp_path); plan = build_closure_plan(request(tmp_path), executor=fake); path = tmp_path / "plan.json"; path.write_text(json.dumps(plan))
    fake.fail_merge = True
    assert main(["apply", "--plan-file", str(path), "--expected-plan-sha256", plan["plan_sha256"]], executor=fake) == 1
    assert '"outcome":"unknown"' in capsys.readouterr().err
