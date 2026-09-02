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
        self.inputs: list[str | None] = []
        self.body = "Governing-Issue: #5245\n\nFixes #5245\n\nFinal-Review-Rounds: 0\n"
        self.issue_title = "builder: make light-path closure deterministic with plan/apply"
        self.issue_body = "Issue body"
        self.events_commit_id = MERGE
        self.timeline: list[object] = []
        self.required_checks: object = {
            "required_status_checks": {
                "contexts": [],
                "checks": [{"context": "CI", "app_id": 7}],
            }
        }
        self.dispatcher_status = "claimed"
        self.dispatcher_task = {
            "task_id": "github-RasmusTho--agentic-pkm-mvp-issue-5245",
            "claimed_by": "codex-slice-implementer",
            "lease_id": "lease-1",
            "linked_pr": "99",
        }

    def run(self, argv: Sequence[str], *, cwd: Path, input_text: str | None = None) -> CommandResult:
        del cwd
        args = tuple(argv); self.calls.append(args); self.inputs.append(input_text)
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
            return self._json(args, {"number": 5245, "state": "closed" if self.merged else "open", "title": self.issue_title, "body": self.issue_body, "labels": [{"name": "agent:in-progress"}, {"name": "lane:governance"}]})
        if endpoint.endswith("/issues/5245/events") and "GET" in args:
            return self._json(args, [{"event": "closed", "commit_id": self.events_commit_id}])
        if endpoint.endswith("/issues/5245/timeline") and "GET" in args:
            return self._json(args, self.timeline)
        if endpoint.endswith("/branches/main/protection") and "GET" in args:
            return self._json(args, self.required_checks)
        if endpoint.endswith("check-runs"):
            return self._json(args, {"check_runs": [{"id": 1, "name": "CI", "status": "completed", "conclusion": "success", "app": {"id": 7}}]})
        if endpoint.endswith("/status"):
            return self._json(args, {"statuses": []})
        if endpoint.endswith("/pulls/99/merge") and "PUT" in args:
            if self.fail_merge: return CommandResult(args, 1, "", "transport")
            self.merged = True; return self._json(args, {"sha": MERGE, "merged": True})
        if endpoint.endswith("/issues/5245") and "PATCH" in args:
            assert args[-2:] == ("--input", "-")
            return self._json(args, {})
        if len(args) >= 3 and args[1:3] == ("-m", "app.dispatcher"):
            if args[3] == "show":
                task = {"task_id": self.dispatcher_task["task_id"], "status": self.dispatcher_status, "linked_pr": "99"}
                if self.dispatcher_status == "claimed":
                    task.update(self.dispatcher_task)
                return self._json(args, {"ok": True, "task": task})
            if args[3] == "events":
                return self._json(args, {"ok": True, "events": [{"task_id": self.dispatcher_task["task_id"], "event_type": "task.completed", "actor": self.dispatcher_task["claimed_by"], "lease_id": self.dispatcher_task["lease_id"]}]})
            if args[3] == "complete":
                assert args[4] == self.dispatcher_task["task_id"]
                assert args[5:7] == ("--agent", self.dispatcher_task["claimed_by"])
                self.dispatcher_status = "completed"; return CommandResult(args, 0, "", "")
        raise AssertionError(args)

    @staticmethod
    def _json(argv: tuple[str, ...], value: object) -> CommandResult:
        return CommandResult(argv, 0, json.dumps(value), "")


def request(tmp_path: Path, task_id: str | None = None) -> ClosureRequest:
    return ClosureRequest(REPO, tmp_path, 99, {"head_sha": HEAD, "verified": True}, task_id)


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
    patch_call = next(call for call in fake.calls if "PATCH" in call)
    patch_input = fake.inputs[fake.calls.index(patch_call)]
    assert json.loads(patch_input or "") == {"labels": ["lane:governance"]}


@pytest.mark.parametrize("field", ["issue_title", "issue_body"])
def test_closure_apply_rejects_post_merge_closing_issue_title_or_body_drift(tmp_path: Path, field: str) -> None:
    fake = Fake(tmp_path); plan = build_closure_plan(request(tmp_path), executor=fake)
    fake.merged = True
    setattr(fake, field, getattr(fake, field) + " changed")
    with pytest.raises(ClosureError, match="post-merge closing Issue title/body drifted"):
        apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert not any("/events" in call[6] for call in fake.calls if call[:2] == ("gh", "api"))


def test_closure_apply_accepts_valid_event_without_optional_issue_number(tmp_path: Path) -> None:
    fake = Fake(tmp_path); plan = build_closure_plan(request(tmp_path), executor=fake)
    receipt = apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert receipt["issue"]["closure_attribution"] == "GitHub-native closing keyword and exact merge event"


def test_closure_apply_completes_exact_dispatcher_task_with_lease_holder(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    task_id = fake.dispatcher_task["task_id"]
    plan = build_closure_plan(request(tmp_path, task_id), executor=fake)
    receipt = apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert receipt["cleanup"]["dispatcher"]["lease_holder"] == "codex-slice-implementer"
    complete = next(call for call in fake.calls if len(call) >= 4 and call[3] == "complete")
    assert complete[4:7] == (task_id, "--agent", "codex-slice-implementer")


def test_closure_plan_binds_repository_required_check_authority(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    plan = build_closure_plan(request(tmp_path), executor=fake)
    assert plan["required_checks"] == [{"kind": "check", "name": "CI", "app_id": 7}]
    fake.required_checks = {}
    with pytest.raises(ClosureError, match="required-check authority"):
        build_closure_plan(request(tmp_path), executor=fake)


def test_closure_apply_recovers_completed_dispatcher_from_governed_completion_event(tmp_path: Path) -> None:
    fake = Fake(tmp_path); task_id = fake.dispatcher_task["task_id"]
    plan = build_closure_plan(request(tmp_path, task_id), executor=fake)
    fake.merged = True; fake.dispatcher_status = "completed"
    receipt = apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert receipt["reconciled"] is True
    assert not any(len(call) >= 4 and call[3] == "complete" for call in fake.calls)


def test_closure_apply_requires_pr_specific_attribution_when_closed_event_has_no_commit(tmp_path: Path) -> None:
    fake = Fake(tmp_path); fake.events_commit_id = None
    plan = build_closure_plan(request(tmp_path), executor=fake)
    with pytest.raises(ClosureError, match="attribution"):
        apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    fake = Fake(tmp_path); fake.events_commit_id = None
    fake.timeline = [{"event": "cross-referenced", "source": {"issue": {"number": 99, "pull_request": {"url": "https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/pulls/99"}}}}]
    plan = build_closure_plan(request(tmp_path), executor=fake)
    receipt = apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert receipt["issue"]["closure_attribution"] == "GitHub-native exact PR closer attribution"


def test_closure_apply_requires_exact_closing_issue_attribution(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.events_commit_id = "c" * 40
    plan = build_closure_plan(request(tmp_path), executor=fake)
    with pytest.raises(ClosureError, match="attribution"):
        apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert not any("PATCH" in call for call in fake.calls)


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
