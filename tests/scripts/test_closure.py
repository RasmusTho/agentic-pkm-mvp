from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import pytest

import app.builderops.closure as closure
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
        target_file = worktree / "tests/scripts/test_closure.py"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text("# fixture for Verify target resolution\n", encoding="utf-8")
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
        self.previous_null_close = False
        self.stale_merge_close = False
        self.event_pages: list[list[dict[str, object]]] | None = None
        self.coordination_comment = {
            "id": 700,
            "issue_url": f"https://api.github.com/repos/{REPO}/issues/5245",
            "body": "Pickup intent receipt: agent=codex-slice-implementer session=session-5245 branch=codex/issue-5245-light-closure worktree="
            f"{worktree} coordination_mode=github-label-only-fallback fallback_reason=dispatcher_db_missing issue=5245",
            "user": {"login": "RasmusTho"},
            "created_at": "2026-09-02T00:00:00Z",
        }
        self.pickup_comments = [self.coordination_comment]
        self.closed_evidence: list[dict[str, object]] = [
            {
                "__typename": "ClosedEvent",
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
        self.dispatcher_status = "absent"
        self.claim_dispatcher_during_pr_readback = False
        self.release_dispatcher_lease_during_pr_readback = False
        self.claim_dispatcher_after_merge = False
        self.claim_dispatcher_during_label_cleanup = False
        self.cleanup_guard_active = False
        self.cleanup_guard_claim_blocked = False
        self.cleanup_guard_token = "guard-token"
        self.dispatcher_lease_released_at: str | None = None
        self.dispatcher_release_events: list[dict[str, object]] = []
        self.dispatcher_claim_events: list[dict[str, object]] = [
            {
                "task_id": "github-RasmusTho--agentic-pkm-mvp-issue-5245",
                "event_type": "task.claimed",
                "actor": "codex-slice-implementer",
                "lease_id": "lease-1",
            }
        ]
        self.recovery_claim_events_after: list[dict[str, object]] = []
        self.dispatcher_task = {
            "task_id": "github-RasmusTho--agentic-pkm-mvp-issue-5245",
            "issue_number": 5245,
            "repo": REPO,
            "claimed_by": "codex-slice-implementer",
            "lease_id": "lease-1",
            "lease_expires_at": "2099-01-01T00:00:00+00:00",
            "linked_pr": "99",
        }
        self.check_runs: list[dict[str, object]] = [
            {"id": 1, "name": "CI", "status": "completed", "conclusion": "success", "app": {"id": 7}, "head_sha": HEAD, "started_at": CHECK_STARTED},
            {"id": 2, "name": "pr-contract", "status": "completed", "conclusion": "success", "app": {"id": 8}, "head_sha": HEAD, "started_at": CHECK_STARTED},
        ]

    def run(self, argv: Sequence[str], *, cwd: Path, input_text: str | None = None) -> CommandResult:
        del cwd
        args = tuple(argv); self.calls.append(args); self.inputs.append(input_text)
        endpoint = next((part for part in args if part.startswith("repos/")), "") if args[:2] == ("gh", "api") else ""
        if endpoint.endswith("/pulls/99") and "GET" in args:
            result = self._json(
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
            if self.claim_dispatcher_during_pr_readback and not self.merged:
                self.dispatcher_status = "claimed"
            if self.release_dispatcher_lease_during_pr_readback and not self.merged:
                self.dispatcher_status = "claimed"
                self.dispatcher_lease_released_at = "2026-09-02T00:00:02+00:00"
            return result
        if endpoint.endswith("/issues/5245") and "GET" in args:
            if self.claim_dispatcher_after_merge and self.merged:
                self.dispatcher_status = "claimed"
                self.dispatcher_task.update(
                    {
                        "claimed_by": "other-agent",
                        "lease_id": "replacement-lease",
                        "lease_expires_at": "2099-01-03T00:00:00+00:00",
                    }
                )
            return self._json(args, {"number": 5245, "state": "open" if not self.merged or self.cleanup_issue_state_open else "closed", "title": self.issue_title, "body": self.issue_body, "updated_at": PR_UPDATED, "labels": [{"name": label} for label in self.labels]})
        if endpoint.startswith(f"repos/{REPO}/issues/5245/comments") and "GET" in args:
            return self._json(args, [self.pickup_comments])
        if endpoint.endswith("/issues/5245/events") and "GET" in args:
            current = {"event": "closed", "commit_id": self.events_commit_id, "created_at": self.close_created_at, "actor": {"login": self.close_actor}}
            previous = {"event": "closed", "commit_id": None, "created_at": "2026-09-01T00:00:10Z", "actor": {"login": self.close_actor}}
            if self.stale_merge_close:
                stale_merge = {"event": "closed", "commit_id": MERGE, "created_at": "2026-09-01T00:00:10Z", "actor": {"login": "github-actions"}}
                current = {"event": "closed", "commit_id": None, "created_at": self.close_created_at, "actor": {"login": self.close_actor}}
                events = [stale_merge, current]
            else:
                events = [previous, current] if self.previous_null_close else [current]
            return self._json(args, self.event_pages if self.event_pages is not None else [events])
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
            if self.claim_dispatcher_during_label_cleanup:
                if self.cleanup_guard_active:
                    self.cleanup_guard_claim_blocked = True
                else:
                    self.dispatcher_status = "claimed"
                    self.dispatcher_task.update(
                        {
                            "claimed_by": "other-agent",
                            "lease_id": "replacement-lease",
                            "lease_expires_at": "2099-01-03T00:00:00+00:00",
                        }
                    )
            label = endpoint.rsplit("/", 1)[-1].replace("%3A", ":")
            if label in self.labels:
                self.labels.remove(label)
            if self.reopen_during_cleanup:
                self.cleanup_issue_state_open = True
            if self.add_label_during_cleanup and "prio:high" not in self.labels:
                self.labels.append("prio:high")
            return self._json(args, {})
        if len(args) >= 3 and args[1:3] == ("-m", "app.dispatcher"):
            if args[3] == "cleanup-guard":
                assert args[5:7] == ("--task-id", self.dispatcher_task["task_id"])
                if args[4] == "acquire":
                    self.cleanup_guard_active = True
                    return self._json(
                        args,
                        {
                            "ok": True,
                            "guard": {
                                "task_id": self.dispatcher_task["task_id"],
                                "owner": args[8],
                                "token": self.cleanup_guard_token,
                                "expires_at": "2099-01-04T00:00:00+00:00",
                            },
                        },
                    )
                assert args[4] == "release"
                assert self.cleanup_guard_active is True
                assert args[7] == "--owner"
                assert args[9] == "--token"
                assert args[10] == self.cleanup_guard_token
                self.cleanup_guard_active = False
                return self._json(args, {"ok": True, "released": True, "task_id": self.dispatcher_task["task_id"]})
            if args[3] == "show":
                if self.dispatcher_status == "absent":
                    return CommandResult(
                        args,
                        1,
                        json.dumps({"ok": False, "error": f"Task {self.dispatcher_task['task_id']} not found"}),
                        "",
                    )
                task = {"task_id": self.dispatcher_task["task_id"], "status": self.dispatcher_status, "issue_number": 5245, "repo": REPO, "linked_pr": "99"}
                if self.dispatcher_status == "claimed":
                    task.update(self.dispatcher_task)
                if "--events" in args:
                    if self.dispatcher_status == "ready":
                        events = self.dispatcher_release_events
                    elif self.dispatcher_status == "claimed":
                        events = self.dispatcher_claim_events
                    else:
                        events = [{"task_id": self.dispatcher_task["task_id"], "event_type": "task.completed", "actor": self.dispatcher_task["claimed_by"], "lease_id": self.dispatcher_task["lease_id"]}]
                    lease = None
                    if self.dispatcher_status == "claimed":
                        lease = {
                            "lease_id": self.dispatcher_task["lease_id"],
                            "holder": self.dispatcher_task["claimed_by"],
                            "resource": "issue:5245",
                            "expires_at": self.dispatcher_task["lease_expires_at"],
                            "released_at": self.dispatcher_lease_released_at,
                        }
                    return self._json(args, {"ok": True, "task": task, "lease": lease, "events": events})
                return self._json(args, {"ok": True, "task": task})
            if args[3] == "events":
                if self.dispatcher_status == "ready":
                    return self._json(args, {"ok": True, "events": self.dispatcher_release_events})
                return self._json(args, {"ok": True, "events": [{"task_id": self.dispatcher_task["task_id"], "event_type": "task.completed", "actor": self.dispatcher_task["claimed_by"], "lease_id": self.dispatcher_task["lease_id"]}]})
            if args[3] == "claim":
                assert args[4] == self.dispatcher_task["task_id"]
                assert args[5:7] == ("--agent", self.dispatcher_task["claimed_by"])
                self.dispatcher_status = "claimed"
                self.dispatcher_task.update({"lease_id": "lease-2", "lease_expires_at": "2099-01-02T00:00:00+00:00"})
                self.dispatcher_claim_events = [
                    *self.dispatcher_release_events,
                    {"task_id": self.dispatcher_task["task_id"], "event_type": "task.claimed", "actor": self.dispatcher_task["claimed_by"], "lease_id": "lease-2"},
                    *self.recovery_claim_events_after,
                ]
                task = {"task_id": self.dispatcher_task["task_id"], "status": "claimed", "issue_number": 5245, "repo": REPO, "linked_pr": "99", **self.dispatcher_task}
                lease = {"lease_id": "lease-2", "holder": self.dispatcher_task["claimed_by"], "resource": "issue:5245", "expires_at": "2099-01-02T00:00:00+00:00"}
                return self._json(args, {"ok": True, "task": task, "lease": lease})
            if args[3] == "complete":
                assert args[4] == self.dispatcher_task["task_id"]
                assert args[5:7] == ("--agent", self.dispatcher_task["claimed_by"])
                assert args[7:9] == ("--lease-id", self.dispatcher_task["lease_id"])
                self.dispatcher_status = "completed"; return CommandResult(args, 0, "", "")
        raise AssertionError(args)

    @staticmethod
    def _json(argv: tuple[str, ...], value: object) -> CommandResult:
        return CommandResult(argv, 0, json.dumps(value), "")


def request(tmp_path: Path, task_id: str | None = None) -> ClosureRequest:
    verify_fixture = tmp_path / "tests/scripts/test_closure.py"
    verify_fixture.parent.mkdir(parents=True, exist_ok=True)
    verify_fixture.touch()
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
    if task_id is None:
        return ClosureRequest(REPO, tmp_path, 99, evidence, None, "github-label-only-fallback", "dispatcher_db_missing", "github-comment:700", "codex-slice-implementer", "session-5245", "codex/issue-5245-light-closure")
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


def test_closure_plan_requires_explicit_coordination_when_dispatcher_task_is_omitted(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    evidence = request(tmp_path).verify_evidence
    with pytest.raises(ClosureError, match="explicit dispatcher or degraded coordination"):
        build_closure_plan(ClosureRequest(REPO, tmp_path, 99, evidence), executor=fake)


def test_closure_plan_rejects_expired_dispatcher_lease(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.dispatcher_status = "claimed"
    fake.dispatcher_task["lease_expires_at"] = "2000-01-01T00:00:00+00:00"
    with pytest.raises(ClosureError, match="dispatcher lease is expired"):
        build_closure_plan(request(tmp_path, fake.dispatcher_task["task_id"]), executor=fake)


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
    fake.dispatcher_status = "claimed"
    task_id = fake.dispatcher_task["task_id"]
    plan = build_closure_plan(request(tmp_path, task_id), executor=fake)
    receipt = apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert receipt["cleanup"]["dispatcher"]["lease_holder"] == "codex-slice-implementer"
    complete = next(call for call in fake.calls if len(call) >= 4 and call[3] == "complete")
    assert complete[4:7] == (task_id, "--agent", "codex-slice-implementer")


def test_closure_apply_recovers_planned_dispatcher_after_post_merge_lease_expiry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = Fake(tmp_path)
    fake.dispatcher_status = "claimed"
    fake.dispatcher_task["lease_expires_at"] = "2026-09-02T00:00:30+00:00"
    real_datetime = datetime

    class Clock(real_datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            del tz
            second = 40 if fake.merged else 20
            return real_datetime(2026, 9, 2, 0, 0, second, tzinfo=timezone.utc)

    monkeypatch.setattr(closure, "datetime", Clock)
    task_id = fake.dispatcher_task["task_id"]
    plan = build_closure_plan(request(tmp_path, task_id), executor=fake)
    receipt = apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert receipt["cleanup"]["dispatcher"]["status"] == "completed"


def test_closure_apply_recovers_gc_reclaimed_planned_lease_without_replacement_claimant(
    tmp_path: Path,
) -> None:
    fake = Fake(tmp_path)
    fake.dispatcher_status = "claimed"
    task_id = fake.dispatcher_task["task_id"]
    plan = build_closure_plan(request(tmp_path, task_id), executor=fake)
    fake.merged = True
    fake.dispatcher_status = "ready"
    fake.dispatcher_release_events = [
        {
            "task_id": task_id,
            "event_type": "task.released",
            "actor": "dispatcher-gc",
            "lease_id": "lease-1",
            "timestamp": "2099-01-01T00:00:01+00:00",
            "payload": {"reason": "expired"},
        }
    ]
    receipt = apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert receipt["cleanup"]["dispatcher"]["status"] == "completed"
    assert receipt["cleanup"]["dispatcher"]["lease_id"] == "lease-2"
    claim = next(call for call in fake.calls if len(call) >= 4 and call[3] == "claim")
    assert "--takeover-stale" not in claim
    complete = next(call for call in fake.calls if len(call) >= 4 and call[3] == "complete")
    assert complete[7:9] == ("--lease-id", "lease-2")


def test_closure_apply_rejects_recovered_dispatcher_after_claimant_history_race(
    tmp_path: Path,
) -> None:
    fake = Fake(tmp_path)
    fake.dispatcher_status = "claimed"
    task_id = fake.dispatcher_task["task_id"]
    plan = build_closure_plan(request(tmp_path, task_id), executor=fake)
    fake.merged = True
    fake.dispatcher_status = "ready"
    fake.dispatcher_release_events = [
        {
            "task_id": task_id,
            "event_type": "task.released",
            "actor": "dispatcher-gc",
            "lease_id": "lease-1",
            "timestamp": "2099-01-01T00:00:01+00:00",
            "payload": {"reason": "expired"},
        }
    ]
    fake.recovery_claim_events_after = [
        {
            "task_id": task_id,
            "event_type": "task.claimed",
            "actor": "other-agent",
            "lease_id": "lease-other",
        },
        {
            "task_id": task_id,
            "event_type": "task.released",
            "actor": "other-agent",
            "lease_id": "lease-other",
        },
    ]
    with pytest.raises(ClosureError, match="claimant history changed"):
        apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert not any(len(call) >= 4 and call[3] == "complete" for call in fake.calls)


def test_closure_apply_rejects_reclaimed_task_with_later_replacement_claimant(
    tmp_path: Path,
) -> None:
    fake = Fake(tmp_path)
    fake.dispatcher_status = "claimed"
    task_id = fake.dispatcher_task["task_id"]
    plan = build_closure_plan(request(tmp_path, task_id), executor=fake)
    fake.merged = True
    fake.dispatcher_status = "ready"
    fake.dispatcher_release_events = [
        {
            "task_id": task_id,
            "event_type": "task.released",
            "actor": "dispatcher-gc",
            "lease_id": "lease-1",
            "timestamp": "2099-01-01T00:00:01+00:00",
            "payload": {"reason": "expired"},
        },
        {
            "task_id": task_id,
            "event_type": "task.claimed",
            "actor": "other-agent",
            "lease_id": "lease-other",
            "timestamp": "2099-01-01T00:00:02+00:00",
        },
    ]
    with pytest.raises(ClosureError, match="claimed after the planned lease was reclaimed"):
        apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert not any(len(call) >= 4 and call[3] == "claim" for call in fake.calls)


def test_closure_plan_rejects_stale_fallback_claimant_receipt(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.pickup_comments.append(
        {
            "id": 701,
            "issue_url": f"https://api.github.com/repos/{REPO}/issues/5245",
            "body": "Pickup intent receipt: agent=new-agent session=new-session branch=new-branch worktree="
            f"{tmp_path} coordination_mode=github-label-only-fallback fallback_reason=dispatcher_db_missing issue=5245",
            "user": {"login": "RasmusTho"},
            "created_at": "2026-09-02T00:01:00Z",
        }
    )
    with pytest.raises(ClosureError, match="current claimant authority"):
        build_closure_plan(request(tmp_path), executor=fake)


def test_closure_apply_rejects_stale_fallback_claimant_after_merge(
    tmp_path: Path,
) -> None:
    fake = Fake(tmp_path)
    plan = build_closure_plan(request(tmp_path), executor=fake)
    fake.merged = True
    fake.dispatcher_status = "claimed"
    fake.pickup_comments.append(
        {
            "id": 701,
            "issue_url": f"https://api.github.com/repos/{REPO}/issues/5245",
            "body": "Pickup intent receipt: agent=new-agent session=new-session branch=new-branch worktree="
            f"{tmp_path} coordination_mode=github-label-only-fallback fallback_reason=dispatcher_db_missing issue=5245",
            "user": {"login": "RasmusTho"},
            "created_at": "2026-09-02T00:01:00Z",
        }
    )
    with pytest.raises(ClosureError, match="current claimant authority"):
        apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert not any("DELETE" in call for call in fake.calls)


def test_closure_apply_rejects_fallback_when_dispatcher_lease_is_current(
    tmp_path: Path,
) -> None:
    fake = Fake(tmp_path)
    plan = build_closure_plan(request(tmp_path), executor=fake)
    fake.dispatcher_status = "claimed"
    with pytest.raises(ClosureError, match="current dispatcher lease"):
        apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert not any(any(part.endswith("/merge") for part in call) for call in fake.calls)


def test_closure_apply_rechecks_fallback_dispatcher_before_merge(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    plan = build_closure_plan(request(tmp_path), executor=fake)
    fake.claim_dispatcher_during_pr_readback = True
    with pytest.raises(ClosureError, match="current dispatcher lease"):
        apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert not any(any(part.endswith("/merge") for part in call) for call in fake.calls)


def test_closure_apply_rechecks_dispatcher_lease_row_before_merge(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.dispatcher_status = "claimed"
    task_id = fake.dispatcher_task["task_id"]
    plan = build_closure_plan(request(tmp_path, task_id), executor=fake)
    fake.release_dispatcher_lease_during_pr_readback = True
    with pytest.raises(ClosureError, match="lease row"):
        apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert not any(any(part.endswith("/merge") for part in call) for call in fake.calls)


@pytest.mark.parametrize("dispatcher_backed", [False, True])
def test_closure_apply_fences_post_merge_replacement_before_label_cleanup(
    tmp_path: Path, dispatcher_backed: bool
) -> None:
    fake = Fake(tmp_path)
    if dispatcher_backed:
        fake.dispatcher_status = "claimed"
        plan = build_closure_plan(request(tmp_path, fake.dispatcher_task["task_id"]), executor=fake)
    else:
        plan = build_closure_plan(request(tmp_path), executor=fake)
    fake.claim_dispatcher_after_merge = True
    with pytest.raises(ClosureError, match="dispatcher|current dispatcher lease"):
        apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert not any("DELETE" in call for call in fake.calls)


def test_closure_apply_holds_fallback_cleanup_guard_during_label_mutation(
    tmp_path: Path,
) -> None:
    fake = Fake(tmp_path)
    plan = build_closure_plan(request(tmp_path), executor=fake)
    fake.claim_dispatcher_during_label_cleanup = True
    receipt = apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert receipt["outcome"] == "success"
    assert fake.cleanup_guard_claim_blocked is True
    assert fake.cleanup_guard_active is False


@pytest.mark.parametrize("already_merged", [False, True])
def test_closure_apply_rejects_stale_merge_event_after_manual_reclose(
    tmp_path: Path, already_merged: bool
) -> None:
    fake = Fake(tmp_path)
    fake.stale_merge_close = True
    fake.close_actor = "manual-user"
    fake.closed_evidence = [
        {
            "__typename": "ClosedEvent",
            "createdAt": fake.close_created_at,
            "actor": {"login": "manual-user"},
            "closer": None,
        }
    ]
    plan = build_closure_plan(request(tmp_path), executor=fake)
    fake.merged = already_merged
    with pytest.raises(ClosureError, match="attribution"):
        apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert not any("DELETE" in call for call in fake.calls)


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


def test_closure_plan_accepts_neutral_required_check_conclusion(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.check_runs[0]["conclusion"] = "neutral"
    plan = build_closure_plan(request(tmp_path), executor=fake)
    assert plan["required_check_evidence"] == [{"kind": "check", "name": "CI", "app_id": 7, "evidence_id": 1}]


def test_closure_plan_rejects_present_but_empty_required_check_authority(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.required_checks = {"required_status_checks": {"contexts": [], "checks": []}}
    with pytest.raises(ClosureError, match="required-check authority is empty"):
        build_closure_plan(request(tmp_path), executor=fake)


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
    fake = Fake(tmp_path); fake.dispatcher_status = "claimed"; task_id = fake.dispatcher_task["task_id"]
    plan = build_closure_plan(request(tmp_path, task_id), executor=fake)
    fake.merged = True; fake.dispatcher_status = "completed"
    receipt = apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert receipt["reconciled"] is True
    assert not any(len(call) >= 4 and call[3] == "complete" for call in fake.calls)
    inspect_call = next(call for call in fake.calls if len(call) >= 4 and call[3] == "show" and "--events" in call)
    assert task_id in inspect_call


def test_closure_plan_requires_dispatcher_repository_and_issue_binding(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.dispatcher_status = "claimed"
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
            "__typename": "ClosedEvent",
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

    fake = Fake(tmp_path); fake.events_commit_id = None; fake.previous_null_close = True
    plan = build_closure_plan(request(tmp_path), executor=fake)
    receipt = apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert receipt["issue"]["closure_attribution"] == "GitHub-native exact PR closer attribution"


def test_closure_apply_paginates_issue_events_before_attribution(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.event_pages = [
        [{"event": "commented", "created_at": "2026-09-01T00:00:00Z"}],
        [{"event": "closed", "commit_id": MERGE, "created_at": fake.close_created_at, "actor": {"login": fake.close_actor}}],
    ]
    plan = build_closure_plan(request(tmp_path), executor=fake)
    receipt = apply_closure_plan(plan, expected_plan_sha256=plan["plan_sha256"], executor=fake)
    assert receipt["issue"]["closure_attribution"] == "GitHub-native closing keyword and exact merge event"
    events_call = next(
        call
        for call in fake.calls
        if call[:2] == ("gh", "api") and any("/issues/5245/events" in part for part in call)
    )
    assert "--paginate" in events_call and "--slurp" in events_call


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
        ("tier", 3),
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


@pytest.mark.parametrize("target", ["trust me", "tests/scripts/does-not-exist.py::test_missing"])
def test_closure_plan_rejects_unresolvable_or_missing_verify_target(tmp_path: Path, target: str) -> None:
    fake = Fake(tmp_path)
    fake.issue_body = ISSUE_BODY.replace(
        "tests/scripts/test_closure.py::test_closure_plan_is_canonical_hash_bound_read_only_and_strictly_light_path",
        target,
    )
    with pytest.raises(ClosureError, match="Verify target"):
        build_closure_plan(request(tmp_path), executor=fake)


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


def test_closure_plan_ignores_optional_skipped_check_runs_like_await_pr_checks(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.check_runs = [
        {"id": 1, "name": "CI", "status": "completed", "conclusion": "success", "app": {"id": 7}, "head_sha": HEAD, "started_at": "2026-09-02T00:00:01Z"},
        {"id": 3, "name": "CI", "status": "completed", "conclusion": "skipped", "app": {"id": 7}, "head_sha": HEAD, "started_at": "2026-09-02T00:00:02Z"},
        {"id": 4, "name": "optional-analysis", "status": "completed", "conclusion": "skipped", "app": {"id": 9}, "head_sha": HEAD, "started_at": "2026-09-02T00:00:03Z"},
        {"id": 2, "name": "pr-contract", "status": "completed", "conclusion": "success", "app": {"id": 8}, "head_sha": HEAD, "started_at": CHECK_STARTED},
    ]
    plan = build_closure_plan(request(tmp_path), executor=fake)
    assert {item["id"] for item in plan["checks"]} == {1, 2}


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


def test_closure_plan_accepts_valid_tier_one_evidence(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    evidence = dict(request(tmp_path).verify_evidence)
    evidence["tier"] = 1
    base = request(tmp_path)
    plan = build_closure_plan(
        ClosureRequest(REPO, tmp_path, 99, evidence, base.dispatcher_task_id, base.coordination_mode, base.fallback_reason, base.coordination_evidence, base.caller_agent, base.caller_session, base.caller_branch),
        executor=fake,
    )
    assert plan["tier"] == 1


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
    base = request(tmp_path)
    assert build_closure_plan(
        ClosureRequest(REPO, tmp_path, 99, evidence, base.dispatcher_task_id, base.coordination_mode, base.fallback_reason, base.coordination_evidence, base.caller_agent, base.caller_session, base.caller_branch),
        executor=fake,
    )["governing_issue"] == 5245


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
