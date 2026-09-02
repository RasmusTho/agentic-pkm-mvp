from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Sequence

import pytest

from app.builderops.closure import (
    ClosureError,
    ClosureRequest,
    _acceptance_criteria,
    apply_closure_plan,
    build_closure_plan,
    closure_plan_hash,
)
from app.builderops.publication import CommandResult
from scripts.closure import main

REPO = "RasmusTho/agentic-pkm-mvp"
HEAD = "a" * 40
MERGE = "b" * 40
PR_UPDATED = "2026-09-02T00:00:00Z"
CHECK_STARTED = "2026-09-02T00:00:01Z"
ISSUE_BODY = (
    "## Acceptance Criteria\n"
    "- [ ] Closure contract is verified. Verify: tests/scripts/test_closure.py::test_closure_plan_is_canonical_hash_bound_read_only_and_strictly_light_path\n"
)


class Fake:
    def __init__(self, worktree: Path) -> None:
        self.worktree = worktree
        self.merged = False
        self.fail_merge = False
        self.calls: list[tuple[str, ...]] = []
        self.inputs: list[str | None] = []
        self.body = "Governing-Issue: #5245\n\nFixes #5245\n\nFinal-Review-Rounds: 0\n"
        self.issue_title = "builder: make light-path closure deterministic with plan/apply"
        self.issue_body = ISSUE_BODY
        self.labels = ["agent:in-progress", "action:repair-contract", "lane:governance"]
        self.events_commit_id = MERGE
        self.close_created_at = "2026-09-02T00:00:10Z"
        self.close_actor = "github-actions"
        self.cleanup_issue_state_open = False
        self.reopen_during_cleanup = False
        self.closed_evidence: list[dict[str, object]] = [
            {
                "createdAt": self.close_created_at,
                "actor": {"login": self.close_actor},
                "closer": {
                    "__typename": "PullRequest",
                    "number": 99,
                    "mergedAt": "2026-09-02T00:00:09Z",
                    "mergeCommit": {"oid": MERGE},
                    "repository": {"nameWithOwner": REPO},
                },
            }
        ]
        self.timeline: list[object] = []
        self.closing_references = [5245]
        self.add_label_during_cleanup = False
        self.required_checks: object = {
            "required_status_checks": {
                "contexts": [],
                "checks": [{"context": "CI", "app_id": 7}],
            }
        }
        self.dispatcher_status = "claimed"
        self.dispatcher_task = {
            "task_id": "github-RasmusTho--agentic-pkm-mvp-issue-5245",
            "issue_number": 5245,
            "repo": REPO,
            "claimed_by": "codex-slice-implementer",
            "lease_id": "lease-1",
            "linked_pr": "99",
        }
        self.check_runs: list[dict[str, object]] = [
            {"id": 1, "name": "CI", "status": "completed", "conclusion": "success", "app": {"id": 7}, "head_sha": HEAD, "started_at": CHECK_STARTED},
            {"id": 2, "name": "pr-contract", "status": "completed", "conclusion": "success", "app": {"id": 8}, "head_sha": HEAD, "started_at": CHECK_STARTED},
        ]

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
                    "updated_at": PR_UPDATED,
                    "base": {"ref": "main", "sha": "c" * 40, "repo": {"full_name": REPO}},
                    "head": {"sha": HEAD, "repo": {"full_name": REPO}},
                },
            )
        if endpoint.endswith("/issues/5245") and "GET" in args:
            return self._json(args, {"number": 5245, "state": "open" if not self.merged or self.cleanup_issue_state_open else "closed", "title": self.issue_title, "body": self.issue_body, "updated_at": PR_UPDATED, "labels": [{"name": label} for label in self.labels]})
        if endpoint.endswith("/issues/5245/events") and "GET" in args:
            return self._json(args, [{"event": "closed", "commit_id": self.events_commit_id, "created_at": self.close_created_at, "actor": {"login": self.close_actor}}])
        if endpoint.endswith("/issues/5245/timeline") and "GET" in args:
            return self._json(args, self.timeline)
        if endpoint.endswith("/branches/main/protection") and "GET" in args:
            return self._json(args, self.required_checks)
        if "graphql" in args:
            if any("timelineItems" in part for part in args):
                return self._json(args, {"data": {"repository": {"issue": {"state": "CLOSED", "closedAt": self.close_created_at, "timelineItems": {"nodes": self.closed_evidence}}}}})
            return self._json(args, {"data": {"repository": {"pullRequest": {"closingIssuesReferences": {"nodes": [{"number": number, "repository": {"nameWithOwner": REPO}} for number in self.closing_references], "pageInfo": {"hasNextPage": False}}}}}})
        if endpoint.endswith("check-runs"):
            return self._json(args, {"check_runs": self.check_runs})
        if endpoint.endswith("/status"):
            return self._json(args, {"statuses": []})
        if endpoint.endswith("/pulls/99/merge") and "PUT" in args:
            if self.fail_merge: return CommandResult(args, 1, "", "transport")
            self.merged = True; return self._json(args, {"sha": MERGE, "merged": True})
        if "/issues/5245/labels/" in endpoint and "DELETE" in args:
            label = endpoint.rsplit("/", 1)[-1].replace("%3A", ":")
            if label in self.labels:
                self.labels.remove(label)
            if self.reopen_during_cleanup:
                self.cleanup_issue_state_open = True
            if self.add_label_during_cleanup and "prio:high" not in self.labels:
                self.labels.append("prio:high")
            return self._json(args, {})
        if len(args) >= 3 and args[1:3] == ("-m", "app.dispatcher"):
            if args[3] == "show":
                task = {"task_id": self.dispatcher_task["task_id"], "status": self.dispatcher_status, "issue_number": 5245, "repo": REPO, "linked_pr": "99"}
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
    issue_hashes = {
        "title_sha256": hashlib.sha256("builder: make light-path closure deterministic with plan/apply".encode()).hexdigest(),
        "body_sha256": hashlib.sha256(ISSUE_BODY.encode()).hexdigest(),
    }
    criteria = _acceptance_criteria(ISSUE_BODY)
    evidence = {
        "schema": "builder.closure-verify-evidence.v1",
        "verified": True,
        "head_sha": HEAD,
        "tier": 2,
        "final_review_rounds": 0,
        "tcd": {"risk_surfaces": [], "risk_assessment_complete": True, "stateful_fallback": False},
        "scope": {"repository": REPO, "pr_number": 99, "base_ref": "main", "base_sha": "c" * 40, "head_sha": HEAD, "governing_issue": 5245, "closing_issues": [5245]},
        "pr": {"number": 99, "title_sha256": hashlib.sha256("closure".encode()).hexdigest(), "body_sha256": hashlib.sha256("Governing-Issue: #5245\n\nFixes #5245\n\nFinal-Review-Rounds: 0\n".encode()).hexdigest(), "updated_at": PR_UPDATED},
        "issue": {"number": 5245, **issue_hashes, "updated_at": PR_UPDATED},
        "acceptance_criteria": [{**item, "verified": True, "evidence_sha256": "a" * 64} for item in criteria],
    }
    return ClosureRequest(REPO, tmp_path, 99, evidence, task_id)


def test_closure_plan_is_canonical_hash_bound_read_only_and_strictly_light_path(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    first = build_closure_plan(request(tmp_path), executor=fake)
    second = build_closure_plan(request(tmp_path), executor=fake)
    assert first == second and first["schema"] == "builder.closure-plan.v1"
    assert first["plan_sha256"] == closure_plan_hash(first)
    assert all("GET" in call or "graphql" in call for call in fake.calls if call[:2] == ("gh", "api"))
    fake.body = "Governing-Issue: #5245\nFixes #5245\nFinal-Review-Rounds: 1"
    with pytest.raises(ClosureError, match="Final-Review-Rounds"):
        build_closure_plan(request(tmp_path), executor=fake)


def test_closure_apply_revalidates_all_authority_before_exact_head_merge(tmp_path: Path) -> None:
    fake = Fake(tmp_path); plan = build_closure_plan(request(tmp_path), executor=fake)
    fake.body += "changed"
    with pytest.raises(ClosureError, match="authority drift|Verify evidence"):
        apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert not any(call[-1].endswith("/merge") for call in fake.calls if call[:2] == ("gh", "api"))


def test_closure_apply_reads_back_merge_closure_and_bounded_cleanup(tmp_path: Path) -> None:
    fake = Fake(tmp_path); plan = build_closure_plan(request(tmp_path), executor=fake)
    receipt = apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert receipt["merge_sha"] == MERGE and receipt["issue"]["state"] == "closed"
    assert receipt["remaining_action"] == "post-merge-owner-doc"
    assert any(any(part.endswith("/merge") for part in call) and "PUT" in call for call in fake.calls)
    assert any("DELETE" in call and any("/labels/agent%3Ain-progress" in part for part in call) for call in fake.calls)
    assert not any("PATCH" in call for call in fake.calls)


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


def test_closure_plan_preserves_name_bound_required_check_authority(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.required_checks = {"required_status_checks": {"contexts": [], "checks": [{"context": "CI", "app_id": None}]}}
    plan = build_closure_plan(request(tmp_path), executor=fake)
    assert plan["required_checks"] == [{"kind": "check", "name": "CI", "app_id": None}]


def test_closure_plan_unions_duplicate_required_check_context_and_check_by_name(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.required_checks = {
        "required_status_checks": {
            "contexts": ["CI", "CI"],
            "checks": [{"context": "CI", "app_id": 7}],
        }
    }
    plan = build_closure_plan(request(tmp_path), executor=fake)
    assert plan["required_checks"] == [{"kind": "check", "name": "CI", "app_id": 7}]


def test_closure_plan_rejects_conflicting_duplicate_required_check_identities(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.required_checks = {
        "required_status_checks": {
            "contexts": ["CI"],
            "checks": [{"context": "CI", "app_id": 7}, {"context": "CI", "app_id": 8}],
        }
    }
    with pytest.raises(ClosureError, match="required-check authority is ambiguous"):
        build_closure_plan(request(tmp_path), executor=fake)


def test_closure_apply_recovers_completed_dispatcher_from_governed_completion_event(tmp_path: Path) -> None:
    fake = Fake(tmp_path); task_id = fake.dispatcher_task["task_id"]
    plan = build_closure_plan(request(tmp_path, task_id), executor=fake)
    fake.merged = True; fake.dispatcher_status = "completed"
    receipt = apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert receipt["reconciled"] is True
    assert not any(len(call) >= 4 and call[3] == "complete" for call in fake.calls)


def test_closure_plan_requires_dispatcher_repository_and_issue_binding(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.dispatcher_task["repo"] = "other/repository"
    with pytest.raises(ClosureError, match="governing repository and Issue"):
        build_closure_plan(request(tmp_path, fake.dispatcher_task["task_id"]), executor=fake)


def test_closure_apply_requires_pr_specific_attribution_when_closed_event_has_no_commit(tmp_path: Path) -> None:
    fake = Fake(tmp_path); fake.events_commit_id = None; fake.closed_evidence = []
    plan = build_closure_plan(request(tmp_path), executor=fake)
    with pytest.raises(ClosureError, match="attribution|closed-event evidence"):
        apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    fake = Fake(tmp_path); fake.events_commit_id = None; fake.closed_evidence = []
    fake.timeline = [{"event": "cross-referenced", "source": {"issue": {"number": 99, "pull_request": {"url": "https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/pulls/99"}}}}]
    plan = build_closure_plan(request(tmp_path), executor=fake)
    with pytest.raises(ClosureError, match="attribution|closed-event evidence"):
        apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    fake.closed_evidence = [
        {
            "createdAt": fake.close_created_at,
            "actor": {"login": fake.close_actor},
            "closer": {
                "__typename": "PullRequest",
                "number": 99,
                "mergedAt": "2026-09-02T00:00:09Z",
                "mergeCommit": {"oid": MERGE},
                "repository": {"nameWithOwner": REPO},
            },
        }
    ]
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


def test_closure_plan_rejects_unbound_caller_verified_evidence(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    with pytest.raises(ClosureError, match="schema"):
        build_closure_plan(
            ClosureRequest(REPO, tmp_path, 99, {"head_sha": HEAD, "verified": True}),
            executor=fake,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tier", 1),
        ("final_review_rounds", 1),
        ("tcd", {"risk_surfaces": ["api"], "risk_assessment_complete": True, "stateful_fallback": False}),
        ("scope", {"repository": REPO, "pr_number": 98, "base_ref": "main", "base_sha": "c" * 40, "head_sha": HEAD, "governing_issue": 5245, "closing_issues": [5245]}),
    ],
)
def test_closure_plan_authenticates_light_path_tcd_and_scope(
    tmp_path: Path, field: str, value: object
) -> None:
    fake = Fake(tmp_path)
    evidence = dict(request(tmp_path).verify_evidence)
    evidence[field] = value
    with pytest.raises(ClosureError, match="light path|TCD|scope"):
        build_closure_plan(ClosureRequest(REPO, tmp_path, 99, evidence), executor=fake)


def test_closure_plan_binds_each_acceptance_criterion_to_issue_revision(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    evidence = dict(request(tmp_path).verify_evidence)
    evidence["issue"] = dict(evidence["issue"])
    evidence["issue"]["body_sha256"] = "f" * 64
    with pytest.raises(ClosureError, match="governing Issue revision"):
        build_closure_plan(ClosureRequest(REPO, tmp_path, 99, evidence), executor=fake)

    evidence = dict(request(tmp_path).verify_evidence)
    evidence["acceptance_criteria"] = []
    with pytest.raises(ClosureError, match="every Acceptance Criterion"):
        build_closure_plan(ClosureRequest(REPO, tmp_path, 99, evidence), executor=fake)


def test_closure_plan_reconciles_failed_same_head_check_with_later_success(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.check_runs = [
        {"id": 1, "name": "CI", "status": "completed", "conclusion": "success", "app": {"id": 7}, "head_sha": HEAD, "started_at": "2026-09-02T00:00:01Z"},
        {"id": 3, "name": "CI", "status": "completed", "conclusion": "failure", "app": {"id": 7}, "head_sha": HEAD, "started_at": "2026-09-02T00:00:02Z"},
        {"id": 4, "name": "CI", "status": "completed", "conclusion": "success", "app": {"id": 7}, "head_sha": HEAD, "started_at": "2026-09-02T00:00:03Z"},
        {"id": 2, "name": "pr-contract", "status": "completed", "conclusion": "success", "app": {"id": 8}, "head_sha": HEAD, "started_at": CHECK_STARTED},
    ]
    plan = build_closure_plan(request(tmp_path), executor=fake)
    assert {item["id"] for item in plan["checks"]} == {2, 4}


def test_closure_plan_rejects_unorderable_same_head_check_history(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.check_runs = [
        {"id": 3, "name": "CI", "status": "completed", "conclusion": "failure", "app": {"id": 7}, "head_sha": HEAD},
        {"id": 4, "name": "CI", "status": "completed", "conclusion": "success", "app": {"id": 7}, "head_sha": HEAD},
        fake.check_runs[1],
    ]
    with pytest.raises(ClosureError, match="ordering evidence"):
        build_closure_plan(request(tmp_path), executor=fake)


def test_closure_plan_requires_pr_contract_after_current_body_revision(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.check_runs[1]["started_at"] = PR_UPDATED
    with pytest.raises(ClosureError, match="predates"):
        build_closure_plan(request(tmp_path), executor=fake)


def test_closure_plan_rejects_additional_github_closing_keyword_forms(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.body = fake.body.replace("Final-Review-Rounds: 0\n", "Closes RasmusTho/agentic-pkm-mvp#4999\nFinal-Review-Rounds: 0\n")
    with pytest.raises(ClosureError, match="governing and closing Issue"):
        build_closure_plan(request(tmp_path), executor=fake)

    fake = Fake(tmp_path)
    fake.closing_references = [5245, 4999]
    with pytest.raises(ClosureError, match="GitHub closing references"):
        build_closure_plan(request(tmp_path), executor=fake)

    fake = Fake(tmp_path)
    fake.body = fake.body.replace("Fixes #5245", "Fixed: #5245")
    evidence = dict(request(tmp_path).verify_evidence)
    evidence["pr"] = dict(evidence["pr"])
    evidence["pr"]["body_sha256"] = hashlib.sha256(fake.body.encode()).hexdigest()
    assert build_closure_plan(ClosureRequest(REPO, tmp_path, 99, evidence), executor=fake)["governing_issue"] == 5245


def test_closure_cleanup_deletes_only_observed_agent_labels(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.add_label_during_cleanup = True
    plan = build_closure_plan(request(tmp_path), executor=fake)
    receipt = apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert receipt["cleanup"]["removed_agent_labels"] == ["agent:in-progress"]
    assert receipt["cleanup"]["removed_action_labels"] == ["action:repair-contract"]
    assert "lane:governance" in receipt["cleanup"]["remaining_labels"]
    assert "prio:high" in receipt["cleanup"]["remaining_labels"]
    assert not any(
        label.startswith(("agent:", "action:"))
        for label in receipt["cleanup"]["remaining_labels"]
    )
    assert receipt["issue"]["state"] == "closed"


def test_closure_cleanup_requires_closed_issue_readback(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    plan = build_closure_plan(request(tmp_path), executor=fake)
    fake.reopen_during_cleanup = True
    with pytest.raises(ClosureError, match="does not prove closed state"):
        apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)


def test_closure_reconciliation_rechecks_pr_body_authority(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    plan = build_closure_plan(request(tmp_path), executor=fake)
    fake.merged = True
    fake.body = fake.body.replace("Fixes #5245", "Fixes #4999")
    with pytest.raises(ClosureError, match="PR body/head authority|closing Issue authority"):
        apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
