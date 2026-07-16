from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from threading import Condition, Thread
from typing import Callable, Mapping
import zipfile
from zoneinfo import ZoneInfo

import pytest
import jsonschema

import app.dispatcher.verification_consumer as verification_consumer

from app.dispatcher.cli import _compact_verification_run
from app.dispatcher.verification_consumer import (
    AuthReceipt,
    CodexChatGPTAuthPreflight,
    CodexExecFailure,
    CodexExecLauncher,
    GhCliVerificationSource,
    LaunchConfig,
    VerificationConsumer,
    verification_attempt_idempotency_key,
)
from app.dispatcher.verification_agent_loop import (
    VerificationAgentLoop,
    valid_human_exception_packet,
)
from app.dispatcher.verification_dispatch import _authenticated_verification_request
from app.dispatcher.verified_merge import (
    build_verified_merge_phase,
    prepare_verified_merge,
)
from tests.dispatcher.verification_helpers import HEAD, REPO, ledger, request


@dataclass
class Truth:
    pr: dict[str, object]
    check_rows: list[dict[str, object]]
    authenticated_supporting: tuple[int, ...] = ()
    merge_repair_budget: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        self._last_pr = self.pr

    def pull_request(self, repository, pr_number):
        self._last_pr = self.pr
        return self.pr

    def checks(self, repository, head_sha):
        return self.check_rows

    def pull_request_comments(self, repository, pr_number):
        return _merge_comments(
            self._last_pr,
            authenticated_supporting=self.authenticated_supporting,
            repair_budget=self.merge_repair_budget,
        )

    def merge_commit(self, repository, merge_commit_sha):
        return _merge_commit(repository=repository, sha=merge_commit_sha)

    def issue_set_closure_evidence(
        self,
        repository,
        pr_number,
        *,
        issue_numbers,
        observed_issue_numbers,
        merged_at,
        merge_commit_sha,
        actor_login,
    ):
        return _closure_evidence(issue_numbers)


class Auth:
    def __init__(self, ok=True): self.ok = ok
    def check(self): return AuthReceipt(self.ok, "chatgpt", "keyring", None if self.ok else "auth")


class MutatingAuth(Auth):
    def __init__(self, truth: Truth, replacement_pr: dict[str, object]) -> None:
        super().__init__(True)
        self.truth = truth
        self.replacement_pr = replacement_pr

    def check(self):
        self.truth.pr = self.replacement_pr
        return super().check()


class FailingSecondReadTruth(Truth):
    def __init__(self) -> None:
        super().__init__(eligible_pr(), GREEN)
        self.pull_calls = 0

    def pull_request(self, repository, pr_number):
        self.pull_calls += 1
        if self.pull_calls == 2:
            raise RuntimeError("simulated GitHub source outage")
        return super().pull_request(repository, pr_number)


class FailingPostLaunchPrTruth(Truth):
    def __init__(self) -> None:
        super().__init__(eligible_pr(), GREEN)
        self.pull_calls = 0

    def pull_request(self, repository, pr_number):
        self.pull_calls += 1
        if self.pull_calls == 3:
            raise RuntimeError("simulated post-launch GitHub PR outage")
        return super().pull_request(repository, pr_number)


class FailingPostLaunchCheckTruth(Truth):
    def __init__(self) -> None:
        super().__init__(eligible_pr(), GREEN)
        self.check_calls = 0
        self.fail_once = True

    def checks(self, repository, head_sha):
        self.check_calls += 1
        if self.fail_once and self.check_calls == 3:
            self.fail_once = False
            raise RuntimeError("simulated post-launch GitHub check outage")
        return super().checks(repository, head_sha)


class PostMergeTerminalReadOutageTruth(Truth):
    def __init__(self) -> None:
        super().__init__(eligible_pr(), GREEN)
        self.pull_calls = 0

    def pull_request(self, repository, pr_number):
        self.pull_calls += 1
        if self.pull_calls <= 2:
            self._last_pr = eligible_pr()
            return self._last_pr
        if self.pull_calls == 3:
            raise RuntimeError("simulated post-merge terminal read outage")
        self._last_pr = merged_pr()
        return self._last_pr


class Launcher:
    config = LaunchConfig("verification_closer", "gpt-5.6-terra", "high", "workspace-write", "instructions")
    def __init__(self): self.calls = []
    def launch(self, context_pack, *, resume_session_id=None, on_thread_started=None, on_heartbeat=None):
        self.calls.append((context_pack, resume_session_id))
        session = resume_session_id or "01900000-0000-7000-8000-000000000001"
        if on_thread_started: on_thread_started(session)
        if on_heartbeat: on_heartbeat()
        return session, {
            "verdict": "needs_human",
            "head_sha": HEAD,
            "summary": "test",
            "receipt_ids": [],
            "retry_after": None,
            "review_events": None,
            "human_exception": {
                "failure_class": "authority-critical",
                "original_intent": "verify and close the governing issue",
                "current_state": "exact head is green but authority is missing",
                "tried_actions": ["validated CI and review evidence"],
                "evidence": ["PR #3620"],
                "why_unsafe": "continuation requires authority outside the issue",
                "options": [
                    {
                        "id": "hold",
                        "label": "Hold delivery",
                        "consequence": "delivery remains blocked",
                    },
                    {
                        "id": "authorize",
                        "label": "Authorize continuation",
                        "consequence": "delivery continues with expanded authority",
                    },
                ],
                "no_action_option": "hold",
                "recommended_option": "hold",
                "recommendation_rationale": "the current issue grants no expanded authority",
                "consequence_of_doing_nothing": "the delivery remains blocked",
            },
        }


class RateLimitedLauncher(Launcher):
    def launch(self, context_pack, *, resume_session_id=None, on_thread_started=None, on_heartbeat=None):
        self.calls.append((context_pack, resume_session_id))
        session = resume_session_id or "01900000-0000-7000-8000-000000000002"
        if on_thread_started: on_thread_started(session)
        return session, {
            "verdict": "retry", "head_sha": HEAD, "summary": "rate limit exhausted", "receipt_ids": [], "retry_after": "1h", "review_events": None, "human_exception": None
        }


class NegatedRateLimitLauncher(Launcher):
    def launch(
        self,
        context_pack,
        *,
        resume_session_id=None,
        on_thread_started=None,
        on_heartbeat=None,
    ):
        self.calls.append((context_pack, resume_session_id))
        session = resume_session_id or "01900000-0000-7000-8000-000000000003"
        if on_thread_started:
            on_thread_started(session)
        return session, {
            "verdict": "blocked",
            "head_sha": HEAD,
            "summary": "No rate limit was observed; verification is technically blocked",
            "receipt_ids": [],
            "retry_after": None,
            "review_events": None,
            "human_exception": None,
        }


class DeliveredLauncher(Launcher):
    def launch(
        self,
        context_pack,
        *,
        resume_session_id=None,
        on_thread_started=None,
        on_heartbeat=None,
    ):
        self.calls.append((context_pack, resume_session_id))
        session = resume_session_id or "01900000-0000-7000-8000-000000000004"
        if on_thread_started:
            on_thread_started(session)
        return session, {
            "verdict": "delivered",
            "head_sha": HEAD,
            "summary": "verified and merged",
            "receipt_ids": ["review-1", "review-2"],
            "retry_after": None,
            "review_events": [
                {
                    "kind": "review",
                    "session_id": "review-1",
                    "capability": "gpt-5.6-sol",
                    "reasoning_effort": "xhigh",
                    "outcome": "clean",
                    "finding_id": None,
                    "failure_domain": None,
                    "mechanism_id": None,
                    "strongest": True,
                },
                {
                    "kind": "review",
                    "session_id": "review-2",
                    "capability": "gpt-5.6-sol",
                    "reasoning_effort": "xhigh",
                    "outcome": "clean",
                    "finding_id": None,
                    "failure_domain": None,
                    "mechanism_id": None,
                    "strongest": True,
                },
            ],
            "human_exception": None,
        }


class TransitionTruth:
    def __init__(
        self,
        terminal_pr: dict[str, object],
        *,
        authenticated_supporting: tuple[int, ...] = (),
    ) -> None:
        # Intake and the post-auth launch fence must both observe stable open
        # authority before the coordinator's delivered receipt changes truth.
        self.prs = iter([eligible_pr(), eligible_pr(), terminal_pr])
        self._last_pr = eligible_pr()
        self.authenticated_supporting = authenticated_supporting

    def pull_request(self, repository, pr_number):
        self._last_pr = next(self.prs)
        return self._last_pr

    def checks(self, repository, head_sha):
        return GREEN

    def pull_request_comments(self, repository, pr_number):
        return _merge_comments(
            self._last_pr,
            authenticated_supporting=self.authenticated_supporting,
        )

    def merge_commit(self, repository, merge_commit_sha):
        return _merge_commit(repository=repository, sha=merge_commit_sha)

    def issue_set_closure_evidence(
        self,
        repository,
        pr_number,
        *,
        issue_numbers,
        observed_issue_numbers,
        merged_at,
        merge_commit_sha,
        actor_login,
    ):
        return _closure_evidence(issue_numbers)


class TerminalChecksTruth(TransitionTruth):
    def __init__(self, terminal_checks: list[dict[str, object]]) -> None:
        super().__init__(merged_pr())
        self.terminal_checks = terminal_checks
        self.check_calls = 0

    def checks(self, repository, head_sha):
        self.check_calls += 1
        if self.check_calls == 3:
            return self.terminal_checks
        return GREEN


def eligible_pr(**updates):
    value = {
        "number": 3603, "state": "open", "draft": False, "merged_at": None,
        "merge_commit_sha": None,
        "title": "dispatcher: verify and close issue set",
        "body": "Governing-Issue: #3603\n\nFixes #3603",
        "base": {"ref": "main", "repo": {"full_name": REPO}},
        "head": {"ref": "branch", "sha": HEAD},
    }
    value.update(updates)
    return value


def test_live_governing_issue_drift_fails_closed_before_launch(tmp_path) -> None:
    launcher = Launcher()
    pr = eligible_pr(body="Governing-Issue: #3626\n\nFixes #3626")

    result = VerificationConsumer(
        ledger(tmp_path), Truth(pr, GREEN), Auth(), launcher, "host"
    ).consume(request())

    assert result.status == "superseded"
    assert result.stop_reason == "governing_issue_mismatch"
    assert launcher.calls == []


def test_supporting_issue_addition_during_repair_preserves_governing_authority(
    tmp_path,
) -> None:
    launcher = Launcher()
    dispatch_request = request()
    dispatch_request["supporting_issues"] = [3626]
    pr = eligible_pr(
        body="Governing-Issue: #3603\n\nFixes #3603\nRefs #3626\nRefs #3745"
    )

    result = VerificationConsumer(
        ledger(tmp_path), Truth(pr, GREEN), Auth(), launcher, "host"
    ).consume(dispatch_request)

    assert result.status == "needs_human"
    assert len(launcher.calls) == 1


def test_supporting_issue_removal_or_governing_drift_fails_closed(tmp_path) -> None:
    for suffix, body in (
        ("removed", "Governing-Issue: #3603\n\nFixes #3603"),
        ("governing", "Governing-Issue: #3626\n\nFixes #3626"),
    ):
        dispatch_request = request()
        dispatch_request["supporting_issues"] = [3626]
        launcher = Launcher()
        result = VerificationConsumer(
            ledger(tmp_path / suffix),
            Truth(eligible_pr(body=body), GREEN),
            Auth(),
            launcher,
            "host",
        ).consume(dispatch_request)

        assert result.status == "superseded"
        assert result.stop_reason == "governing_issue_mismatch"
        assert launcher.calls == []


def test_head_move_during_auth_fails_closed_before_launch(tmp_path) -> None:
    truth = Truth(eligible_pr(), GREEN)
    launcher = Launcher()
    auth = MutatingAuth(truth, eligible_pr(head={"ref": "branch", "sha": "b" * 40}))

    result = VerificationConsumer(ledger(tmp_path), truth, auth, launcher, "host").consume(
        request()
    )

    assert result.status == "superseded"
    assert result.stop_reason == "stale_head"
    assert launcher.calls == []


def test_governing_issue_move_during_auth_fails_closed_before_launch(tmp_path) -> None:
    truth = Truth(eligible_pr(), GREEN)
    launcher = Launcher()
    auth = MutatingAuth(
        truth, eligible_pr(body="Governing-Issue: #3626\n\nFixes #3626")
    )

    result = VerificationConsumer(ledger(tmp_path), truth, auth, launcher, "host").consume(
        request()
    )

    assert result.status == "superseded"
    assert result.stop_reason == "governing_issue_mismatch"
    assert launcher.calls == []


def test_post_auth_live_truth_error_backs_off_claimed_run(tmp_path) -> None:
    truth = FailingSecondReadTruth()
    launcher = Launcher()

    result = VerificationConsumer(
        ledger(tmp_path), truth, Auth(), launcher, "host"
    ).consume(request())

    assert result.status == "backoff"
    assert result.terminal_receipt == {
        "outcome": "blocked",
        "reason": "prelaunch_live_truth_unavailable",
        "error_type": "RuntimeError",
    }
    assert truth.pull_calls == 2
    assert launcher.calls == []


def test_post_launch_live_truth_error_backs_off_running_run(tmp_path) -> None:
    state = ledger(tmp_path)
    truth = FailingPostLaunchPrTruth()
    launcher = Launcher()

    result = VerificationConsumer(state, truth, Auth(), launcher, "host").consume(
        request()
    )

    assert result.status == "backoff"
    assert result.claimed_by is None
    assert result.lease_id is None
    assert result.terminal_receipt["outcome"] == "blocked"
    assert result.terminal_receipt["reason"] == "postlaunch_live_truth_unavailable"
    assert result.terminal_receipt["error_type"] == "RuntimeError"
    assert result.terminal_receipt["pending_terminal_receipt"]["verdict"] == "needs_human"
    assert [row["kind"] for row in state.attempts(result.run_id)] == ["verification"]
    assert len(launcher.calls) == 1
    with state.store._connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM verification_exceptions WHERE run_id=?",
            (result.run_id,),
        ).fetchone()[0] == 0


def test_post_launch_check_error_preserves_verification_anchor(tmp_path) -> None:
    state = ledger(tmp_path)
    truth = FailingPostLaunchCheckTruth()
    launcher = Launcher()
    consumer = VerificationConsumer(state, truth, Auth(), launcher, "host")

    first = consumer.consume(request())
    assert first.status == "backoff"
    assert [row["kind"] for row in state.attempts(first.run_id)] == ["verification"]
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET retry_after='2000-01-01T00:00:00+00:00' "
            "WHERE run_id=?",
            (first.run_id,),
        )
        conn.commit()

    final = consumer.consume(request())

    assert final.status == "needs_human"
    assert [row["kind"] for row in state.attempts(final.run_id)] == ["verification"]
    assert [call[1] for call in launcher.calls] == [None, "01900000-0000-7000-8000-000000000001"]


def test_post_merge_terminal_read_outage_replays_exact_delivered_receipt(
    tmp_path,
) -> None:
    state = ledger(tmp_path)
    launcher = DeliveredLauncher()
    consumer = VerificationConsumer(
        state, PostMergeTerminalReadOutageTruth(), Auth(), launcher, "host"
    )

    first = consumer.consume(request())
    assert first.status == "backoff"
    assert first.terminal_receipt["reason"] == "postlaunch_live_truth_unavailable"
    assert first.terminal_receipt["pending_terminal_receipt"]["verdict"] == "delivered"
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET retry_after='2000-01-01T00:00:00+00:00' "
            "WHERE run_id=?",
            (first.run_id,),
        )
        conn.commit()

    final = consumer.consume(request())

    assert final.status == "completed"
    assert final.verified_head_sha == HEAD
    assert len(launcher.calls) == 1
    assert [row["kind"] for row in state.attempts(final.run_id)] == [
        "verification",
        "review",
        "review",
    ]


def test_pending_delivered_receipt_replay_is_idempotent(tmp_path) -> None:
    state = ledger(tmp_path)
    launcher = DeliveredLauncher()
    consumer = VerificationConsumer(
        state, PostMergeTerminalReadOutageTruth(), Auth(), launcher, "host"
    )
    first = consumer.consume(request())
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET retry_after='2000-01-01T00:00:00+00:00' "
            "WHERE run_id=?",
            (first.run_id,),
        )
        conn.commit()

    completed = consumer.consume(request())
    replay = consumer.consume(request())

    assert replay == completed
    assert len(launcher.calls) == 1
    assert [row["kind"] for row in state.attempts(replay.run_id)] == [
        "verification",
        "review",
        "review",
    ]


def test_delivered_receipt_rejects_unattributed_unauthorized_issue_closure(
    tmp_path,
) -> None:
    class UnauthorizedClosureTruth(TransitionTruth):
        def issue_set_closure_evidence(self, *args, issue_numbers, **kwargs):
            return _closure_evidence(issue_numbers, unauthorized=(4999,))

    result = VerificationConsumer(
        ledger(tmp_path),
        UnauthorizedClosureTruth(merged_pr()),
        Auth(),
        DeliveredLauncher(),
        "host",
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "receipt_live_truth_unauthorized_closure"
    assert result.verified_head_sha is None


def test_delivered_receipt_scans_phase_observed_unauthorized_candidate(
    tmp_path,
) -> None:
    class PhaseObservedClosureTruth(TransitionTruth):
        observed_candidates: list[int] | None = None

        def pull_request_comments(self, repository, pr_number):
            return _merge_comments(
                self._last_pr,
                reopened_unauthorized=(4999,),
            )

        def issue_set_closure_evidence(
            self,
            *args,
            issue_numbers,
            observed_issue_numbers,
            **kwargs,
        ):
            self.observed_candidates = list(observed_issue_numbers)
            return _closure_evidence(issue_numbers, unauthorized=(4999,))

    truth = PhaseObservedClosureTruth(merged_pr())
    result = VerificationConsumer(
        ledger(tmp_path),
        truth,
        Auth(),
        DeliveredLauncher(),
        "host",
    ).consume(request())

    assert truth.observed_candidates == [4999]
    assert result.status == "failed"
    assert result.stop_reason == "receipt_live_truth_unauthorized_closure"


def test_delivered_receipt_requires_trusted_exact_head_merge_authority(
    tmp_path,
) -> None:
    class ForgedAuthorityTruth(TransitionTruth):
        def pull_request_comments(self, repository, pr_number):
            comments = _merge_comments(self._last_pr)
            for comment in comments:
                comment["author_association"] = "NONE"
            return comments

    result = VerificationConsumer(
        ledger(tmp_path),
        ForgedAuthorityTruth(merged_pr()),
        Auth(),
        DeliveredLauncher(),
        "host",
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "receipt_live_truth_merge_authority_missing"
    assert result.verified_head_sha is None


def test_delivered_receipt_rejects_merge_authority_with_stale_repair_budget(
    tmp_path,
) -> None:
    class StaleBudgetTruth(TransitionTruth):
        def pull_request_comments(self, repository, pr_number):
            comments = _merge_comments(self._last_pr)
            comments[0]["body"] = str(comments[0]["body"]).replace(
                '"policy_version":"v2"', '"policy_version":"v1"'
            )
            return comments

    result = VerificationConsumer(
        ledger(tmp_path),
        StaleBudgetTruth(merged_pr()),
        Auth(),
        DeliveredLauncher(),
        "host",
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "receipt_live_truth_merge_authority_missing"
    assert result.verified_head_sha is None


@pytest.mark.parametrize("entrypoint", ["consume", "recover"])
@pytest.mark.parametrize(
    ("crash_phase", "crash_body_state"),
    [("prepared", "neutralized"), ("reconciled", "restored")],
)
def test_merged_incomplete_run_recovers_idempotently_after_coordinator_crash(
    tmp_path,
    entrypoint: str,
    crash_phase: str,
    crash_body_state: str,
) -> None:
    plan = _merge_plan(HEAD)
    crashed_pr = merged_pr(
        body=(
            plan["neutralized_body"]
            if crash_body_state == "neutralized"
            else plan["original_body"]
        )
    )

    class RecoveryTruth(Truth):
        def __init__(self) -> None:
            super().__init__(crashed_pr, GREEN)
            self.phase = crash_phase

        def pull_request_comments(self, repository, pr_number):
            return _merge_comments(self._last_pr, phase=self.phase)

    truth = RecoveryTruth()

    class RecoveryLauncher(DeliveredLauncher):
        def launch(
            self,
            context_pack,
            *,
            resume_session_id=None,
            on_thread_started=None,
            on_heartbeat=None,
        ):
            self.calls.append((context_pack, resume_session_id))
            truth.pr = merged_pr()
            truth._last_pr = truth.pr
            truth.phase = "restored"
            session = resume_session_id or "01900000-0000-7000-8000-000000000004"
            if on_thread_started:
                on_thread_started(session)
            if on_heartbeat:
                on_heartbeat()
            receipt = DeliveredLauncher().launch({})[1]
            return session, receipt

    state = ledger(tmp_path / entrypoint)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "crashed-host")
    persisted_pack = verification_consumer.context_pack(
        claimed,
        eligible_pr(),
        repair_budget=state.repair_budget_projection(run.run_id),
    )
    running = state.start(
        run.run_id,
        "crashed-host",
        claimed.lease_id or "",
        "01900000-0000-7000-8000-000000000004",
        persisted_pack,
    )
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET lease_expires_at=? WHERE run_id=?",
            ("2000-01-01T00:00:00+00:00", running.run_id),
        )
        conn.commit()
    budget_before = state.repair_budget_projection(run.run_id)
    launcher = RecoveryLauncher()
    consumer = VerificationConsumer(
        state, truth, Auth(), launcher, "recovery-host"
    )

    completed = (
        consumer.consume(_authenticated_verification_request(request()))
        if entrypoint == "consume"
        else consumer.recover(run.run_id)
    )

    assert completed.status == "completed"
    assert completed.run_id == run.run_id
    assert completed.verified_head_sha == HEAD
    assert state.repair_budget_projection(run.run_id) == budget_before
    assert len(launcher.calls) == 1
    recovered_pack, resumed_session = launcher.calls[0]
    assert resumed_session == "01900000-0000-7000-8000-000000000004"
    assert recovered_pack["merge_recovery"]["phase"] == crash_phase
    assert recovered_pack["merge_recovery"]["body_state"] == crash_body_state


def test_merged_incomplete_run_recovers_after_raced_body_edit_and_crash(
    tmp_path,
) -> None:
    plan = _merge_plan(HEAD)
    authority = plan["authority_receipt"]
    assert isinstance(authority, dict)
    neutral_pr = eligible_pr(body=plan["neutralized_body"])
    prepared = build_verified_merge_phase(
        authority_receipt=authority,
        phase="prepared",
        pr=neutral_pr,
    )
    raced_body = "Governing-Issue: #3603\n\nRefs #3603\nFixes #4999"
    crashed_pr = merged_pr(body=raced_body)

    class RecoveryTruth(Truth):
        def __init__(self) -> None:
            super().__init__(crashed_pr, GREEN)
            self.restored = False

        def pull_request_comments(self, repository, pr_number):
            if self.restored:
                return _merge_comments(self._last_pr)
            return [
                {
                    "author_association": "COLLABORATOR",
                    "body": plan["authority_receipt_comment"],
                },
                {
                    "author_association": "COLLABORATOR",
                    "body": prepared["phase_receipt_comment"],
                },
            ]

    truth = RecoveryTruth()

    class RecoveryLauncher(DeliveredLauncher):
        def launch(self, context_pack, **kwargs):
            assert context_pack["merge_recovery"]["phase"] == "prepared"
            assert context_pack["merge_recovery"]["body_state"] == "raced"
            truth.pr = merged_pr(body=plan["original_body"])
            truth._last_pr = truth.pr
            truth.restored = True
            return super().launch(context_pack, **kwargs)

    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "crashed-host")
    running = state.start(
        run.run_id,
        "crashed-host",
        claimed.lease_id or "",
        "01900000-0000-7000-8000-000000000004",
        verification_consumer.context_pack(
            claimed,
            eligible_pr(),
            repair_budget=state.repair_budget_projection(run.run_id),
        ),
    )
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET lease_expires_at=? WHERE run_id=?",
            ("2000-01-01T00:00:00+00:00", running.run_id),
        )
        conn.commit()

    completed = VerificationConsumer(
        state, truth, Auth(), RecoveryLauncher(), "recovery-host"
    ).recover(run.run_id)

    assert completed.status == "completed"
    assert completed.verified_head_sha == HEAD


def _corrupt_pending_delivered_receipt(state, run_id, mutate) -> None:
    current = state.get(run_id)
    assert current is not None
    terminal = dict(current.terminal_receipt)
    pending = dict(terminal["pending_terminal_receipt"])
    mutate(pending)
    terminal["pending_terminal_receipt"] = pending
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET terminal_receipt_json=?, "
            "retry_after='2000-01-01T00:00:00+00:00' WHERE run_id=?",
            (json.dumps(terminal, sort_keys=True), run_id),
        )
        conn.commit()


def test_pending_delivered_replay_revalidates_persisted_receipt(tmp_path) -> None:
    class CountingAuth(Auth):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def check(self):
            self.calls += 1
            return super().check()

    state = ledger(tmp_path)
    auth = CountingAuth()
    consumer = VerificationConsumer(
        state,
        PostMergeTerminalReadOutageTruth(),
        auth,
        DeliveredLauncher(),
        "host",
    )
    first = consumer.consume(request())
    _corrupt_pending_delivered_receipt(
        state, first.run_id, lambda pending: pending.pop("retry_after")
    )

    final = consumer.consume(request())

    assert final.status == "failed"
    assert final.stop_reason == "invalid_receipt_contract"
    assert final.verified_head_sha is None
    assert auth.calls == 1
    assert [row["kind"] for row in state.attempts(final.run_id)] == [
        "verification"
    ]


def test_invalid_pending_delivered_replay_is_redacted_and_never_needs_human(
    tmp_path,
) -> None:
    private = "credential=SHOULD_NOT_PERSIST /Users/operator/private-vault"
    state = ledger(tmp_path)
    consumer = VerificationConsumer(
        state,
        PostMergeTerminalReadOutageTruth(),
        Auth(),
        DeliveredLauncher(),
        "host",
    )
    first = consumer.consume(request())
    _corrupt_pending_delivered_receipt(
        state, first.run_id, lambda pending: pending.update({"diagnostic": private})
    )

    final = consumer.consume(request())

    durable = json.dumps(final.terminal_receipt, sort_keys=True)
    assert final.status == "failed"
    assert final.stop_reason == "invalid_receipt_contract"
    assert private not in durable
    with state.store._connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM verification_exceptions WHERE run_id=?",
            (final.run_id,),
        ).fetchone()[0] == 0


def test_pending_delivered_replay_schema_load_failure_fails_closed(tmp_path) -> None:
    state = ledger(tmp_path)
    truth = PostMergeTerminalReadOutageTruth()
    first = VerificationConsumer(
        state, truth, Auth(), DeliveredLauncher(), "host"
    ).consume(request())
    _corrupt_pending_delivered_receipt(state, first.run_id, lambda pending: None)

    final = VerificationConsumer(
        state,
        truth,
        Auth(),
        DeliveredLauncher(),
        "host",
        receipt_schema=tmp_path / "credential=SHOULD_NOT_PERSIST" / "schema.json",
    ).consume(request())

    assert final.status == "failed"
    assert final.stop_reason == "invalid_receipt_contract"
    assert final.terminal_receipt == {
        "outcome": "invalid_persisted_verification_receipt",
        "error_type": "FileNotFoundError",
    }
    assert [row["kind"] for row in state.attempts(final.run_id)] == [
        "verification"
    ]


def merged_pr(**updates: object) -> dict[str, object]:
    value = eligible_pr(
        state="closed",
        merged=True,
        merged_at="2026-07-15T00:00:00Z",
        merge_commit_sha="b" * 40,
        merged_by={"login": "verification-closer"},
        base={
            "ref": "main",
            "repo": {"full_name": "RasmusTho/agentic-pkm-mvp"},
        },
    )
    value.update(updates)
    return value


def _merge_commit(
    *,
    repository: str = REPO,
    sha: str = "b" * 40,
    message: str = "Merge verified issue set",
) -> dict[str, object]:
    return {"repository": repository, "sha": sha, "message": message}


def _verification_run_id() -> str:
    idempotency_key = request()["idempotency_key"]
    assert isinstance(idempotency_key, str)
    return f"vrun-{idempotency_key[:16]}"


def _merge_plan(
    head_sha: str,
    *,
    body: str = "Governing-Issue: #3603\n\nFixes #3603",
    authenticated_supporting: tuple[int, ...] = (),
    repair_budget: Mapping[str, object] | None = None,
) -> dict[str, object]:
    context = {
        "contract": "verification_closer_dispatch_context.v2",
        "run_id": _verification_run_id(),
        "repository": REPO,
        "pr_number": 3603,
        "governing_issue": 3603,
        "closing_issues": [3603],
        "supporting_issues": list(authenticated_supporting),
        "head_sha": head_sha,
        "repair_budget": (
            dict(repair_budget)
            if repair_budget is not None
            else {
                "policy_version": "v2",
                "mechanism_count": 0,
                "truncated": False,
                "omitted_count": 0,
                "mechanisms": [],
            }
        ),
    }
    return prepare_verified_merge(
        context=context,
        pr=eligible_pr(body=body, head={"ref": "branch", "sha": head_sha}),
        live_closing_issues=[3603],
    )


def _merge_comments(
    pr: Mapping[str, object],
    *,
    phase: str = "restored",
    authenticated_supporting: tuple[int, ...] = (),
    reopened_unauthorized: tuple[int, ...] = (),
    repair_budget: Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    head_sha = pr.get("head", {}).get("sha") if isinstance(pr.get("head"), Mapping) else None
    assert isinstance(head_sha, str)
    body = pr.get("body")
    assert isinstance(body, str)
    plan = _merge_plan(
        head_sha,
        body=(
            "Governing-Issue: #3603\n\nFixes #3603"
            if "Verified-Closing-Issues:" in body
            else body
        ),
        authenticated_supporting=authenticated_supporting,
        repair_budget=repair_budget,
    )
    authority = plan["authority_receipt"]
    assert isinstance(authority, dict)
    neutral = eligible_pr(
        body=plan["neutralized_body"],
        head={"ref": "branch", "sha": head_sha},
    )
    merged_neutral = {
        **dict(pr),
        "body": plan["neutralized_body"],
        "head": {"ref": "branch", "sha": head_sha},
    }
    restored = {
        **merged_neutral,
        "body": plan["original_body"],
    }
    phases = [
        build_verified_merge_phase(
            authority_receipt=authority, phase="prepared", pr=neutral
        ),
        build_verified_merge_phase(
            authority_receipt=authority, phase="merged", pr=merged_neutral
        ),
        build_verified_merge_phase(
            authority_receipt=authority,
            phase="reconciled",
            pr=merged_neutral,
            closed_issues=[3603],
            reopened_unauthorized_issues=list(reopened_unauthorized),
        ),
        build_verified_merge_phase(
            authority_receipt=authority,
            phase="restored",
            pr=restored,
            closed_issues=[3603],
            reopened_unauthorized_issues=list(reopened_unauthorized),
        ),
    ]
    phase_index = {"prepared": 1, "merged": 2, "reconciled": 3, "restored": 4}[phase]
    return [
        {
            "author_association": "COLLABORATOR",
            "body": plan["authority_receipt_comment"],
        },
        *[
            {
                "author_association": "COLLABORATOR",
                "body": item["phase_receipt_comment"],
            }
            for item in phases[:phase_index]
        ],
    ]


def _closure_evidence(
    issue_numbers: list[int] | tuple[int, ...],
    *,
    unauthorized: tuple[int, ...] = (),
) -> dict[str, object]:
    observed = sorted({*issue_numbers, *unauthorized})
    return {
        "closure_scan_complete": True,
        "observed_closing_issues": observed,
        "issue_evidence": [
            {
                "number": number,
                "state": "closed",
                "closed_by_delivery": True,
                "closed_by_pull_requests": [] if number in issue_numbers else [3603],
            }
            for number in observed
        ],
    }


def _repository_issue_event(
    event_id: int,
    *,
    number: int,
    created_at: str,
    event: str = "closed",
    commit_id: str | None = None,
    commit_repository: str = REPO,
    issue_repository: str = REPO,
) -> dict[str, object]:
    repository_url = f"https://api.github.com/repos/{issue_repository}"
    issue_url = f"{repository_url}/issues/{number}"
    return {
        "id": event_id,
        "url": f"{repository_url}/issues/events/{event_id}",
        "event": event,
        "commit_id": commit_id,
        "commit_url": (
            f"https://api.github.com/repos/{commit_repository}/commits/{commit_id}"
            if commit_id is not None
            else None
        ),
        "created_at": created_at,
        "issue": {
            "number": number,
            "url": issue_url,
            "repository_url": repository_url,
            "events_url": f"{issue_url}/events",
        },
    }


def _rest_issue(number: int, *, node_id: str | None = None) -> dict[str, object]:
    repository_url = f"https://api.github.com/repos/{REPO}"
    return {
        "node_id": node_id or f"I_kwDOclosure{number}",
        "number": number,
        "repository_url": repository_url,
        "url": f"{repository_url}/issues/{number}",
    }


def _graphql_closed_event(
    created_at: str,
    *,
    actor: str = "verification-closer",
    closer_number: int | None = None,
    closer_repository: str = REPO,
    closer_sha: str | None = "b" * 40,
) -> dict[str, object]:
    closer: dict[str, object] | None = None
    if closer_number is not None:
        closer = {
            "__typename": "PullRequest",
            "number": closer_number,
            "repository": {"nameWithOwner": closer_repository},
            "mergeCommit": {"oid": closer_sha},
        }
    return {
        "__typename": "ClosedEvent",
        "actor": {"login": actor},
        "closer": closer,
        "createdAt": created_at,
    }


def _graphql_issue(
    number: int,
    *,
    created_at: str,
    event: dict[str, object] | None = None,
    node_id: str | None = None,
    repository: str = REPO,
    state: str = "CLOSED",
) -> dict[str, object]:
    return {
        "__typename": "Issue",
        "id": node_id or f"I_kwDOclosure{number}",
        "number": number,
        "repository": {"nameWithOwner": repository},
        "state": state,
        "closedAt": created_at if state == "CLOSED" else None,
        "timelineItems": {
            "nodes": [event or _graphql_closed_event(created_at)]
            if state == "CLOSED"
            else []
        },
    }


def _graphql_result(*nodes: object) -> dict[str, object]:
    return {"data": {"nodes": list(nodes)}}


def _required_check_authority(
    head_sha: str = HEAD, *, suite_id: int = 1
) -> dict[str, object]:
    return {
        "check_suite": {"id": suite_id},
        "workflow_run": {
            "id": 1000 + suite_id,
            "workflow_id": 198962230,
            "path": ".github/workflows/ci.yml",
            "event": "pull_request",
            "head_sha": head_sha,
            "check_suite_id": suite_id,
            "run_attempt": 1,
        },
    }


def green_checks(head_sha: str = HEAD) -> list[dict[str, object]]:
    return [
        {
            "id": 1,
            "name": "Unit tests (not pg)",
            "app": {"slug": "github-actions"},
            **_required_check_authority(head_sha),
            "status": "completed",
            "conclusion": "success",
        }
    ]


GREEN = green_checks()


def artifact_request(**updates: object) -> dict[str, object]:
    value = request()
    value["artifact_provenance"] = {
        "workflow_run_id": 123,
        "repository_id": 456,
        "artifact_name": f"verification-dispatch-3603-{HEAD}",
    }
    value.update(updates)
    return value


def test_gh_source_fetches_bounded_artifact_and_live_truth_without_shell(tmp_path) -> None:
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr(
            "verification-dispatch/request.json", json.dumps(artifact_request())
        )

    class Result:
        def __init__(self, stdout):
            self.returncode = 0
            self.stdout = stdout

    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        endpoint = command[-1]
        if endpoint.endswith("actions/artifacts?per_page=100"):
            return Result(
                json.dumps(
                    {
                        "artifacts": [
                            {
                                "id": 7,
                                "name": f"verification-dispatch-3603-{HEAD}",
                                "size_in_bytes": len(archive_bytes.getvalue()),
                                "expired": False,
                                "workflow_run": {
                                    "id": 123,
                                    "repository_id": 456,
                                    "head_repository_id": 456,
                                    "head_sha": "b" * 40,
                                },
                            }
                        ]
                    }
                )
            )
        if endpoint.endswith("artifacts/7/zip"):
            return Result(archive_bytes.getvalue())
        if endpoint.endswith("actions/runs/123"):
            return Result(
                json.dumps(
                    {
                        "id": 123,
                        "run_attempt": 1,
                        "name": "Verification Dispatch Request",
                        "path": ".github/workflows/verification-dispatch-request.yml",
                        "event": "workflow_run",
                        "status": "completed",
                        "conclusion": "success",
                        "head_sha": "b" * 40,
                        "repository": {
                            "id": 456,
                            "full_name": "RasmusTho/agentic-pkm-mvp",
                        },
                        "head_repository": {
                            "id": 456,
                            "full_name": "RasmusTho/agentic-pkm-mvp",
                        },
                    }
                )
            )
        if endpoint.endswith("actions/runs/99"):
            return Result(
                json.dumps(
                    {
                        "id": 99,
                        "run_attempt": 1,
                        "name": "CI",
                        "path": ".github/workflows/ci.yml",
                        "event": "pull_request",
                        "status": "completed",
                        "conclusion": "success",
                        "head_sha": HEAD,
                        "repository": {
                            "id": 456,
                            "full_name": "RasmusTho/agentic-pkm-mvp",
                        },
                        "head_repository": {
                            "id": 456,
                            "full_name": "RasmusTho/agentic-pkm-mvp",
                        },
                    }
                )
            )
        if "/pulls/3603" in endpoint:
            return Result(json.dumps(eligible_pr()))
        if "/actions/runs?head_sha=" in endpoint:
            return Result(json.dumps({"workflow_runs": [GREEN[0]["workflow_run"]]}))
        return Result(json.dumps({"check_runs": GREEN}))

    source = GhCliVerificationSource(runner=runner)
    assert source.pending_requests("RasmusTho/agentic-pkm-mvp") == [artifact_request()]
    assert source.pull_request("RasmusTho/agentic-pkm-mvp", 3603)["number"] == 3603
    assert source.checks("RasmusTho/agentic-pkm-mvp", HEAD) == GREEN
    assert all(call[:2] == ["gh", "api"] for call in calls)


def test_gh_source_authenticates_check_workflow_suite_identity() -> None:
    raw_checks = [
        {
            "id": 10,
            "name": "Unit tests (not pg)",
            "app": {"slug": "github-actions"},
            "check_suite": {"id": 77},
            "status": "completed",
            "conclusion": "success",
        },
        {
            "id": 11,
            "name": "Unit tests (not pg)",
            "app": {"slug": "github-actions"},
            "check_suite": {"id": 88},
            "workflow_run": {
                "path": ".github/workflows/ci.yml",
                "check_suite_id": 88,
            },
            "status": "completed",
            "conclusion": "success",
        },
    ]

    class Result:
        returncode = 0

        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def runner(command, **_kwargs):
        endpoint = command[-1]
        if "/actions/runs?head_sha=" in endpoint:
            return Result(
                json.dumps(
                    {
                        "workflow_runs": [
                            {
                                "id": 123,
                                "workflow_id": 198962230,
                                "path": ".github/workflows/ci.yml",
                                "event": "pull_request",
                                "head_sha": HEAD,
                                "check_suite_id": 77,
                                "run_attempt": 1,
                            }
                        ]
                    }
                )
            )
        return Result(json.dumps({"check_runs": raw_checks}))

    checks = GhCliVerificationSource(runner=runner).checks(
        "RasmusTho/agentic-pkm-mvp", HEAD
    )

    assert checks[0]["workflow_run"] == {
        "id": 123,
        "workflow_id": 198962230,
        "path": ".github/workflows/ci.yml",
        "event": "pull_request",
        "head_sha": HEAD,
        "check_suite_id": 77,
        "run_attempt": 1,
    }
    assert "workflow_run" not in checks[1]
    assert (
        verification_consumer._checks_rejection(checks, expected_head_sha=HEAD)
        is None
    )


def test_gh_source_attributes_null_rest_commit_with_exact_graphql_closer() -> None:
    class Result:
        returncode = 0

        def __init__(self, value: object) -> None:
            self.stdout = json.dumps(value)

    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        calls.append(command)
        if command[:3] == ["gh", "api", "graphql"]:
            return Result(
                _graphql_result(
                    _graphql_issue(
                        3603,
                        created_at="2026-07-15T00:00:02Z",
                    ),
                    _graphql_issue(
                        4999,
                        created_at="2026-07-15T00:00:03Z",
                        event=_graphql_closed_event(
                            "2026-07-15T00:00:03Z", closer_number=3603
                        ),
                    ),
                )
            )
        endpoint = command[-1]
        if endpoint == f"repos/{REPO}/issues/events?per_page=100&page=1":
            return Result(
                [
                    _repository_issue_event(
                        20,
                        number=4999,
                        created_at="2026-07-15T00:00:03Z",
                        commit_id=None,
                    ),
                    _repository_issue_event(
                        19,
                        number=4998,
                        created_at="2026-07-14T23:59:59Z",
                        event="labeled",
                    ),
                ]
            )
        if endpoint == f"repos/{REPO}/issues/3603":
            return Result(_rest_issue(3603))
        if endpoint == f"repos/{REPO}/issues/4999":
            return Result(_rest_issue(4999))
        raise AssertionError(endpoint)

    evidence = GhCliVerificationSource(runner=runner).issue_set_closure_evidence(
        REPO,
        3603,
        issue_numbers=[3603],
        observed_issue_numbers=[],
        merged_at="2026-07-15T00:00:00Z",
        merge_commit_sha="b" * 40,
        actor_login="verification-closer",
    )

    assert evidence["closure_scan_complete"] is True
    assert evidence["observed_closing_issues"] == [3603, 4999]
    assert evidence["issue_evidence"] == [
        {
            "closed_at": "2026-07-15T00:00:02Z",
            "closed_by_delivery": True,
            "closed_by_pull_requests": [],
            "number": 3603,
            "state": "closed",
        },
        {
            "closed_at": "2026-07-15T00:00:03Z",
            "closed_by_delivery": True,
            "closed_by_pull_requests": [3603],
            "number": 4999,
            "state": "closed",
        },
    ]
    graphql_calls = [call for call in calls if call[:3] == ["gh", "api", "graphql"]]
    assert len(graphql_calls) == 1
    assert "-F" not in graphql_calls[0]
    assert graphql_calls[0].count("-f") == 3
    assert all(
        argument.startswith("ids[]=")
        for argument in graphql_calls[0]
        if argument.startswith("ids[]=")
    )
    assert len(calls) == 4
    assert not any(
        f"/issues/{number}/events?per_page=100" in argument
        for call in calls
        for argument in call
        for number in (3603, 4999)
    )


def test_gh_source_busy_repository_does_not_expand_closure_calls() -> None:
    class Result:
        returncode = 0

        def __init__(self, value: object) -> None:
            self.stdout = json.dumps(value)

    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        calls.append(command)
        if command[:3] == ["gh", "api", "graphql"]:
            return Result(
                _graphql_result(
                    _graphql_issue(
                        3603,
                        created_at="2026-07-15T00:00:02Z",
                    )
                )
            )
        endpoint = command[-1]
        if endpoint.startswith(
            f"repos/{REPO}/issues/events?per_page=100&page="
        ):
            page = int(endpoint.rsplit("=", 1)[1])
            if page < 5:
                return Result(
                    [
                        _repository_issue_event(
                            page * 1000 + offset,
                            number=6000 + offset,
                            created_at=f"2026-07-15T00:00:{9 - page:02d}Z",
                            event="labeled",
                        )
                        for offset in range(100)
                    ]
                )
            return Result(
                [
                    _repository_issue_event(
                        5001,
                        number=6001,
                        created_at="2026-07-14T23:59:59Z",
                        event="labeled",
                    )
                ]
            )
        if endpoint == f"repos/{REPO}/issues/3603":
            return Result(_rest_issue(3603))
        raise AssertionError(f"unbounded busy-repository call: {endpoint}")

    evidence = GhCliVerificationSource(runner=runner).issue_set_closure_evidence(
        REPO,
        3603,
        issue_numbers=[3603],
        observed_issue_numbers=[],
        merged_at="2026-07-15T00:00:00Z",
        merge_commit_sha="b" * 40,
        actor_login="verification-closer",
    )

    assert evidence["observed_closing_issues"] == [3603]
    assert len(calls) == 7
    assert sum(
        "/issues/events?" in call[-1]
        for call in calls
        if call[:3] != ["gh", "api", "graphql"]
    ) == 5


def test_gh_source_rejects_malicious_rest_node_id_before_graphql() -> None:
    class Result:
        returncode = 0

        def __init__(self, value: object) -> None:
            self.stdout = json.dumps(value)

    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        calls.append(command)
        endpoint = command[-1]
        if endpoint == f"repos/{REPO}/issues/events?per_page=100&page=1":
            return Result(
                [
                    _repository_issue_event(
                        1,
                        number=3603,
                        created_at="2026-07-14T23:59:59Z",
                        event="labeled",
                    )
                ]
            )
        if endpoint == f"repos/{REPO}/issues/3603":
            return Result(_rest_issue(3603, node_id="@/private/secret"))
        raise AssertionError(endpoint)

    with pytest.raises(RuntimeError, match="malformed GitHub issue response"):
        GhCliVerificationSource(runner=runner).issue_set_closure_evidence(
            REPO,
            3603,
            issue_numbers=[3603],
            observed_issue_numbers=[],
            merged_at="2026-07-15T00:00:00Z",
            merge_commit_sha="b" * 40,
            actor_login="verification-closer",
        )
    assert len(calls) == 2
    assert not any(call[:3] == ["gh", "api", "graphql"] for call in calls)


def test_gh_source_repository_event_pagination_cap_fails_closed() -> None:
    class Result:
        returncode = 0

        def __init__(self, value: object) -> None:
            self.stdout = json.dumps(value)

    calls: list[str] = []

    def runner(command, **_kwargs):
        endpoint = command[-1]
        calls.append(endpoint)
        assert endpoint.startswith(
            f"repos/{REPO}/issues/events?per_page=100&page="
        )
        page = int(endpoint.rsplit("=", 1)[1])
        return Result(
            [
                _repository_issue_event(
                    page * 1000 + offset,
                    number=6000 + offset,
                    created_at=f"2026-07-15T00:00:{10 - page:02d}Z",
                    event="labeled",
                )
                for offset in range(100)
            ]
        )

    with pytest.raises(
        RuntimeError,
        match="cap reached before merge coverage",
    ):
        GhCliVerificationSource(runner=runner).issue_set_closure_evidence(
            REPO,
            3603,
            issue_numbers=[3603],
            observed_issue_numbers=[],
            merged_at="2026-07-15T00:00:00Z",
            merge_commit_sha="b" * 40,
            actor_login="verification-closer",
        )
    assert len(calls) == 5


def test_gh_source_repository_close_candidates_keep_existing_cap() -> None:
    class Result:
        returncode = 0

        def __init__(self, value: object) -> None:
            self.stdout = json.dumps(value)

    events = [
        _repository_issue_event(
            100 - offset,
            number=5000 + offset,
            created_at="2026-07-15T00:00:03Z",
            commit_id=None,
        )
        for offset in range(21)
    ]

    with pytest.raises(RuntimeError, match="candidates exceed bounded scan"):
        GhCliVerificationSource(
            runner=lambda *_args, **_kwargs: Result(events)
        ).issue_set_closure_evidence(
            REPO,
            3603,
            issue_numbers=[3603],
            observed_issue_numbers=[],
            merged_at="2026-07-15T00:00:00Z",
            merge_commit_sha="b" * 40,
            actor_login="verification-closer",
        )


def test_gh_source_rejects_foreign_repository_event_identity() -> None:
    class Result:
        returncode = 0

        def __init__(self, value: object) -> None:
            self.stdout = json.dumps(value)

    event = _repository_issue_event(
        20,
        number=4999,
        created_at="2026-07-15T00:00:03Z",
        commit_id=None,
        issue_repository="attacker/redirect",
    )

    with pytest.raises(RuntimeError, match="event identity"):
        GhCliVerificationSource(
            runner=lambda *_args, **_kwargs: Result([event])
        ).issue_set_closure_evidence(
            REPO,
            3603,
            issue_numbers=[3603],
            observed_issue_numbers=[],
            merged_at="2026-07-15T00:00:00Z",
            merge_commit_sha="b" * 40,
            actor_login="verification-closer",
        )


@pytest.mark.parametrize("closer_number", [None, 4998])
def test_gh_source_ignores_unrelated_graphql_closer(
    closer_number: int | None,
) -> None:
    class Result:
        returncode = 0

        def __init__(self, value: object) -> None:
            self.stdout = json.dumps(value)

    def runner(command, **_kwargs):
        if command[:3] == ["gh", "api", "graphql"]:
            return Result(
                _graphql_result(
                    _graphql_issue(
                        3603,
                        created_at="2026-07-15T00:00:02Z",
                    ),
                    _graphql_issue(
                        4999,
                        created_at="2026-07-15T00:00:03Z",
                        event=_graphql_closed_event(
                            "2026-07-15T00:00:03Z",
                            closer_number=closer_number,
                        ),
                    ),
                )
            )
        endpoint = command[-1]
        if endpoint == f"repos/{REPO}/issues/events?per_page=100&page=1":
            return Result(
                [
                    _repository_issue_event(
                        20,
                        number=4999,
                        created_at="2026-07-15T00:00:03Z",
                        commit_id=None,
                    ),
                    _repository_issue_event(
                        19,
                        number=4998,
                        created_at="2026-07-14T23:59:59Z",
                        event="labeled",
                    ),
                ]
            )
        if endpoint == f"repos/{REPO}/issues/3603":
            return Result(_rest_issue(3603))
        if endpoint == f"repos/{REPO}/issues/4999":
            return Result(_rest_issue(4999))
        raise AssertionError(endpoint)

    evidence = GhCliVerificationSource(runner=runner).issue_set_closure_evidence(
        REPO,
        3603,
        issue_numbers=[3603],
        observed_issue_numbers=[],
        merged_at="2026-07-15T00:00:00Z",
        merge_commit_sha="b" * 40,
        actor_login="verification-closer",
    )

    assert evidence["observed_closing_issues"] == [3603]
    assert [item["number"] for item in evidence["issue_evidence"]] == [3603]


@pytest.mark.parametrize(
    ("closer_repository", "closer_sha"),
    [("attacker/redirect", "b" * 40), (REPO, "c" * 40)],
)
def test_gh_source_rejects_forged_target_pr_closer_identity(
    closer_repository: str,
    closer_sha: str,
) -> None:
    class Result:
        returncode = 0

        def __init__(self, value: object) -> None:
            self.stdout = json.dumps(value)

    def runner(command, **_kwargs):
        if command[:3] == ["gh", "api", "graphql"]:
            return Result(
                _graphql_result(
                    _graphql_issue(
                        3603,
                        created_at="2026-07-15T00:00:02Z",
                    ),
                    _graphql_issue(
                        4999,
                        created_at="2026-07-15T00:00:03Z",
                        event=_graphql_closed_event(
                            "2026-07-15T00:00:03Z",
                            closer_number=3603,
                            closer_repository=closer_repository,
                            closer_sha=closer_sha,
                        ),
                    ),
                )
            )
        endpoint = command[-1]
        if endpoint == f"repos/{REPO}/issues/events?per_page=100&page=1":
            return Result(
                [
                    _repository_issue_event(
                        20,
                        number=4999,
                        created_at="2026-07-15T00:00:03Z",
                    ),
                    _repository_issue_event(
                        19,
                        number=4998,
                        created_at="2026-07-14T23:59:59Z",
                        event="labeled",
                    ),
                ]
            )
        if endpoint == f"repos/{REPO}/issues/3603":
            return Result(_rest_issue(3603))
        if endpoint == f"repos/{REPO}/issues/4999":
            return Result(_rest_issue(4999))
        raise AssertionError(endpoint)

    with pytest.raises(RuntimeError, match="closer identity mismatch"):
        GhCliVerificationSource(runner=runner).issue_set_closure_evidence(
            REPO,
            3603,
            issue_numbers=[3603],
            observed_issue_numbers=[],
            merged_at="2026-07-15T00:00:00Z",
            merge_commit_sha="b" * 40,
            actor_login="verification-closer",
        )


@pytest.mark.parametrize(
    "graphql_payload",
    [
        _graphql_result(
            _graphql_issue(3603, created_at="2026-07-15T00:00:02Z")
        ),
        _graphql_result(
            _graphql_issue(3603, created_at="2026-07-15T00:00:02Z"),
            _graphql_issue(3603, created_at="2026-07-15T00:00:02Z"),
        ),
        _graphql_result(
            {
                **_graphql_issue(3603, created_at="2026-07-15T00:00:02Z"),
                "__typename": "PullRequest",
            },
            _graphql_issue(4999, created_at="2026-07-15T00:00:03Z"),
        ),
    ],
    ids=["missing", "duplicate", "malformed"],
)
def test_gh_source_rejects_incomplete_or_malformed_graphql_batch(
    graphql_payload: dict[str, object],
) -> None:
    class Result:
        returncode = 0

        def __init__(self, value: object) -> None:
            self.stdout = json.dumps(value)

    def runner(command, **_kwargs):
        if command[:3] == ["gh", "api", "graphql"]:
            return Result(graphql_payload)
        endpoint = command[-1]
        if endpoint == f"repos/{REPO}/issues/events?per_page=100&page=1":
            return Result(
                [
                    _repository_issue_event(
                        20,
                        number=4999,
                        created_at="2026-07-15T00:00:03Z",
                    ),
                    _repository_issue_event(
                        19,
                        number=4998,
                        created_at="2026-07-14T23:59:59Z",
                        event="labeled",
                    ),
                ]
            )
        if endpoint == f"repos/{REPO}/issues/3603":
            return Result(_rest_issue(3603))
        if endpoint == f"repos/{REPO}/issues/4999":
            return Result(_rest_issue(4999))
        raise AssertionError(endpoint)

    with pytest.raises(RuntimeError, match="GraphQL closure"):
        GhCliVerificationSource(runner=runner).issue_set_closure_evidence(
            REPO,
            3603,
            issue_numbers=[3603],
            observed_issue_numbers=[],
            merged_at="2026-07-15T00:00:00Z",
            merge_commit_sha="b" * 40,
            actor_login="verification-closer",
        )


def test_gh_source_rejects_stale_graphql_closure_snapshot() -> None:
    class Result:
        returncode = 0

        def __init__(self, value: object) -> None:
            self.stdout = json.dumps(value)

    def runner(command, **_kwargs):
        if command[:3] == ["gh", "api", "graphql"]:
            return Result(
                _graphql_result(
                    _graphql_issue(
                        3603,
                        created_at="2026-07-15T00:00:02Z",
                    ),
                    _graphql_issue(
                        4999,
                        created_at="2026-07-15T00:00:01Z",
                    ),
                )
            )
        endpoint = command[-1]
        if endpoint == f"repos/{REPO}/issues/events?per_page=100&page=1":
            return Result(
                [
                    _repository_issue_event(
                        20,
                        number=4999,
                        created_at="2026-07-15T00:00:03Z",
                    ),
                    _repository_issue_event(
                        19,
                        number=4998,
                        created_at="2026-07-14T23:59:59Z",
                        event="labeled",
                    ),
                ]
            )
        if endpoint == f"repos/{REPO}/issues/3603":
            return Result(_rest_issue(3603))
        if endpoint == f"repos/{REPO}/issues/4999":
            return Result(_rest_issue(4999))
        raise AssertionError(endpoint)

    with pytest.raises(RuntimeError, match="does not match REST closure"):
        GhCliVerificationSource(runner=runner).issue_set_closure_evidence(
            REPO,
            3603,
            issue_numbers=[3603],
            observed_issue_numbers=[],
            merged_at="2026-07-15T00:00:00Z",
            merge_commit_sha="b" * 40,
            actor_login="verification-closer",
        )


def test_gh_source_rejects_oversized_graphql_closure_response() -> None:
    class Result:
        returncode = 0

        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def runner(command, **_kwargs):
        if command[:3] == ["gh", "api", "graphql"]:
            return Result("x" * 1_000_001)
        endpoint = command[-1]
        if endpoint == f"repos/{REPO}/issues/events?per_page=100&page=1":
            return Result(
                json.dumps(
                    [
                        _repository_issue_event(
                            19,
                            number=4998,
                            created_at="2026-07-14T23:59:59Z",
                            event="labeled",
                        )
                    ]
                )
            )
        if endpoint == f"repos/{REPO}/issues/3603":
            return Result(json.dumps(_rest_issue(3603)))
        raise AssertionError(endpoint)

    with pytest.raises(RuntimeError, match="exceeds bounded read"):
        GhCliVerificationSource(runner=runner).issue_set_closure_evidence(
            REPO,
            3603,
            issue_numbers=[3603],
            observed_issue_numbers=[],
            merged_at="2026-07-15T00:00:00Z",
            merge_commit_sha="b" * 40,
            actor_login="verification-closer",
        )


def test_production_terminal_evidence_rejects_removed_ref_merge_closure(
    tmp_path,
) -> None:
    class Result:
        returncode = 0

        def __init__(self, value: object) -> None:
            self.stdout = json.dumps(value)

    state = ledger(tmp_path)
    run = state.ingest(request())
    budget = state.repair_budget_projection(run.run_id)
    terminal_pr = merged_pr()
    comments = _merge_comments(terminal_pr, repair_budget=budget)

    def runner(command, **_kwargs):
        if command[:3] == ["gh", "api", "graphql"]:
            return Result(
                _graphql_result(
                    _graphql_issue(
                        3603,
                        created_at="2026-07-15T00:00:02Z",
                    ),
                    _graphql_issue(
                        4999,
                        created_at="2026-07-15T00:00:03Z",
                        event=_graphql_closed_event(
                            "2026-07-15T00:00:03Z", closer_number=3603
                        ),
                    ),
                )
            )
        endpoint = command[-1]
        if endpoint == f"repos/{REPO}/git/commits/{'b' * 40}":
            return Result(
                {
                    "sha": "b" * 40,
                    "url": (
                        f"https://api.github.com/repos/{REPO}/git/commits/"
                        + "b" * 40
                    ),
                    "message": "Merge verified issue set",
                }
            )
        if endpoint == f"repos/{REPO}/issues/3603/comments?per_page=100&page=1":
            return Result(comments)
        if endpoint == f"repos/{REPO}/issues/events?per_page=100&page=1":
            return Result(
                [
                    _repository_issue_event(
                        20,
                        number=4999,
                        created_at="2026-07-15T00:00:03Z",
                        commit_id=None,
                    ),
                    _repository_issue_event(
                        19,
                        number=4998,
                        created_at="2026-07-14T23:59:59Z",
                        event="labeled",
                    ),
                ]
            )
        if endpoint in {
            f"repos/{REPO}/issues/3603",
            f"repos/{REPO}/issues/4999",
        }:
            number = int(endpoint.rsplit("/", 1)[1])
            return Result(_rest_issue(number))
        raise AssertionError(endpoint)

    consumer = VerificationConsumer(
        state,
        GhCliVerificationSource(runner=runner),
        Auth(),
        DeliveredLauncher(),
        "host",
    )
    evidence = consumer._read_delivery_evidence(
        run,
        terminal_pr,
        expected_repair_budget=budget,
    )

    assert evidence["observed_closing_issues"] == [3603, 4999]
    assert (
        verification_consumer.delivered_live_truth_rejection(
            run,
            terminal_pr,
            GREEN,
            evidence,
            expected_head_sha=HEAD,
            expected_repair_budget=budget,
        )
        == "unauthorized_closure"
    )


def test_gh_source_rejects_malformed_repository_event_commit() -> None:
    class Result:
        returncode = 0

        def __init__(self, value: object) -> None:
            self.stdout = json.dumps(value)

    event = _repository_issue_event(
        20,
        number=4999,
        created_at="2026-07-15T00:00:03Z",
        commit_id="not-a-sha",
    )

    with pytest.raises(RuntimeError, match="malformed.*commit identity"):
        GhCliVerificationSource(
            runner=lambda *_args, **_kwargs: Result([event])
        ).issue_set_closure_evidence(
            REPO,
            3603,
            issue_numbers=[3603],
            observed_issue_numbers=[],
            merged_at="2026-07-15T00:00:00Z",
            merge_commit_sha="b" * 40,
            actor_login="verification-closer",
        )


def test_gh_source_rejects_out_of_order_repository_events() -> None:
    class Result:
        returncode = 0

        def __init__(self, value: object) -> None:
            self.stdout = json.dumps(value)

    events = [
        _repository_issue_event(
            20,
            number=4999,
            created_at="2026-07-14T23:59:59Z",
            event="labeled",
        ),
        _repository_issue_event(
            21,
            number=5000,
            created_at="2026-07-15T00:00:03Z",
            event="labeled",
        ),
    ]

    with pytest.raises(RuntimeError, match="ordering mismatch"):
        GhCliVerificationSource(
            runner=lambda *_args, **_kwargs: Result(events)
        ).issue_set_closure_evidence(
            REPO,
            3603,
            issue_numbers=[3603],
            observed_issue_numbers=[],
            merged_at="2026-07-15T00:00:00Z",
            merge_commit_sha="b" * 40,
            actor_login="verification-closer",
        )


def test_gh_source_fetches_exact_bounded_merge_commit_identity() -> None:
    class Result:
        returncode = 0

        def __init__(self, value: object) -> None:
            self.stdout = json.dumps(value)

    sha = "b" * 40
    endpoint = f"repos/{REPO}/git/commits/{sha}"

    def runner(command, **_kwargs):
        assert command[-1] == endpoint
        return Result(
            {
                "sha": sha,
                "url": f"https://api.github.com/repos/{REPO}/git/commits/{sha}",
                "message": "Merge verified issue set\n\nAuthority retained by receipt.",
                "verification": {"payload": "must-not-cross-boundary"},
            }
        )

    assert GhCliVerificationSource(runner=runner).merge_commit(REPO, sha) == {
        "repository": REPO,
        "sha": sha,
        "message": "Merge verified issue set\n\nAuthority retained by receipt.",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {
            "sha": "c" * 40,
            "url": f"https://api.github.com/repos/{REPO}/git/commits/{'c' * 40}",
            "message": "Merge verified issue set",
        },
        {
            "sha": "b" * 40,
            "url": (
                "https://api.github.com/repos/attacker/redirect/git/commits/"
                + "b" * 40
            ),
            "message": "Merge verified issue set",
        },
    ],
)
def test_gh_source_rejects_mismatched_merge_commit_identity(payload) -> None:
    class Result:
        returncode = 0
        stdout = json.dumps(payload)

    with pytest.raises(RuntimeError, match="merge commit identity mismatch"):
        GhCliVerificationSource(runner=lambda *_args, **_kwargs: Result()).merge_commit(
            REPO, "b" * 40
        )


def test_gh_source_merge_commit_read_is_size_bounded() -> None:
    class Result:
        returncode = 0
        stdout = json.dumps({"padding": "x" * 70_000})

    with pytest.raises(RuntimeError, match="exceeds bounded read"):
        GhCliVerificationSource(runner=lambda *_args, **_kwargs: Result()).merge_commit(
            REPO, "b" * 40
        )


def test_merged_recovery_pending_replay_uses_durable_authority_budget_after_advance(
    tmp_path,
) -> None:
    repaired_head = "c" * 40
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "crashed-host")
    persisted_pack = verification_consumer.context_pack(
        claimed,
        eligible_pr(),
        repair_budget=state.repair_budget_projection(run.run_id),
    )
    launch_budget = persisted_pack["repair_budget"]
    running = state.start(
        run.run_id,
        "crashed-host",
        claimed.lease_id or "",
        "01900000-0000-7000-8000-000000000030",
        persisted_pack,
    )
    rebound = state.rebind_head(
        run.run_id,
        repaired_head,
        expected_head_sha=HEAD,
        observed_repository=REPO,
        observed_pr_number=3603,
        observed_head_sha=repaired_head,
        holder="crashed-host",
        lease_id=running.lease_id or "",
    )
    state.record_attempt(
        run.run_id,
        "standard_repair",
        "repair-session",
        "gpt-5.6-terra",
        "high",
        {"head_sha": repaired_head},
        "fixed",
        {
            "finding_id": "F-recovery",
            "failure_domain": "review_code_correctness",
            "mechanism_id": "same-session-repair",
        },
        holder="crashed-host",
        lease_id=rebound.lease_id or "",
    )
    advanced_budget = state.repair_budget_projection(run.run_id)
    assert advanced_budget != launch_budget
    plan = _merge_plan(repaired_head, repair_budget=launch_budget)
    crashed_pr = merged_pr(
        body=plan["neutralized_body"],
        head={"ref": "branch", "sha": repaired_head},
    )

    class RecoveryTruth(Truth):
        def __init__(self) -> None:
            super().__init__(crashed_pr, green_checks(repaired_head))
            self.phase = "prepared"
            self.fail_next_pull = False

        def pull_request(self, repository, pr_number):
            if self.fail_next_pull:
                self.fail_next_pull = False
                raise RuntimeError("simulated post-launch GitHub read outage")
            return super().pull_request(repository, pr_number)

        def pull_request_comments(self, repository, pr_number):
            return _merge_comments(
                self._last_pr,
                phase=self.phase,
                repair_budget=launch_budget,
            )

    truth = RecoveryTruth()

    class RecoveryLauncher(DeliveredLauncher):
        def launch(self, context_pack, **kwargs):
            assert context_pack["head_sha"] == repaired_head
            assert context_pack["repair_budget"] == advanced_budget
            assert context_pack["requested_head_sha"] == HEAD
            truth.pr = merged_pr(head={"ref": "branch", "sha": repaired_head})
            truth._last_pr = truth.pr
            truth.phase = "restored"
            truth.fail_next_pull = True
            session, receipt = super().launch(context_pack, **kwargs)
            return session, {**receipt, "head_sha": repaired_head}

    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET lease_expires_at=? WHERE run_id=?",
            ("2000-01-01T00:00:00+00:00", run.run_id),
        )
        conn.commit()

    consumer = VerificationConsumer(
        state, truth, Auth(), RecoveryLauncher(), "recovery-host"
    )
    pending = consumer.recover(run.run_id)

    assert pending.status == "backoff"
    assert pending.terminal_receipt["reason"] == "postlaunch_live_truth_unavailable"
    assert pending.terminal_receipt["pending_terminal_receipt"]["verdict"] == "delivered"
    assert pending.terminal_receipt["merge_authority_repair_budget"] == launch_budget
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET retry_after='2000-01-01T00:00:00+00:00' "
            "WHERE run_id=?",
            (run.run_id,),
        )
        conn.commit()

    completed = consumer.consume(
        _authenticated_verification_request(request(repaired_head))
    )

    assert completed.status == "completed"
    assert completed.head_sha == repaired_head
    assert completed.requested_head_sha == HEAD
    assert [row["kind"] for row in state.attempts(run.run_id)] == [
        "standard_repair",
        "verification",
        "review",
        "review",
    ]
    assert len(consumer.launcher.calls) == 1
    assert state.repair_budget_projection(run.run_id) == advanced_budget


def _artifact_source_for_request(payload: dict[str, object], *, workflow_run_id: int = 123):
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("verification-dispatch/request.json", json.dumps(payload))

    class Result:
        def __init__(self, stdout):
            self.returncode = 0
            self.stdout = stdout

    calls: list[list[str]] = []

    def runner(command, **kwargs):
        calls.append(command)
        if command[-1].endswith("actions/artifacts?per_page=100"):
            return Result(
                json.dumps(
                    {
                        "artifacts": [
                            {
                                "id": 7,
                                "name": f"verification-dispatch-3603-{HEAD}",
                                "size_in_bytes": len(archive_bytes.getvalue()),
                                "expired": False,
                                "workflow_run": {
                                    "id": workflow_run_id,
                                    "repository_id": 456,
                                    "head_repository_id": 456,
                                    "head_sha": "b" * 40,
                                },
                            }
                        ]
                    }
                )
            )
        if command[-1].endswith(f"actions/runs/{workflow_run_id}"):
            return Result(
                json.dumps(
                    {
                        "id": workflow_run_id,
                        "run_attempt": 1,
                        "name": "Verification Dispatch Request",
                        "path": ".github/workflows/verification-dispatch-request.yml",
                        "event": "workflow_run",
                        "status": "completed",
                        "conclusion": "success",
                        "head_sha": "b" * 40,
                        "repository": {
                            "id": 456,
                            "full_name": "RasmusTho/agentic-pkm-mvp",
                        },
                        "head_repository": {
                            "id": 456,
                            "full_name": "RasmusTho/agentic-pkm-mvp",
                        },
                    }
                )
            )
        if command[-1].endswith("actions/runs/99"):
            return Result(
                json.dumps(
                    {
                        "id": 99,
                        "run_attempt": 1,
                        "name": "CI",
                        "path": ".github/workflows/ci.yml",
                        "event": "pull_request",
                        "status": "completed",
                        "conclusion": "success",
                        "head_sha": HEAD,
                        "repository": {
                            "id": 456,
                            "full_name": "RasmusTho/agentic-pkm-mvp",
                        },
                        "head_repository": {
                            "id": 456,
                            "full_name": "RasmusTho/agentic-pkm-mvp",
                        },
                    }
                )
            )
        return Result(archive_bytes.getvalue())

    return GhCliVerificationSource(runner=runner), calls


def test_pending_request_rejects_oversized_archive_before_buffering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Process:
        def __init__(self) -> None:
            self.stdout = io.BytesIO(
                b"x" * (verification_consumer._MAX_ARTIFACT_COMPRESSED_BYTES + 1)
            )
            self.returncode: int | None = None
            self.terminate_calls = 0
            self.wait_calls = 0

        def terminate(self) -> None:
            self.terminate_calls += 1
            self.returncode = -15

        def kill(self) -> None:
            self.returncode = -9

        def wait(self, timeout: float | None = None) -> int:
            self.wait_calls += 1
            if self.returncode is None:
                self.returncode = 0
            return self.returncode

    process = Process()
    source = GhCliVerificationSource()
    monkeypatch.setattr(
        source,
        "_json",
        lambda endpoint: (
            {
                "artifacts": [
                    {
                        "id": 7,
                        "name": f"verification-dispatch-3603-{HEAD}",
                        # Even stale or lying metadata cannot bypass the stream cap.
                        "size_in_bytes": 1,
                        "expired": False,
                        "workflow_run": {
                            "id": 123,
                            "repository_id": 456,
                            "head_repository_id": 456,
                            "head_sha": "b" * 40,
                        },
                    }
                ]
            }
            if endpoint.endswith("actions/artifacts?per_page=100")
            else {
                "id": 123,
                "run_attempt": 1,
                "name": "Verification Dispatch Request",
                "path": ".github/workflows/verification-dispatch-request.yml",
                "event": "workflow_run",
                "status": "completed",
                "conclusion": "success",
                "head_sha": "b" * 40,
                "repository": {
                    "id": 456,
                    "full_name": "RasmusTho/agentic-pkm-mvp",
                },
                "head_repository": {
                    "id": 456,
                    "full_name": "RasmusTho/agentic-pkm-mvp",
                },
            }
        ),
    )
    monkeypatch.setattr(
        verification_consumer.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )

    monkeypatch.setattr(
        verification_consumer.io,
        "BytesIO",
        lambda *_args, **_kwargs: pytest.fail("oversized artifact reached BytesIO"),
    )

    with pytest.raises(ValueError, match="compressed size limit"):
        source.pending_requests("RasmusTho/agentic-pkm-mvp")

    assert process.terminate_calls == 1
    assert process.wait_calls >= 1


def test_pending_request_rejects_oversized_archive_members() -> None:
    archives: list[bytes] = []
    member_archive = io.BytesIO()
    with zipfile.ZipFile(member_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("verification-dispatch/request.json", json.dumps(artifact_request()))
        for index in range(verification_consumer._MAX_ARTIFACT_MEMBERS):
            archive.writestr(f"extra-{index}.txt", "x")
    archives.append(member_archive.getvalue())

    aggregate_archive = io.BytesIO()
    with zipfile.ZipFile(aggregate_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("verification-dispatch/request.json", json.dumps(artifact_request()))
        archive.writestr(
            "large.txt",
            b"x" * verification_consumer._MAX_ARTIFACT_UNCOMPRESSED_BYTES,
        )
    archives.append(aggregate_archive.getvalue())

    for payload in archives:
        class Result:
            def __init__(self, stdout):
                self.returncode = 0
                self.stdout = stdout

        def runner(command, **kwargs):
            if command[-1].endswith("actions/artifacts?per_page=100"):
                return Result(
                    json.dumps(
                        {
                            "artifacts": [
                                {
                                    "id": 7,
                                    "name": f"verification-dispatch-3603-{HEAD}",
                                    "size_in_bytes": len(payload),
                                    "expired": False,
                                    "workflow_run": {
                                        "id": 123,
                                        "repository_id": 456,
                                        "head_repository_id": 456,
                                        "head_sha": "b" * 40,
                                    },
                                }
                            ]
                        }
                    )
                )
            if command[-1].endswith("actions/runs/123"):
                return Result(
                    json.dumps(
                        {
                            "id": 123,
                            "run_attempt": 1,
                            "name": "Verification Dispatch Request",
                            "path": ".github/workflows/verification-dispatch-request.yml",
                            "event": "workflow_run",
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "b" * 40,
                            "repository": {
                                "id": 456,
                                "full_name": "RasmusTho/agentic-pkm-mvp",
                            },
                            "head_repository": {
                                "id": 456,
                                "full_name": "RasmusTho/agentic-pkm-mvp",
                            },
                        }
                    )
                )
            return Result(payload)

        with pytest.raises(ValueError, match="too many members|uncompressed size limit"):
            GhCliVerificationSource(runner=runner).pending_requests(
                "RasmusTho/agentic-pkm-mvp"
            )


def test_pending_request_rejects_repository_mismatch() -> None:
    source, calls = _artifact_source_for_request(
        artifact_request(repository="attacker/redirected-repo")
    )

    with pytest.raises(ValueError, match="artifact repository mismatch"):
        source.pending_requests("RasmusTho/agentic-pkm-mvp")

    assert len(calls) == 3


def test_pending_request_rejects_workflow_run_mismatch() -> None:
    source, calls = _artifact_source_for_request(
        artifact_request(), workflow_run_id=999
    )

    with pytest.raises(ValueError, match="artifact workflow-run mismatch"):
        source.pending_requests("RasmusTho/agentic-pkm-mvp")

    assert len(calls) == 3


def test_pending_request_rejects_v1_empty_supporting_closure_authority() -> None:
    payload = artifact_request()
    payload["contract_version"] = "verification_dispatch_request.v1"
    payload.pop("closing_issues")
    assert payload["supporting_issues"] == []
    identity = {
        "contract_version": payload["contract_version"],
        "head_sha": payload["current_head_sha"],
        "pr_number": payload["pr_number"],
        "repository": payload["repository"],
        "stage": payload["stage"],
    }
    payload["idempotency_key"] = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    source, calls = _artifact_source_for_request(payload)

    with pytest.raises(ValueError, match="request artifact is malformed"):
        source.pending_requests("RasmusTho/agentic-pkm-mvp")

    assert len(calls) == 4


@pytest.mark.parametrize("pr,checks,reason", [
    ({}, GREEN, "malformed_pr"),
    (eligible_pr(draft=True), GREEN, "draft"),
    (eligible_pr(state="closed"), GREEN, "closed_unmerged_or_merged"),
    (eligible_pr(head={"ref": "branch", "sha": "b" * 40}), GREEN, "stale_head"),
    (eligible_pr(), [], "missing_checks"),
])
def test_live_truth_gate_rejects_ineligible_requests(tmp_path, pr, checks, reason) -> None:
    launcher = Launcher()
    result = VerificationConsumer(ledger(tmp_path), Truth(pr, checks), Auth(), launcher, "host").consume(request())
    assert result.status == ("backoff" if reason == "missing_checks" else "superseded")
    assert result.stop_reason == (None if reason == "missing_checks" else reason)
    assert launcher.calls == []


def test_eligible_request_invokes_registered_verification_closer_with_minimal_context(tmp_path) -> None:
    launcher = Launcher()
    result = VerificationConsumer(
        ledger(tmp_path), Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    ).consume(request())
    assert result.status == "needs_human"
    pack, resumed = launcher.calls[0]
    assert resumed is None
    assert pack["agent_adapter"] == ".codex/agents/verification-closer.toml"
    assert pack["verification_skill"] == ".codex/skills/verification-and-closure/SKILL.md"
    assert pack["verified_merge_phase_contract"] == (
        "verified_issue_set_merge_phase.v1"
    )
    assert pack["verified_merge_phase_writer"] == (
        "scripts/build_verified_issue_set_merge_phase.py"
    )
    assert pack["governing_issue"] == 3603
    assert pack["closing_issues"] == [3603]
    assert pack["supporting_issues"] == []
    assert "body" not in pack and "credentials" not in pack


def test_multi_issue_context_separates_parent_closure_and_evidence_authority(
    tmp_path,
) -> None:
    dispatch_request = request()
    dispatch_request["supporting_issues"] = [3626, 3698, 3705]
    dispatch_request["closing_issues"] = [3626, 3698]
    pr = eligible_pr(
        body=(
            "Governing-Issue: #3603\n\nRefs #3705\n"
            "Fixes #3626\nCloses #3698"
        )
    )
    launcher = Launcher()

    result = VerificationConsumer(
        ledger(tmp_path), Truth(pr, GREEN), Auth(), launcher, "host"
    ).consume(dispatch_request)

    assert result.status == "needs_human"
    pack, _ = launcher.calls[0]
    assert pack["governing_issue"] == 3603
    assert pack["closing_issues"] == [3626, 3698]
    assert pack["supporting_issues"] == [3626, 3698, 3705]


def test_live_body_cannot_expand_authenticated_closing_authority(tmp_path) -> None:
    dispatch_request = request()
    dispatch_request["closing_issues"] = [3626]
    dispatch_request["supporting_issues"] = [3626]
    pr = eligible_pr(
        body=(
            "Governing-Issue: #3603\nFixes #3626\n"
            "Refs #9999\nCloses #9999"
        )
    )
    launcher = Launcher()

    result = VerificationConsumer(
        ledger(tmp_path), Truth(pr, GREEN), Auth(), launcher, "host"
    ).consume(dispatch_request)

    assert result.status == "superseded"
    assert result.stop_reason == "governing_issue_mismatch"
    assert launcher.calls == []


@pytest.mark.parametrize("separator", ["\r", "\u2028", "\u2029"])
def test_unsupported_authority_line_separator_never_launches_consumer(
    tmp_path, separator
) -> None:
    launcher = Launcher()
    pr = eligible_pr(body=f"Governing-Issue: #3603{separator}Fixes #3603")

    result = VerificationConsumer(
        ledger(tmp_path), Truth(pr, GREEN), Auth(), launcher, "host"
    ).consume(request())

    assert result.status == "superseded"
    assert result.stop_reason == "governing_issue_mismatch"
    assert launcher.calls == []


def test_needs_human_receipt_persists_deduplicated_exception(tmp_path) -> None:
    state = ledger(tmp_path)
    result = VerificationConsumer(
        state, Truth(eligible_pr(), GREEN), Auth(), Launcher(), "host"
    ).consume(request())

    assert result.status == "needs_human"
    assert result.stop_reason == "authority-critical"
    assert result.terminal_receipt is not None
    exception_id = result.terminal_receipt["exception_id"]
    with state.store._connect() as conn:
        rows = conn.execute(
            "SELECT exception_id, failure_class, head_sha, packet_json "
            "FROM verification_exceptions WHERE run_id=?",
            (result.run_id,),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["exception_id"] == exception_id
    assert rows[0]["failure_class"] == "authority-critical"
    assert rows[0]["head_sha"] == HEAD
    packet = json.loads(rows[0]["packet_json"])
    assert packet["governing_issue"] == 3603
    assert packet["summary"] == "[REDACTED]"
    assert packet["recommended_option"] == "hold"


def test_needs_human_receipt_requires_valid_complete_owner_packet(tmp_path) -> None:
    class IncompleteHumanLauncher(Launcher):
        def launch(self, context_pack, **kwargs):
            session, receipt = super().launch(context_pack, **kwargs)
            receipt["human_exception"] = {
                "failure_class": "coordinator_needs_human",
            }
            return session, receipt

    state = ledger(tmp_path)
    result = VerificationConsumer(
        state, Truth(eligible_pr(), GREEN), Auth(), IncompleteHumanLauncher(), "host"
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "invalid_receipt_contract"
    with state.store._connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM verification_exceptions WHERE run_id=?",
            (result.run_id,),
        ).fetchone()[0] == 0


def test_human_exception_packet_requires_two_to_three_actionable_options(
    tmp_path,
) -> None:
    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "app/dispatcher/schemas/verification_closer_receipt.schema.json"
        ).read_text(encoding="utf-8")
    )
    _, receipt = Launcher().launch({})
    receipt.update(
        {"retry_after": None, "review_events": None}
    )

    verification_consumer.validate_verification_closer_receipt(receipt, schema)
    packet = receipt["human_exception"]
    assert isinstance(packet, dict)
    for field, value in (
        ("tried_actions", []),
        ("evidence", []),
        ("options", [packet["options"][0]]),
        ("options", [*packet["options"], {"id": "defer", "label": "Defer", "consequence": "work waits"}, {"id": "delegate", "label": "Delegate", "consequence": "another owner decides"}]),
        ("options", [packet["options"][0], packet["options"][0]]),
        ("no_action_option", "not-offered"),
        ("recommended_option", "not-offered"),
    ):
        invalid = {**receipt, "human_exception": {**packet, field: value}}
        with pytest.raises(jsonschema.ValidationError):
            verification_consumer.validate_verification_closer_receipt(invalid, schema)
        assert not valid_human_exception_packet(invalid["human_exception"])


def test_human_exception_options_require_ids_labels_and_consequences(
    tmp_path,
) -> None:
    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "app/dispatcher/schemas/verification_closer_receipt.schema.json"
        ).read_text(encoding="utf-8")
    )
    _, receipt = Launcher().launch({})
    receipt.update({"retry_after": None, "review_events": None})
    packet = receipt["human_exception"]
    assert isinstance(packet, dict)

    for options in (
        ["hold", "authorize"],
        [{"id": "hold", "label": "Hold delivery"}, packet["options"][1]],
        [packet["options"][0], {**packet["options"][1], "id": "hold"}],
    ):
        invalid = {**receipt, "human_exception": {**packet, "options": options}}
        with pytest.raises(jsonschema.ValidationError):
            verification_consumer.validate_verification_closer_receipt(invalid, schema)
        assert not valid_human_exception_packet(invalid["human_exception"])


def test_human_exception_recommendation_requires_rationale(tmp_path) -> None:
    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "app/dispatcher/schemas/verification_closer_receipt.schema.json"
        ).read_text(encoding="utf-8")
    )
    _, receipt = Launcher().launch({})
    receipt.update({"retry_after": None, "review_events": None})
    packet = receipt["human_exception"]
    assert isinstance(packet, dict)

    for rationale in (None, "", "   "):
        invalid_packet = {**packet, "recommendation_rationale": rationale}
        invalid = {**receipt, "human_exception": invalid_packet}
        with pytest.raises(jsonschema.ValidationError):
            verification_consumer.validate_verification_closer_receipt(invalid, schema)
        assert not valid_human_exception_packet(invalid_packet)


def test_pending_repair_checks_persist_repair_before_backoff(tmp_path) -> None:
    new_head = "b" * 40
    pending = [
        {
            "id": 2,
            "name": "Unit tests (not pg)",
            "app": {"slug": "github-actions"},
            **_required_check_authority(new_head, suite_id=2),
            "status": "in_progress",
            "conclusion": None,
        }
    ]
    truth = Truth(eligible_pr(), GREEN)

    class PendingRepairLauncher(Launcher):
        def launch(self, context_pack, **kwargs):
            self.calls.append((context_pack, kwargs.get("resume_session_id")))
            if callback := kwargs.get("on_thread_started"):
                callback("01900000-0000-7000-8000-000000000005")
            truth.pr = eligible_pr(head={"ref": "branch", "sha": new_head})
            truth.check_rows = pending
            return "01900000-0000-7000-8000-000000000005", {
                "verdict": "blocked",
                "head_sha": new_head,
                "summary": "repair pushed; checks pending",
                "receipt_ids": ["repair-1"],
                "retry_after": None,
                "review_events": [
                    {
                        "kind": "repair",
                        "session_id": "repair-1",
                        "capability": "gpt-5.6-terra",
                        "reasoning_effort": "high",
                        "outcome": "fixed",
                        "finding_id": "F1",
                        "failure_domain": "review_code_correctness",
                        "mechanism_id": "pending-repair",
                        "strongest": False,
                    }
                ],
                "human_exception": None,
            }

    state = ledger(tmp_path)
    result = VerificationConsumer(
        state, truth, Auth(), PendingRepairLauncher(), "host"
    ).consume(request())

    assert result.status == "backoff"
    assert result.head_sha == new_head
    assert [row["kind"] for row in state.attempts(result.run_id)] == [
        "verification",
        "standard_repair",
    ]


def test_supporting_issue_addition_allows_repair_head_rebind_without_budget_reset(
    tmp_path,
) -> None:
    new_head = "b" * 40
    pending = [
        {
            "id": 2,
            "name": "Unit tests (not pg)",
            "app": {"slug": "github-actions"},
            **_required_check_authority(new_head, suite_id=2),
            "status": "in_progress",
            "conclusion": None,
        }
    ]
    original_head = HEAD
    truth = Truth(
        eligible_pr(body="Governing-Issue: #3603\n\nFixes #3603\nRefs #3626"),
        GREEN,
    )

    class SupportingRepairLauncher(Launcher):
        def launch(self, context_pack, **kwargs):
            if callback := kwargs.get("on_thread_started"):
                callback("01900000-0000-7000-8000-000000000006")
            truth.pr = eligible_pr(
                body=(
                    "Governing-Issue: #3603\n\nRefs #3603\n"
                    "Fixes #3603\nRefs #3626\nRefs #3745"
                ),
                head={"ref": "branch", "sha": new_head},
            )
            truth.check_rows = pending
            return "01900000-0000-7000-8000-000000000006", {
                "verdict": "blocked",
                "head_sha": new_head,
                "summary": "bounded repair published",
                "receipt_ids": ["repair-3745"],
                "retry_after": None,
                "review_events": [
                    {
                        "kind": "repair",
                        "session_id": "repair-3745",
                        "capability": "gpt-5.6-terra",
                        "reasoning_effort": "high",
                        "outcome": "fixed",
                        "finding_id": "F3745",
                        "failure_domain": "review_code_correctness",
                        "mechanism_id": "supporting-repair",
                        "strongest": False,
                    }
                ],
                "human_exception": None,
            }

    state = ledger(tmp_path)
    dispatch_request = request()
    dispatch_request["supporting_issues"] = [3626]
    result = VerificationConsumer(
        state, truth, Auth(), SupportingRepairLauncher(), "host"
    ).consume(dispatch_request)

    assert result.status == "backoff"
    assert result.requested_head_sha == original_head
    assert result.head_sha == new_head
    assert result.request["supporting_issues"] == [3626]
    assert [row["kind"] for row in state.attempts(result.run_id)] == [
        "verification",
        "standard_repair",
    ]


def test_invalid_pending_repair_event_batch_fails_before_backoff(tmp_path) -> None:
    new_head = "b" * 40
    pending = [
        {
            "id": 2,
            "name": "Unit tests (not pg)",
            "app": {"slug": "github-actions"},
            **_required_check_authority(new_head, suite_id=2),
            "status": "in_progress",
            "conclusion": None,
        }
    ]
    truth = Truth(eligible_pr(), GREEN)

    class InvalidPendingRepairLauncher(Launcher):
        def launch(self, context_pack, **kwargs):
            if callback := kwargs.get("on_thread_started"):
                callback("01900000-0000-7000-8000-000000000007")
            truth.pr = eligible_pr(head={"ref": "branch", "sha": new_head})
            truth.check_rows = pending
            return "01900000-0000-7000-8000-000000000007", {
                "verdict": "blocked",
                "head_sha": new_head,
                "summary": "schema-valid but semantically invalid repair",
                "receipt_ids": ["repair-1"],
                "retry_after": None,
                "review_events": [
                    {
                        "kind": "repair",
                        "session_id": "repair-1",
                        "capability": "gpt-5.6-terra",
                        "reasoning_effort": "high",
                        "outcome": "fixed",
                        "finding_id": "F1",
                        "failure_domain": "review_code_correctness",
                        "mechanism_id": "invalid-strongest-repair",
                        "strongest": True,
                    }
                ],
                "human_exception": None,
            }

    state = ledger(tmp_path)
    result = VerificationConsumer(
        state, truth, Auth(), InvalidPendingRepairLauncher(), "host"
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "receipt_event_application_failed"
    assert result.claimed_by is None
    assert result.lease_id is None
    assert result.terminal_receipt == {
        "outcome": "receipt_event_application_failed",
        "error_type": "ValueError",
        "head_sha": new_head,
    }
    assert [row["kind"] for row in state.attempts(result.run_id)] == [
        "verification"
    ]


def test_invalid_review_event_batch_terminals_without_stranding_lease(tmp_path) -> None:
    class OverBudgetReviewLauncher(Launcher):
        def launch(self, context_pack, **kwargs):
            if callback := kwargs.get("on_thread_started"):
                callback("01900000-0000-7000-8000-000000000008")
            return "01900000-0000-7000-8000-000000000008", {
                "verdict": "blocked",
                "head_sha": HEAD,
                "summary": "three clean reviews exceed the durable budget",
                "receipt_ids": ["review-1", "review-2", "review-3"],
                "retry_after": None,
                "review_events": [
                    {
                        "kind": "review",
                        "session_id": f"review-{index}",
                        "capability": "gpt-5.6-sol",
                        "reasoning_effort": "xhigh",
                        "outcome": "clean",
                        "finding_id": None,
                        "failure_domain": None,
                        "mechanism_id": None,
                        "strongest": None,
                    }
                    for index in range(1, 4)
                ],
                "human_exception": None,
            }

    state = ledger(tmp_path)
    result = VerificationConsumer(
        state, Truth(eligible_pr(), GREEN), Auth(), OverBudgetReviewLauncher(), "host"
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "receipt_event_application_failed"
    assert result.claimed_by is None
    assert result.lease_id is None
    assert result.terminal_receipt == {
        "outcome": "receipt_event_application_failed",
        "error_type": "ValueError",
        "head_sha": HEAD,
    }
    assert [row["kind"] for row in state.attempts(result.run_id)] == [
        "verification"
    ]
    with state.store._connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM verification_exceptions WHERE run_id=?",
            (result.run_id,),
        ).fetchone()[0] == 0


def test_pending_repair_replay_preserves_two_plus_two_accounting(tmp_path) -> None:
    new_head = "b" * 40
    pending = [
        {
            "id": 2,
            "name": "Unit tests (not pg)",
            "app": {"slug": "github-actions"},
            **_required_check_authority(new_head, suite_id=2),
            "status": "in_progress",
            "conclusion": None,
        }
    ]
    truth = Truth(eligible_pr(), GREEN)

    class PendingRepairLauncher(Launcher):
        def launch(self, context_pack, **kwargs):
            self.calls.append((context_pack, kwargs.get("resume_session_id")))
            if callback := kwargs.get("on_thread_started"):
                callback("01900000-0000-7000-8000-000000000005")
            truth.pr = eligible_pr(head={"ref": "branch", "sha": new_head})
            truth.check_rows = pending
            return "01900000-0000-7000-8000-000000000005", {
                "verdict": "blocked",
                "head_sha": new_head,
                "summary": "repair pushed; checks pending",
                "receipt_ids": ["repair-1"],
                "retry_after": None,
                "review_events": [{
                    "kind": "repair", "session_id": "repair-1",
                    "capability": "gpt-5.6-terra", "reasoning_effort": "high",
                    "outcome": "fixed", "finding_id": "F1",
                    "failure_domain": "review_code_correctness",
                    "mechanism_id": "replay-repair", "strongest": False,
                }],
                "human_exception": None,
            }

    class ReviewOnlyDeliveryLauncher(Launcher):
        def launch(self, context_pack, **kwargs):
            self.calls.append((context_pack, kwargs.get("resume_session_id")))
            truth.merge_repair_budget = context_pack["repair_budget"]
            truth.pr = merged_pr(head={"ref": "branch", "sha": new_head})
            return "01900000-0000-7000-8000-000000000020", {
                "verdict": "delivered",
                "head_sha": new_head,
                "summary": "checks green and reviews clean",
                "receipt_ids": ["review-1", "review-2"],
                "retry_after": None,
                "review_events": [
                    {
                        "kind": "review", "session_id": "review-1",
                        "capability": "gpt-5.6-sol", "reasoning_effort": "xhigh",
                        "outcome": "clean", "finding_id": None,
                        "failure_domain": None, "mechanism_id": None,
                        "strongest": None,
                    },
                    {
                        "kind": "review", "session_id": "review-2",
                        "capability": "gpt-5.6-sol", "reasoning_effort": "xhigh",
                        "outcome": "clean", "finding_id": None,
                        "failure_domain": None, "mechanism_id": None,
                        "strongest": None,
                    },
                ],
                "human_exception": None,
            }

    state = ledger(tmp_path)
    first = VerificationConsumer(
        state, truth, Auth(), PendingRepairLauncher(), "host"
    ).consume(request())
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET retry_after='2000-01-01T00:00:00+00:00' "
            "WHERE run_id=?",
            (first.run_id,),
        )
        conn.commit()
    truth.pr = eligible_pr(head={"ref": "branch", "sha": new_head})
    truth.check_rows = green_checks(new_head)

    final = VerificationConsumer(
        state, truth, Auth(), ReviewOnlyDeliveryLauncher(), "host"
    ).consume(request(new_head))

    assert final.status == "completed"
    assert [row["kind"] for row in state.attempts(final.run_id)] == [
        "verification", "standard_repair", "verification", "review", "review"
    ]


def test_exact_terminal_receipt_replay_preserves_closure_anchor(tmp_path) -> None:
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "host")
    state.start(run.run_id, "host", claimed.lease_id, "01900000-0000-7000-8000-000000000009", {})
    receipt = {"verdict": "delivered", "head_sha": HEAD, "summary": "clean"}
    key = verification_attempt_idempotency_key(
        "01900000-0000-7000-8000-000000000009", "gpt-5.6-sol", "xhigh", receipt
    )
    events = [
        {
            "kind": "review", "session_id": "review-1",
            "capability": "gpt-5.6-sol", "reasoning_effort": "xhigh",
            "outcome": "clean", "finding_id": None,
            "failure_domain": None, "mechanism_id": None, "strongest": None,
        },
        {
            "kind": "review", "session_id": "review-2",
            "capability": "gpt-5.6-sol", "reasoning_effort": "xhigh",
            "outcome": "clean", "finding_id": None,
            "failure_domain": None, "mechanism_id": None, "strongest": None,
        },
    ]
    loop = VerificationAgentLoop(
        state, run.run_id, holder="host", lease_id=claimed.lease_id
    )

    for context in ({"head_sha": HEAD}, {"head_sha": "b" * 40}):
        state.record_attempt(
            run.run_id, "verification", "01900000-0000-7000-8000-000000000009", "gpt-5.6-sol", "xhigh",
            context, "launched", receipt, holder="host", lease_id=claimed.lease_id,
            idempotency_key=key,
        )
        loop.apply_events(events, context={"head_sha": HEAD})

    assert [row["kind"] for row in state.attempts(run.run_id)] == [
        "verification", "review", "review"
    ]
    assert state.closure_ready(run.run_id) is True


def test_changed_terminal_receipt_does_not_deduplicate_verification_anchor(tmp_path) -> None:
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "host")
    first = {"verdict": "delivered", "head_sha": HEAD, "summary": "first"}
    changed = {**first, "summary": "changed"}

    for receipt in (first, changed):
        state.record_attempt(
            run.run_id, "verification", "01900000-0000-7000-8000-000000000009", "gpt-5.6-sol", "xhigh",
            {}, "launched", receipt, holder="host", lease_id=claimed.lease_id,
            idempotency_key=verification_attempt_idempotency_key(
                "01900000-0000-7000-8000-000000000009", "gpt-5.6-sol", "xhigh", receipt
            ),
        )

    assert [row["kind"] for row in state.attempts(run.run_id)] == [
        "verification", "verification"
    ]


def test_technical_receipt_failures_never_require_owner(tmp_path) -> None:
    class InvalidVerdictLauncher(Launcher):
        def launch(self, context_pack, **kwargs):
            session, receipt = super().launch(context_pack, **kwargs)
            receipt["verdict"] = "unknown"
            receipt["human_exception"] = None
            return session, receipt

    class InvalidHeadLauncher(Launcher):
        def launch(self, context_pack, **kwargs):
            session, receipt = super().launch(context_pack, **kwargs)
            receipt["head_sha"] = "not-a-sha"
            return session, receipt

    for launcher, reason in (
        (InvalidVerdictLauncher(), "invalid_verdict"),
        (InvalidHeadLauncher(), "receipt_head_mismatch"),
    ):
        state = ledger(tmp_path / reason)
        result = VerificationConsumer(
            state, Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
        ).consume(request())

        assert result.status == "failed"
        assert result.stop_reason == "invalid_receipt_contract"
        with state.store._connect() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM verification_exceptions WHERE run_id=?",
                (result.run_id,),
            ).fetchone()[0] == 0


def test_needs_human_receipt_replay_is_idempotent(tmp_path) -> None:
    state = ledger(tmp_path)
    launcher = Launcher()
    consumer = VerificationConsumer(
        state, Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    )

    first = consumer.consume(request())
    second = consumer.consume(request())

    assert second == first
    assert len(launcher.calls) == 1
    with state.store._connect() as conn:
        exception_count = conn.execute(
            "SELECT COUNT(*) FROM verification_exceptions WHERE run_id=?",
            (first.run_id,),
        ).fetchone()[0]
    assert exception_count == 1


def test_delivered_receipt_accepts_matching_post_merge_live_truth(tmp_path) -> None:
    result = VerificationConsumer(
        ledger(tmp_path),
        TransitionTruth(merged_pr()),
        Auth(),
        DeliveredLauncher(),
        "host",
    ).consume(request())

    assert result.status == "completed"
    assert result.verified_head_sha == HEAD


def test_schema_invalid_delivered_receipt_cannot_complete(tmp_path) -> None:
    class SchemaInvalidDeliveredLauncher(DeliveredLauncher):
        def launch(self, context_pack, **kwargs):
            session, receipt = super().launch(context_pack, **kwargs)
            del receipt["retry_after"]
            return session, receipt

    state = ledger(tmp_path)
    result = VerificationConsumer(
        state,
        TransitionTruth(merged_pr()),
        Auth(),
        SchemaInvalidDeliveredLauncher(),
        "host",
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "invalid_receipt_contract"
    assert result.verified_head_sha is None
    assert result.terminal_receipt == {
        "outcome": "invalid_verification_receipt",
        "error_type": "ValidationError",
    }


def test_schema_invalid_launcher_receipt_fails_before_attempt_or_events(
    tmp_path,
) -> None:
    class SchemaInvalidEventLauncher(DeliveredLauncher):
        def launch(self, context_pack, **kwargs):
            session, receipt = super().launch(context_pack, **kwargs)
            receipt["review_events"][0]["unexpected"] = "not canonical"
            return session, receipt

    state = ledger(tmp_path)
    result = VerificationConsumer(
        state,
        TransitionTruth(merged_pr()),
        Auth(),
        SchemaInvalidEventLauncher(),
        "host",
    ).consume(request())

    assert result.status == "failed"
    assert state.attempts(result.run_id) == []
    with state.store._connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM verification_exceptions WHERE run_id=?",
            (result.run_id,),
        ).fetchone()[0] == 0


def test_receipt_schema_load_failure_is_redacted_and_fails_closed(tmp_path) -> None:
    private_path = tmp_path / "credential=SHOULD_NOT_PERSIST" / "schema.json"
    state = ledger(tmp_path)
    result = VerificationConsumer(
        state,
        TransitionTruth(merged_pr()),
        Auth(),
        DeliveredLauncher(),
        "host",
        receipt_schema=private_path,
    ).consume(request())

    durable = json.dumps(result.terminal_receipt, sort_keys=True)
    assert result.status == "failed"
    assert result.stop_reason == "invalid_receipt_contract"
    assert result.terminal_receipt == {
        "outcome": "invalid_verification_receipt",
        "error_type": "FileNotFoundError",
    }
    assert "SHOULD_NOT_PERSIST" not in durable
    assert state.attempts(result.run_id) == []


def test_delivered_truth_accepts_added_supporting_repair_issue(tmp_path) -> None:
    dispatch_request = request()
    dispatch_request["supporting_issues"] = [3626]
    original_pr = eligible_pr(
        body="Governing-Issue: #3603\n\nFixes #3603\nRefs #3626"
    )
    terminal_pr = merged_pr(
        body=(
            "Governing-Issue: #3603\n\nRefs #3603\n"
            "Fixes #3603\nRefs #3626\nRefs #3745"
        )
    )
    truth = TransitionTruth(
        terminal_pr, authenticated_supporting=(3626,)
    )
    truth.prs = iter([original_pr, original_pr, terminal_pr])
    result = VerificationConsumer(
        ledger(tmp_path),
        truth,
        Auth(),
        DeliveredLauncher(),
        "host",
    ).consume(dispatch_request)

    assert result.status == "completed"
    assert result.verified_head_sha == HEAD


def test_same_head_live_supporting_add_remove_is_never_dispatched(
    tmp_path,
) -> None:
    dispatch_request = request()
    dispatch_request["supporting_issues"] = [3626]
    added = eligible_pr(
        body=(
            "Governing-Issue: #3603\n\nFixes #3603\n"
            "Refs #3626\nRefs #9999"
        )
    )
    terminal = merged_pr(
        body="Governing-Issue: #3603\n\nFixes #3603\nRefs #3626"
    )
    truth = TransitionTruth(
        terminal, authenticated_supporting=(3626,)
    )
    truth.prs = iter([added, added, terminal])
    launcher = DeliveredLauncher()

    result = VerificationConsumer(
        ledger(tmp_path), truth, Auth(), launcher, "host"
    ).consume(dispatch_request)

    assert result.status == "completed"
    pack, _ = launcher.calls[0]
    assert pack["supporting_issues"] == [3626]
    assert 9999 not in pack["supporting_issues"]
    assert result.supporting_authority == (3626,)


def test_delivered_receipt_rejects_unnamed_or_missing_required_gate(tmp_path) -> None:
    result = VerificationConsumer(
        ledger(tmp_path),
        TerminalChecksTruth(
            [{"status": "completed", "conclusion": "success"}]
        ),
        Auth(),
        DeliveredLauncher(),
        "host",
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "reviews_before_checks_green"
    assert result.verified_head_sha is None


@pytest.mark.parametrize("conclusion", ["skipped", "neutral", "failure", None])
def test_delivered_receipt_requires_successful_named_unit_typecheck_gate(
    tmp_path, conclusion
) -> None:
    status = "in_progress" if conclusion is None else "completed"
    result = VerificationConsumer(
        ledger(tmp_path),
        TerminalChecksTruth(
            [
                {
                    "id": 2,
                    "name": "Unit tests (not pg)",
                    "app": {"slug": "github-actions"},
                    **_required_check_authority(suite_id=2),
                    "status": status,
                    "conclusion": conclusion,
                }
            ]
        ),
        Auth(),
        DeliveredLauncher(),
        "host",
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "reviews_before_checks_green"
    assert result.verified_head_sha is None


@pytest.mark.parametrize(
    ("status", "conclusion"),
    [("in_progress", None), ("completed", "failure")],
)
def test_unnamed_non_green_check_cannot_be_ignored(
    tmp_path, status, conclusion
) -> None:
    result = VerificationConsumer(
        ledger(tmp_path),
        TerminalChecksTruth(
            [
                *GREEN,
                {"id": 2, "status": status, "conclusion": conclusion},
            ]
        ),
        Auth(),
        DeliveredLauncher(),
        "host",
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "reviews_before_checks_green"
    assert result.verified_head_sha is None


@pytest.mark.parametrize(
    ("terminal_pr", "reason"),
    [
        (
            merged_pr(merged=False, merged_at=None, merge_commit_sha=None),
            "receipt_live_truth_closed_unmerged",
        ),
        (
            merged_pr(head={"ref": "branch", "sha": "b" * 40}),
            "receipt_head_mismatch",
        ),
        (
            merged_pr(
                base={"ref": "main", "repo": {"full_name": "attacker/redirect"}}
            ),
            "receipt_live_truth_repository_mismatch",
        ),
        (
            merged_pr(merge_commit_sha=None),
            "receipt_live_truth_missing_merge_evidence",
        ),
    ],
)
def test_delivered_receipt_rejects_closed_unmerged_or_mismatched_merge(
    tmp_path, terminal_pr, reason
) -> None:
    result = VerificationConsumer(
        ledger(tmp_path),
        TransitionTruth(terminal_pr),
        Auth(),
        DeliveredLauncher(),
        "host",
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == reason


@pytest.mark.parametrize(
    "message",
    [
        "Fixes #3603\n\ncaller supplied body",
        "Merge verified issue set\n\nCloses #not-a-number",
        "Merge verified issue set\n\nResolves other/repository#4999",
        (
            "Merge verified issue set\n\nFixes "
            "https://github.com/other/repository/issues/4999"
        ),
    ],
)
def test_delivered_receipt_rejects_merge_commit_closing_attempts(
    tmp_path, message
) -> None:
    class ClosingCommitTruth(TransitionTruth):
        def merge_commit(self, repository, merge_commit_sha):
            return _merge_commit(
                repository=repository,
                sha=merge_commit_sha,
                message=message,
            )

    result = VerificationConsumer(
        ledger(tmp_path),
        ClosingCommitTruth(merged_pr()),
        Auth(),
        DeliveredLauncher(),
        "host",
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "receipt_live_truth_merge_commit_closing_attempt"


def test_delivered_receipt_rejects_cross_repository_merge_commit_evidence(
    tmp_path,
) -> None:
    class CrossRepositoryCommitTruth(TransitionTruth):
        def merge_commit(self, repository, merge_commit_sha):
            return _merge_commit(
                repository="attacker/redirect",
                sha=merge_commit_sha,
            )

    result = VerificationConsumer(
        ledger(tmp_path),
        CrossRepositoryCommitTruth(merged_pr()),
        Auth(),
        DeliveredLauncher(),
        "host",
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "receipt_live_truth_merge_commit_repository_mismatch"


def test_merged_recovery_rejects_closing_merge_commit_before_phase_acceptance(
    tmp_path,
) -> None:
    class ClosingCommitTruth(Truth):
        def merge_commit(self, repository, merge_commit_sha):
            return _merge_commit(
                repository=repository,
                sha=merge_commit_sha,
                message="Merge verified issue set\n\nFixes other/repository#4999",
            )

    state = ledger(tmp_path)
    run = state.ingest(request())
    consumer = VerificationConsumer(
        state,
        ClosingCommitTruth(merged_pr(), GREEN),
        Auth(),
        DeliveredLauncher(),
        "host",
    )

    with pytest.raises(
        ValueError,
        match="merge_commit_closing_attempt",
    ):
        consumer._merged_recovery_pack(run, merged_pr(), GREEN)


def test_codex_launcher_uses_explicit_noninteractive_flags_and_no_api_env(tmp_path, monkeypatch) -> None:
    calls = []

    class Result:
        returncode = 0
        stdout = '{"type":"thread.started","thread_id":"01900000-0000-7000-8000-000000000010"}\n{"type":"item.completed","item":{"type":"agent_message","text":"{\\"verdict\\":\\"blocked\\",\\"head_sha\\":\\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\",\\"summary\\":\\"test\\",\\"receipt_ids\\":[],\\"retry_after\\":null,\\"review_events\\":null,\\"human_exception\\":null}"}}\n'

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    monkeypatch.setenv("OPENAI_API_KEY", "must-not-pass")
    monkeypatch.setenv("CODEX_API_KEY", "must-not-pass")
    schema = tmp_path / "receipt.schema.json"
    schema.write_text(
        json.dumps(
            {
                "type": "object",
                "properties": {
                    "verdict": {"type": "string"},
                    "head_sha": {"type": "string"},
                    "summary": {"type": "string"},
                    "receipt_ids": {"type": "array", "items": {"type": "string"}},
                    "retry_after": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "review_events": {"type": "null"},
                    "human_exception": {"type": "null"},
                },
                "required": [
                    "verdict",
                    "head_sha",
                    "summary",
                    "receipt_ids",
                    "retry_after",
                    "review_events",
                    "human_exception",
                ],
                "additionalProperties": False,
            }
        ),
        encoding="utf-8",
    )
    launcher = CodexExecLauncher(tmp_path, schema, tmp_path / "context.json", adapter_path=Path(__file__).resolve().parents[2] / ".codex/agents/verification-closer.toml", runner=runner)
    session, _ = launcher.launch({"head_sha": HEAD})
    command, kwargs = calls[0]
    assert session == "01900000-0000-7000-8000-000000000010"
    assert command[:2] == ["codex", "exec"]
    assert command[2:5] == ["--json", "--sandbox", "workspace-write"]
    assert "OPENAI_API_KEY" not in kwargs["env"]
    assert "CODEX_API_KEY" not in kwargs["env"]
    resumed = launcher.command("01900000-0000-7000-8000-000000000010")
    assert resumed[:11] == command[:11]
    assert "resume" in resumed and resumed[resumed.index("resume") + 1] == "01900000-0000-7000-8000-000000000010"


def _capturing_coordinator_launcher(tmp_path: Path, calls: list[dict[str, object]]) -> CodexExecLauncher:
    class Result:
        returncode = 0
        stderr = ""
        stdout = (
            '{"type":"thread.started","thread_id":"01900000-0000-7000-8000-000000000030"}\n'
            '{"type":"item.completed","item":{"type":"agent_message","text":"{\\"verdict\\":\\"blocked\\",\\"head_sha\\":\\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\",\\"summary\\":\\"test\\",\\"receipt_ids\\":[],\\"retry_after\\":null,\\"review_events\\":null,\\"human_exception\\":null}"}}\n'
        )

    def runner(command, **kwargs):
        calls.append(kwargs)
        return Result()

    return CodexExecLauncher(
        tmp_path,
        Path(__file__).resolve().parents[2]
        / "app/dispatcher/schemas/verification_closer_receipt.schema.json",
        tmp_path / "context.json",
        adapter_path=Path(__file__).resolve().parents[2]
        / ".codex/agents/verification-closer.toml",
        runner=runner,
    )


def test_coordinator_launch_strips_ambient_host_credentials(tmp_path, monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    for key in (
        "ANTHROPIC_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "DATABASE_URL",
        "GH_TOKEN",
        "OPENAI_API_KEY",
    ):
        monkeypatch.setenv(key, "rejected-value")

    _capturing_coordinator_launcher(tmp_path, calls).launch({"head_sha": HEAD})

    child_env = calls[0]["env"]
    assert isinstance(child_env, dict)
    assert not set(child_env).intersection(
        {
            "ANTHROPIC_API_KEY",
            "AWS_SECRET_ACCESS_KEY",
            "DATABASE_URL",
            "GH_TOKEN",
            "OPENAI_API_KEY",
        }
    )


def test_coordinator_launch_uses_explicit_runtime_environment(tmp_path, monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    runtime_environment = {
        "HOME": "/non-secret/home",
        "LANG": "sv_SE.UTF-8",
        "LC_CTYPE": "UTF-8",
        "LC_MESSAGES": "sv_SE.UTF-8",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "TMPDIR": "/non-secret/tmp",
    }
    for key in verification_consumer._COORDINATOR_OPTIONAL_ENVIRONMENT:
        monkeypatch.delenv(key, raising=False)
    for key, value in runtime_environment.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("UNRELATED_SERVICE_CREDENTIAL", "rejected-value")

    _capturing_coordinator_launcher(tmp_path, calls).launch({"head_sha": HEAD})

    child_env = calls[0]["env"]
    assert isinstance(child_env, dict)
    assert {key: child_env[key] for key in runtime_environment} == runtime_environment
    assert set(child_env) == {
        *runtime_environment,
        "PKM_VERIFICATION_PROCESS_TREE",
    }


@pytest.mark.parametrize("missing_key", ["HOME", "PATH"])
def test_coordinator_launch_missing_required_environment_fails_closed(
    tmp_path, monkeypatch, missing_key
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.delenv(missing_key, raising=False)
    monkeypatch.setenv("HOST_CREDENTIAL", "rejected-value")

    with pytest.raises(
        RuntimeError,
        match="^verification coordinator required environment unavailable$",
    ):
        _capturing_coordinator_launcher(tmp_path, calls).launch({"head_sha": HEAD})

    assert calls == []


class _AuthorityLossOutput:
    def __init__(self, lines: list[str]) -> None:
        self.lines = iter(lines)
        self.reads = 0

    def __iter__(self):
        return self

    def __next__(self) -> str:
        line = next(self.lines)
        self.reads += 1
        return line


class _AuthorityLossProcess:
    def __init__(self, lines: list[str]) -> None:
        self.stdout = _AuthorityLossOutput(lines)
        self.stderr = io.StringIO("")
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls = 0

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        self.returncode = -15

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class _BlockedAuthorityLossOutput:
    def __init__(
        self, process: _IgnoringTerminateProcess, lines: list[str]
    ) -> None:
        self.process = process
        self.lines = iter(lines)
        self.reads = 0

    def __iter__(self):
        return self

    def __next__(self) -> str:
        with self.process.condition:
            while not self.process.stdout_released:
                self.process.condition.wait()
        line = next(self.lines)
        self.reads += 1
        return line


class _IgnoringTerminateProcess:
    def __init__(self, lines: list[str]) -> None:
        self.condition = Condition()
        self.stdout_released = False
        self.stdout = _BlockedAuthorityLossOutput(self, lines)
        self.stderr = io.StringIO("")
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls = 0

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9
        self.release_stdout()

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        if self.returncode is None:
            raise verification_consumer.subprocess.TimeoutExpired("codex", timeout)
        return self.returncode

    def release_stdout(self) -> None:
        with self.condition:
            self.stdout_released = True
            self.condition.notify_all()


class _DescendantHeldStdoutProcess(_IgnoringTerminateProcess):
    def __init__(self, lines: list[str]) -> None:
        super().__init__(lines)
        self.pid = 42_023
        self.descendant_alive = True
        self.group_signals: list[tuple[int, int]] = []

    def killpg(self, process_group_id: int, sig: int) -> None:
        self.group_signals.append((process_group_id, sig))
        if process_group_id != self.pid or not self.descendant_alive:
            raise ProcessLookupError(process_group_id)
        if sig == verification_consumer.signal.SIGTERM:
            # The direct parent exits, but its descendant ignores SIGTERM and
            # retains the inherited stdout pipe.
            self.returncode = -verification_consumer.signal.SIGTERM
        elif sig == verification_consumer.signal.SIGKILL:
            self.descendant_alive = False
            self.release_stdout()


class _NormalExitDescendantHeldStdoutProcess(_DescendantHeldStdoutProcess):
    def __init__(self, lines: list[str]) -> None:
        super().__init__(lines)
        self.returncode = 0

    def killpg(self, process_group_id: int, sig: int) -> None:
        self.group_signals.append((process_group_id, sig))
        if process_group_id != self.pid or not self.descendant_alive:
            raise ProcessLookupError(process_group_id)
        if sig == verification_consumer.signal.SIGKILL:
            self.descendant_alive = False
            self.release_stdout()


class _CleanExitDetachedDescendantProcess:
    def __init__(self) -> None:
        receipt = {
            "verdict": "blocked",
            "head_sha": HEAD,
            "summary": "technical stop",
            "receipt_ids": [],
            "retry_after": None,
            "review_events": None,
            "human_exception": None,
        }
        self.stdout = io.StringIO(
            json.dumps({"type": "thread.started", "thread_id": "01900000-0000-7000-8000-000000000011"})
            + "\n"
            + json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": json.dumps(receipt),
                    },
                }
            )
            + "\n"
        )
        self.stderr = io.StringIO("")
        self.returncode = 0
        self.pid = 42_024
        self.descendant_alive = True
        self.group_signals: list[tuple[int, int]] = []
        self.wait_calls = 0

    def poll(self) -> int:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        return self.returncode

    def killpg(self, process_group_id: int, sig: int) -> None:
        self.group_signals.append((process_group_id, sig))
        if process_group_id != self.pid or not self.descendant_alive:
            raise ProcessLookupError(process_group_id)
        if sig == verification_consumer.signal.SIGKILL:
            self.descendant_alive = False


class _PostSpawnOsFailureProcess:
    def __init__(self) -> None:
        private = "credential=SHOULD_NOT_PERSIST /Users/operator/private-vault"

        class Output:
            def __init__(self) -> None:
                self.index = 0

            def __iter__(self):
                return self

            def __next__(self) -> str:
                self.index += 1
                if self.index == 1:
                    return json.dumps(
                        {
                            "type": "thread.started",
                            "thread_id": "01900000-0000-7000-8000-000000000023",
                        }
                    )
                raise OSError(private)

        self.stdout = Output()
        self.stderr = io.StringIO("")
        self.returncode: int | None = None
        self.pid = 42_025
        self.descendant_alive = True
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls = 0

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9
        self.descendant_alive = False

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        if self.returncode is None:
            raise verification_consumer.subprocess.TimeoutExpired("codex", timeout)
        return self.returncode


class _ProvenContainment:
    def environment(self, base: Mapping[str, str]) -> dict[str, str]:
        return dict(base)

    def attach(self, root_pid: int) -> None:
        self.root_pid = root_pid

    def cleanup(self) -> bool:
        return True


class _EscapedDescendantContainment(_ProvenContainment):
    def __init__(self, process: _CleanExitDetachedDescendantProcess, *, proven: bool) -> None:
        self.process = process
        self.proven = proven
        self.cleanup_calls = 0

    def cleanup(self) -> bool:
        self.cleanup_calls += 1
        self.process.descendant_alive = False
        return self.proven


class _FailingContainment(_ProvenContainment):
    def __init__(self, *, fail_at: str) -> None:
        self.fail_at = fail_at

    def attach(self, root_pid: int) -> None:
        if self.fail_at == "attach":
            raise PermissionError(
                "credential=SHOULD_NOT_PERSIST /Users/operator/private-vault"
            )
        super().attach(root_pid)

    def cleanup(self) -> bool:
        if self.fail_at == "cleanup":
            raise PermissionError(
                "credential=SHOULD_NOT_PERSIST /Users/operator/private-vault"
            )
        return True


def _authority_loss_launcher(
    tmp_path: Path,
    containment_factory: Callable[[], verification_consumer.WholeTreeContainment]
    | None = None,
    cleanup_tracker_factory: Callable[
        [], verification_consumer.WholeTreeContainment
    ]
    | None = None,
) -> CodexExecLauncher:
    return CodexExecLauncher(
        tmp_path,
        Path(__file__).resolve().parents[2]
        / "app/dispatcher/schemas/verification_closer_receipt.schema.json",
        tmp_path / "context.json",
        adapter_path=Path(__file__).resolve().parents[2]
        / ".codex/agents/verification-closer.toml",
        containment_factory=containment_factory or _ProvenContainment,
        cleanup_tracker_factory=(
            cleanup_tracker_factory or verification_consumer.TaggedProcessTreeCleanup
        ),
    )


def _late_terminal_lines() -> list[str]:
    receipt = {
        "verdict": "needs_human",
        "head_sha": HEAD,
        "summary": "must not be accepted after authority loss",
        "receipt_ids": [],
        "retry_after": None,
        "review_events": None,
    }
    return [
        json.dumps({"type": "thread.started", "thread_id": "01900000-0000-7000-8000-000000000012"}) + "\n",
        json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": json.dumps(receipt)},
            }
        )
        + "\n",
    ]


def test_heartbeat_authority_loss_terminates_codex_child(tmp_path, monkeypatch) -> None:
    process = _AuthorityLossProcess(_late_terminal_lines())
    monkeypatch.setattr(verification_consumer.subprocess, "Popen", lambda *args, **kwargs: process)

    def lose_authority() -> None:
        raise RuntimeError("verification lease heartbeat rejected")

    with pytest.raises(CodexExecFailure) as exc_info:
        _authority_loss_launcher(tmp_path).launch(
            {"head_sha": HEAD}, on_heartbeat=lose_authority
        )

    assert exc_info.value.receipt["outcome"] == "heartbeat_authority_lost"
    assert process.terminate_calls == 1
    assert process.wait_calls >= 1
    assert process.poll() is not None


def _background_authority_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[_IgnoringTerminateProcess, CodexExecFailure]:
    process = _IgnoringTerminateProcess(_late_terminal_lines())
    monkeypatch.setattr(
        verification_consumer.subprocess, "Popen", lambda *args, **kwargs: process
    )
    event_wait = verification_consumer.threading.Event.wait

    def accelerated_wait(event, timeout=None):
        if timeout is not None:
            timeout = min(timeout, 0.01)
        return event_wait(event, timeout)

    monkeypatch.setattr(
        verification_consumer.threading.Event, "wait", accelerated_wait
    )
    outcome: dict[str, BaseException] = {}

    def launch() -> None:
        try:
            _authority_loss_launcher(tmp_path).launch(
                {"head_sha": HEAD},
                on_heartbeat=lambda: (_ for _ in ()).throw(
                    RuntimeError("verification lease heartbeat rejected")
                ),
            )
        except BaseException as exc:  # noqa: BLE001 - asserted thread outcome
            outcome["error"] = exc

    worker = Thread(target=launch, daemon=True)
    worker.start()
    try:
        worker.join(timeout=0.5)
        assert not worker.is_alive(), {
            "launcher_still_blocked": True,
            "terminate_calls": process.terminate_calls,
            "wait_calls": process.wait_calls,
        }
    finally:
        process.release_stdout()
        worker.join(timeout=1)

    error = outcome.get("error")
    assert isinstance(error, CodexExecFailure), outcome
    return process, error


def test_background_heartbeat_authority_loss_kills_blocked_codex_child(
    tmp_path, monkeypatch
) -> None:
    process, error = _background_authority_loss(tmp_path, monkeypatch)

    assert error.receipt["outcome"] == "heartbeat_authority_lost"
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert process.wait_calls >= 2
    assert process.poll() == -9


def test_background_authority_loss_rejects_late_stdout(
    tmp_path, monkeypatch
) -> None:
    process, error = _background_authority_loss(tmp_path, monkeypatch)

    assert error.receipt["session_id"] is None
    assert process.stdout.reads == 1


def _process_group_authority_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[_DescendantHeldStdoutProcess, CodexExecFailure, dict[str, object]]:
    process = _DescendantHeldStdoutProcess(_late_terminal_lines())
    popen_kwargs: dict[str, object] = {}

    def popen(*args, **kwargs):
        popen_kwargs.update(kwargs)
        return process

    monkeypatch.setattr(verification_consumer.subprocess, "Popen", popen)
    monkeypatch.setattr(verification_consumer.os, "killpg", process.killpg)
    event_wait = verification_consumer.threading.Event.wait

    def accelerated_wait(event, timeout=None):
        if timeout is not None:
            timeout = min(timeout, 0.01)
        return event_wait(event, timeout)

    monkeypatch.setattr(
        verification_consumer.threading.Event, "wait", accelerated_wait
    )
    outcome: dict[str, BaseException] = {}

    def launch() -> None:
        try:
            _authority_loss_launcher(tmp_path).launch(
                {"head_sha": HEAD},
                on_heartbeat=lambda: (_ for _ in ()).throw(
                    RuntimeError("verification lease heartbeat rejected")
                ),
            )
        except BaseException as exc:  # noqa: BLE001 - asserted thread outcome
            outcome["error"] = exc

    worker = Thread(target=launch, daemon=True)
    worker.start()
    try:
        worker.join(timeout=0.5)
        assert not worker.is_alive(), {
            "launcher_still_blocked": True,
            "group_signals": process.group_signals,
            "parent_returncode": process.returncode,
            "wait_calls": process.wait_calls,
        }
    finally:
        process.release_stdout()
        worker.join(timeout=1)

    error = outcome.get("error")
    assert isinstance(error, CodexExecFailure), outcome
    return process, error, popen_kwargs


def test_authority_loss_terminates_process_group_when_descendant_holds_stdout(
    tmp_path, monkeypatch
) -> None:
    process, error, popen_kwargs = _process_group_authority_loss(
        tmp_path, monkeypatch
    )

    assert error.receipt["outcome"] == "heartbeat_authority_lost"
    assert popen_kwargs["start_new_session"] is True
    assert process.returncode == -verification_consumer.signal.SIGTERM
    assert not process.descendant_alive


def test_authority_loss_kills_only_coordinator_process_group(
    tmp_path, monkeypatch
) -> None:
    process, _, _ = _process_group_authority_loss(tmp_path, monkeypatch)

    assert process.group_signals == [
        (process.pid, verification_consumer.signal.SIGTERM),
        (process.pid, 0),
        (process.pid, verification_consumer.signal.SIGKILL),
    ]


def test_process_group_authority_loss_rejects_late_descendant_output(
    tmp_path, monkeypatch
) -> None:
    process, error, _ = _process_group_authority_loss(tmp_path, monkeypatch)

    assert error.receipt["session_id"] is None
    assert process.stdout.reads == 1


def _normal_parent_exit_with_descendant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[_NormalExitDescendantHeldStdoutProcess, CodexExecFailure, list[int]]:
    process = _NormalExitDescendantHeldStdoutProcess(_late_terminal_lines())
    monkeypatch.setattr(
        verification_consumer.subprocess, "Popen", lambda *args, **kwargs: process
    )
    monkeypatch.setattr(verification_consumer.os, "killpg", process.killpg)
    event_wait = verification_consumer.threading.Event.wait

    def accelerated_wait(event, timeout=None):
        if timeout is not None:
            timeout = min(timeout, 0.01)
        return event_wait(event, timeout)

    monkeypatch.setattr(
        verification_consumer.threading.Event, "wait", accelerated_wait
    )
    heartbeat_counts: list[int] = []
    outcome: dict[str, BaseException] = {}

    def launch() -> None:
        try:
            _authority_loss_launcher(tmp_path).launch(
                {"head_sha": HEAD},
                on_heartbeat=lambda: heartbeat_counts.append(len(heartbeat_counts) + 1),
            )
        except BaseException as exc:  # noqa: BLE001 - asserted thread outcome
            outcome["error"] = exc

    worker = Thread(target=launch, daemon=True)
    worker.start()
    try:
        worker.join(timeout=0.5)
        assert not worker.is_alive(), {
            "launcher_still_blocked": True,
            "heartbeats": len(heartbeat_counts),
            "group_signals": process.group_signals,
        }
    finally:
        if worker.is_alive():
            process.release_stdout()
            worker.join(timeout=1)
    error = outcome.get("error")
    assert isinstance(error, CodexExecFailure), outcome
    return process, error, heartbeat_counts


def test_parent_exit_with_descendant_stdout_stops_heartbeat_and_reaps_group(
    tmp_path, monkeypatch
) -> None:
    process, error, heartbeat_counts = _normal_parent_exit_with_descendant(
        tmp_path, monkeypatch
    )

    stopped_at = len(heartbeat_counts)
    verification_consumer.threading.Event().wait(0.05)
    assert len(heartbeat_counts) == stopped_at
    assert error.receipt["outcome"] == "parent_exit_authority_lost"
    assert not process.descendant_alive
    assert process.group_signals == [
        (process.pid, verification_consumer.signal.SIGTERM),
        (process.pid, 0),
        (process.pid, verification_consumer.signal.SIGKILL),
    ]


def test_parent_exit_rejects_late_descendant_stdout(tmp_path, monkeypatch) -> None:
    process, error, _ = _normal_parent_exit_with_descendant(tmp_path, monkeypatch)

    assert error.receipt["session_id"] is None
    assert process.stdout.reads == 1


def _clean_parent_exit_with_detached_descendant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[_CleanExitDetachedDescendantProcess, Mapping[str, object]]:
    process = _CleanExitDetachedDescendantProcess()
    monkeypatch.setattr(
        verification_consumer.subprocess, "Popen", lambda *args, **kwargs: process
    )
    monkeypatch.setattr(verification_consumer.os, "killpg", process.killpg)

    session_id, receipt = _authority_loss_launcher(tmp_path).launch(
        {"head_sha": HEAD}
    )

    assert session_id == "01900000-0000-7000-8000-000000000011"
    return process, receipt


def test_clean_parent_exit_reaps_stdout_independent_descendant(
    tmp_path, monkeypatch
) -> None:
    process, _ = _clean_parent_exit_with_detached_descendant(tmp_path, monkeypatch)

    assert not process.descendant_alive
    assert process.group_signals == [
        (process.pid, 0),
        (process.pid, verification_consumer.signal.SIGTERM),
        (process.pid, 0),
        (process.pid, verification_consumer.signal.SIGKILL),
    ]


def test_successful_terminal_receipt_leaves_no_private_group_members(
    tmp_path, monkeypatch
) -> None:
    process, receipt = _clean_parent_exit_with_detached_descendant(
        tmp_path, monkeypatch
    )

    assert receipt["verdict"] == "blocked"
    assert not process.descendant_alive
    with pytest.raises(ProcessLookupError):
        process.killpg(process.pid, 0)


def test_new_session_descendant_cannot_outlive_launcher(
    tmp_path, monkeypatch
) -> None:
    process = _CleanExitDetachedDescendantProcess()
    containment = _EscapedDescendantContainment(process, proven=True)
    monkeypatch.setattr(
        verification_consumer.subprocess, "Popen", lambda *args, **kwargs: process
    )
    # A setsid escape is absent from the original private process group.
    monkeypatch.setattr(
        verification_consumer.os,
        "killpg",
        lambda process_group_id, sig: (_ for _ in ()).throw(
            ProcessLookupError(process_group_id)
        ),
    )

    session_id, receipt = _authority_loss_launcher(
        tmp_path, containment_factory=lambda: containment
    ).launch({"head_sha": HEAD})

    assert session_id == "01900000-0000-7000-8000-000000000011"
    assert receipt["verdict"] == "blocked"
    assert not process.descendant_alive
    assert containment.cleanup_calls == 1


def test_terminal_receipt_fails_closed_without_process_tree_containment(
    tmp_path, monkeypatch
) -> None:
    process = _CleanExitDetachedDescendantProcess()
    containment = _EscapedDescendantContainment(process, proven=False)
    monkeypatch.setattr(
        verification_consumer.subprocess, "Popen", lambda *args, **kwargs: process
    )
    monkeypatch.setattr(
        verification_consumer.os,
        "killpg",
        lambda process_group_id, sig: (_ for _ in ()).throw(
            ProcessLookupError(process_group_id)
        ),
    )

    with pytest.raises(RuntimeError, match="whole-process-tree containment unavailable"):
        _authority_loss_launcher(
            tmp_path, containment_factory=lambda: containment
        ).launch({"head_sha": HEAD})

    assert not process.descendant_alive
    assert containment.cleanup_calls == 1


@pytest.mark.parametrize("fail_at", ["attach", "cleanup"])
def test_containment_adapter_failure_reaps_and_persists_only_safe_receipt(
    tmp_path,
    monkeypatch,
    fail_at: str,
) -> None:
    private = "credential=SHOULD_NOT_PERSIST /Users/operator/private-vault"
    process = _CleanExitDetachedDescendantProcess()
    tracker = _EscapedDescendantContainment(process, proven=False)
    monkeypatch.setattr(
        verification_consumer.subprocess, "Popen", lambda *args, **kwargs: process
    )
    monkeypatch.setattr(
        verification_consumer.os,
        "killpg",
        lambda process_group_id, sig: (_ for _ in ()).throw(
            ProcessLookupError(process_group_id)
        ),
    )
    state = ledger(tmp_path)
    result = VerificationConsumer(
        state,
        Truth(eligible_pr(), GREEN),
        Auth(),
        _authority_loss_launcher(
            tmp_path,
            containment_factory=lambda: _FailingContainment(fail_at=fail_at),
            cleanup_tracker_factory=lambda: tracker,
        ),
        "host",
    ).consume(request())

    durable = json.dumps(
        {
            "attempts": state.attempts(result.run_id),
            "terminal": result.terminal_receipt,
            "status": _compact_verification_run(result),
        },
        sort_keys=True,
    )
    assert result.status == "backoff"
    assert result.claimed_by is None
    assert result.lease_id is None
    assert result.terminal_receipt["outcome"] == "launcher_contract_failed"
    assert result.terminal_receipt["error_type"] == "RuntimeError"
    assert private not in durable
    assert "PermissionError" not in durable
    assert not process.descendant_alive
    assert process.wait_calls >= 1
    assert tracker.cleanup_calls >= 1


def test_popen_os_failure_releases_lease_with_safe_status(tmp_path, monkeypatch) -> None:
    private = "credential=SHOULD_NOT_PERSIST /Users/operator/private-vault"
    monkeypatch.setattr(
        verification_consumer.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError(private)),
    )
    state = ledger(tmp_path)
    result = VerificationConsumer(
        state,
        Truth(eligible_pr(), GREEN),
        Auth(),
        _authority_loss_launcher(tmp_path),
        "host",
    ).consume(request())

    durable = json.dumps(_compact_verification_run(result), sort_keys=True)
    assert result.status == "backoff"
    assert result.claimed_by is None
    assert result.lease_id is None
    assert result.terminal_receipt["outcome"] == "launcher_contract_failed"
    assert result.terminal_receipt["error_type"] == "FileNotFoundError"
    assert private not in durable


def test_post_spawn_stream_failure_reaps_tree_and_sanitizes_status(
    tmp_path,
    monkeypatch,
) -> None:
    private = "credential=SHOULD_NOT_PERSIST /Users/operator/private-vault"
    process = _PostSpawnOsFailureProcess()
    tracker = _EscapedDescendantContainment(process, proven=False)
    monkeypatch.setattr(
        verification_consumer.subprocess, "Popen", lambda *args, **kwargs: process
    )
    monkeypatch.setattr(
        verification_consumer.os,
        "killpg",
        lambda process_group_id, sig: (_ for _ in ()).throw(
            ProcessLookupError(process_group_id)
        ),
    )
    state = ledger(tmp_path)
    result = VerificationConsumer(
        state,
        Truth(eligible_pr(), GREEN),
        Auth(),
        _authority_loss_launcher(
            tmp_path,
            cleanup_tracker_factory=lambda: tracker,
        ),
        "host",
    ).consume(request())

    durable = json.dumps(
        {
            "attempts": state.attempts(result.run_id),
            "status": _compact_verification_run(result),
        },
        sort_keys=True,
    )
    assert result.status == "backoff"
    assert result.claimed_by is None
    assert result.lease_id is None
    assert result.terminal_receipt["outcome"] == "launcher_contract_failed"
    assert result.terminal_receipt["error_type"] == "RuntimeError"
    assert private not in durable
    assert not process.descendant_alive
    assert process.kill_calls == 1
    assert process.wait_calls >= 2
    assert tracker.cleanup_calls >= 1


def test_tagged_cleanup_reaps_setsid_descendant() -> None:
    containment = verification_consumer.TaggedProcessTreeCleanup()
    root = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import os,subprocess,sys,time; "
            "time.sleep(0.05); "
            "child=subprocess.Popen([sys.executable,'-c',"
            "'import os,signal,time;os.setsid();"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)']); "
            "print(child.pid,flush=True); time.sleep(0.3)",
        ],
        env=containment.environment(os.environ),
        stdout=subprocess.PIPE,
        text=True,
    )
    assert root.stdout is not None
    containment.attach(root.pid)
    escaped_pid = int(root.stdout.readline())
    try:
        root.wait(timeout=2)
        assert escaped_pid in containment._known_pids
        assert containment.cleanup() is False
        with pytest.raises(ProcessLookupError):
            os.kill(escaped_pid, 0)
    finally:
        try:
            os.kill(escaped_pid, verification_consumer.signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_thread_start_authority_loss_terminates_codex_child(
    tmp_path, monkeypatch
) -> None:
    process = _AuthorityLossProcess(_late_terminal_lines())
    monkeypatch.setattr(
        verification_consumer.subprocess, "Popen", lambda *args, **kwargs: process
    )

    def reject_thread_start(_session_id: str) -> None:
        raise ValueError("verification start ownership mismatch")

    with pytest.raises(CodexExecFailure) as exc_info:
        _authority_loss_launcher(tmp_path).launch(
            {"head_sha": HEAD}, on_thread_started=reject_thread_start
        )

    assert exc_info.value.receipt["outcome"] == "thread_start_authority_lost"
    assert process.terminate_calls == 1
    assert process.wait_calls >= 1
    assert process.poll() is not None
    assert process.stdout.reads == 1


def test_authority_lost_child_output_is_rejected(tmp_path, monkeypatch) -> None:
    process = _AuthorityLossProcess(_late_terminal_lines())
    monkeypatch.setattr(verification_consumer.subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(CodexExecFailure, match="class=authority_loss") as exc_info:
        _authority_loss_launcher(tmp_path).launch(
            {"head_sha": HEAD},
            on_heartbeat=lambda: (_ for _ in ()).throw(RuntimeError("lease lost")),
        )

    assert exc_info.value.receipt["outcome"] == "heartbeat_authority_lost"
    assert process.stdout.reads == 1


def test_heartbeat_authority_loss_persists_one_backoff_receipt(tmp_path) -> None:
    state = ledger(tmp_path)

    class AuthorityLostLauncher(Launcher):
        def launch(
            self,
            context_pack,
            *,
            resume_session_id=None,
            on_thread_started=None,
            on_heartbeat=None,
        ):
            if on_thread_started:
                on_thread_started("01900000-0000-7000-8000-000000000012")
            with state.store._connect() as conn:
                conn.execute(
                    "UPDATE verification_runs "
                    "SET lease_expires_at='2000-01-01T00:00:00+00:00'"
                )
                conn.commit()
            raise CodexExecFailure(
                {
                    "outcome": "heartbeat_authority_lost",
                    "failure_class": "authority_loss",
                    "returncode": -15,
                    "stderr": "heartbeat authority lost",
                    "terminal_error": "ValueError: verification heartbeat ownership mismatch",
                    "session_id": "01900000-0000-7000-8000-000000000012",
                }
            )

    result = VerificationConsumer(
        state,
        Truth(eligible_pr(), GREEN),
        Auth(),
        AuthorityLostLauncher(),
        "host",
    ).consume(request())

    assert result.status == "backoff"
    assert result.terminal_receipt["outcome"] == "heartbeat_authority_lost"
    with state.store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM verification_attempts").fetchone()[0] == 0


def test_parent_exit_authority_loss_persists_one_backoff_receipt(tmp_path) -> None:
    class ParentExitedLauncher(Launcher):
        def launch(
            self,
            context_pack,
            *,
            resume_session_id=None,
            on_thread_started=None,
            on_heartbeat=None,
        ):
            raise CodexExecFailure(
                {
                    "outcome": "parent_exit_authority_lost",
                    "failure_class": "authority_loss",
                    "returncode": 0,
                    "stderr": "coordinator parent exited while stdout remained open",
                    "terminal_error": "RuntimeError: descendant retained stdout",
                    "session_id": None,
                }
            )

    result = VerificationConsumer(
        ledger(tmp_path),
        Truth(eligible_pr(), GREEN),
        Auth(),
        ParentExitedLauncher(),
        "host",
    ).consume(request())

    assert result.status == "backoff"
    assert result.terminal_receipt["outcome"] == "parent_exit_authority_lost"
    assert result.claimed_by is None
    assert result.lease_id is None


def test_schema_invalid_terminal_output_records_technical_backoff(tmp_path) -> None:
    class SchemaInvalidLauncher(Launcher):
        def launch(
            self,
            context_pack,
            *,
            resume_session_id=None,
            on_thread_started=None,
            on_heartbeat=None,
        ):
            if on_thread_started:
                on_thread_started("01900000-0000-7000-8000-000000000013")
            raise RuntimeError("codex exec produced no schema-valid final agent receipt")

    state = ledger(tmp_path)
    result = VerificationConsumer(
        state,
        Truth(eligible_pr(), GREEN),
        Auth(),
        SchemaInvalidLauncher(),
        "host",
    ).consume(request())

    assert result.status == "backoff"
    assert result.terminal_receipt["outcome"] == "launcher_contract_failed"
    assert result.terminal_receipt["reason"] == "invalid_coordinator_output"
    assert result.terminal_receipt["error_type"] == "RuntimeError"
    assert result.claimed_by is None
    assert result.lease_id is None
    with state.store._connect() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM verification_exceptions WHERE run_id=?",
                (result.run_id,),
            ).fetchone()[0]
            == 0
        )


def test_missing_terminal_output_releases_active_lease(tmp_path) -> None:
    class MissingTerminalLauncher(Launcher):
        def launch(
            self,
            context_pack,
            *,
            resume_session_id=None,
            on_thread_started=None,
            on_heartbeat=None,
        ):
            raise RuntimeError("codex exec produced no thread identity")

    result = VerificationConsumer(
        ledger(tmp_path),
        Truth(eligible_pr(), GREEN),
        Auth(),
        MissingTerminalLauncher(),
        "host",
    ).consume(request())

    assert result.status == "backoff"
    assert result.terminal_receipt["outcome"] == "launcher_contract_failed"
    assert result.claimed_by is None
    assert result.lease_id is None


def test_auth_preflight_requires_chatgpt_keyring_and_login_status(tmp_path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        'forced_login_method = "chatgpt"\ncli_auth_credentials_store = "keyring"\n',
        encoding="utf-8",
    )
    calls = []

    class Result:
        returncode = 0

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    receipt = CodexChatGPTAuthPreflight(config, runner=runner).check()
    assert receipt == AuthReceipt(True, "chatgpt", "keyring")
    assert calls[0][0] == ["codex", "login", "status"]


def test_process_runner_injection_preserves_falsey_callable(tmp_path) -> None:
    class FalseRunner:
        def __bool__(self) -> bool:
            return False

        def __call__(self, *args, **kwargs):
            raise AssertionError("the injected runner should not be called by construction")

    runner = FalseRunner()
    config = tmp_path / "config.toml"
    config.write_text(
        'forced_login_method = "chatgpt"\ncli_auth_credentials_store = "keyring"\n',
        encoding="utf-8",
    )
    launcher = CodexExecLauncher(
        tmp_path,
        tmp_path / "receipt.schema.json",
        tmp_path / "context.json",
        adapter_path=Path(__file__).resolve().parents[2] / ".codex/agents/verification-closer.toml",
        runner=runner,
    )

    assert GhCliVerificationSource(runner=runner).runner is runner
    assert CodexChatGPTAuthPreflight(config, runner=runner).runner is runner
    assert launcher.runner is runner


def test_production_receipt_schema_uses_codex_subset_and_preserves_semantics() -> None:
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "app/dispatcher/schemas/verification_closer_receipt.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    verification_consumer.validate_codex_output_schema(schema)
    assert "allOf" not in json.dumps(schema)
    assert "oneOf" not in json.dumps(schema)
    assert "uniqueItems" not in json.dumps(schema)

    valid = {
        "verdict": "delivered",
        "head_sha": HEAD,
        "summary": "verified",
        "receipt_ids": ["review-1", "review-2"],
        "retry_after": None,
        "review_events": [
            {
                "kind": "review",
                "session_id": "review-1",
                "capability": "gpt-5.6-sol",
                "reasoning_effort": "xhigh",
                "outcome": "clean",
                "finding_id": None,
                "failure_domain": None,
                "mechanism_id": None,
                "strongest": None,
            },
            {
                "kind": "review",
                "session_id": "review-2",
                "capability": "gpt-5.6-sol",
                "reasoning_effort": "xhigh",
                "outcome": "clean",
                "finding_id": None,
                "failure_domain": None,
                "mechanism_id": None,
                "strongest": None,
            },
        ],
        "human_exception": None,
    }
    verification_consumer.validate_verification_closer_receipt(valid, schema)

    without_reviews = dict(valid, review_events=None)
    with pytest.raises(jsonschema.ValidationError, match="two review events"):
        verification_consumer.validate_verification_closer_receipt(without_reviews, schema)

    repair_without_finding = dict(valid)
    repair_without_finding["review_events"] = [
        dict(valid["review_events"][0], kind="repair"),  # type: ignore[index]
        valid["review_events"][1],  # type: ignore[index]
    ]
    with pytest.raises(jsonschema.ValidationError, match="stable finding"):
        verification_consumer.validate_verification_closer_receipt(
            repair_without_finding, schema
        )


def test_codex_launcher_rejects_unsupported_schema_before_process_start(tmp_path) -> None:
    schema = tmp_path / "receipt.schema.json"
    schema.write_text(
        json.dumps(
            {
                "type": "object",
                "properties": {"verdict": {"type": "string"}},
                "required": ["verdict"],
                "additionalProperties": False,
                "allOf": [{"properties": {"verdict": {"const": "delivered"}}}],
            }
        ),
        encoding="utf-8",
    )

    calls = []

    def runner(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("invalid schema must fail before process start")

    launcher = CodexExecLauncher(
        tmp_path,
        schema,
        tmp_path / "context.json",
        adapter_path=Path(__file__).resolve().parents[2]
        / ".codex/agents/verification-closer.toml",
        runner=runner,
    )
    with pytest.raises(ValueError, match=r"unsupported output-schema keyword.*allOf"):
        launcher.launch({"head_sha": HEAD})
    assert calls == []


def test_codex_launcher_rejects_unique_items_before_process_start(tmp_path) -> None:
    schema = tmp_path / "receipt.schema.json"
    schema.write_text(
        json.dumps(
            {
                "type": "object",
                "properties": {
                    "receipt_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "uniqueItems": True,
                    }
                },
                "required": ["receipt_ids"],
                "additionalProperties": False,
            }
        ),
        encoding="utf-8",
    )

    calls = []

    def runner(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("invalid schema must fail before process start")

    launcher = CodexExecLauncher(
        tmp_path,
        schema,
        tmp_path / "context.json",
        adapter_path=Path(__file__).resolve().parents[2]
        / ".codex/agents/verification-closer.toml",
        runner=runner,
    )
    with pytest.raises(ValueError, match=r"unsupported output-schema keyword.*uniqueItems"):
        launcher.launch({"head_sha": HEAD})
    assert calls == []


def test_restart_recovers_without_duplicate_agent_or_mutation(tmp_path) -> None:
    launcher = Launcher()
    state = ledger(tmp_path)
    consumer = VerificationConsumer(state, Truth(eligible_pr(), GREEN), Auth(), launcher, "host")
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "original")
    running = state.start(run.run_id, "original", claimed.lease_id, "01900000-0000-7000-8000-000000000001", {"head_sha": HEAD})
    assert consumer.recover(running.run_id).run_id == running.run_id
    assert launcher.calls == []

    with consumer.ledger.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET lease_expires_at='2000-01-01T00:00:00+00:00' "
            "WHERE run_id=?",
            (running.run_id,),
        )
        conn.commit()
    resumed = consumer.recover(running.run_id)
    assert resumed.status == "needs_human"
    assert launcher.calls[-1][1] == "01900000-0000-7000-8000-000000000001"


def test_recovery_live_truth_error_backs_off_claimed_run(tmp_path) -> None:
    state = ledger(tmp_path)
    truth = FailingSecondReadTruth()
    launcher = Launcher()
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "original")
    running = state.start(
        run.run_id,
        "original",
        claimed.lease_id,
        "01900000-0000-7000-8000-000000000014",
        {"head_sha": HEAD},
    )
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET lease_expires_at='2000-01-01T00:00:00+00:00' "
            "WHERE run_id=?",
            (running.run_id,),
        )
        conn.commit()

    result = VerificationConsumer(
        state, truth, Auth(), launcher, "replacement"
    ).recover(running.run_id)

    assert result.status == "backoff"
    assert result.coordinator_session_id == "01900000-0000-7000-8000-000000000014"
    assert truth.pull_calls == 2
    assert launcher.calls == []


def test_recover_rejects_live_head_movement_before_resume(tmp_path) -> None:
    moved_head = "b" * 40

    class MovingTruth:
        def __init__(self) -> None:
            self.pull_calls = 0
            self.check_calls = 0

        def pull_request(self, repository, pr_number):
            self.pull_calls += 1
            return eligible_pr(head={"ref": "branch", "sha": moved_head})

        def checks(self, repository, head_sha):
            self.check_calls += 1
            raise AssertionError("stale recovery must not fetch replacement-head checks")

    class UnreachedAuth:
        def __init__(self) -> None:
            self.calls = 0

        def check(self):
            self.calls += 1
            raise AssertionError("stale recovery must not run auth preflight")

    state = ledger(tmp_path)
    launcher = Launcher()
    truth = MovingTruth()
    auth = UnreachedAuth()
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "original")
    running = state.start(
        run.run_id,
        "original",
        claimed.lease_id,
        "01900000-0000-7000-8000-000000000014",
        {"head_sha": HEAD},
    )
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET lease_expires_at='2000-01-01T00:00:00+00:00' "
            "WHERE run_id=?",
            (running.run_id,),
        )
        conn.commit()

    consumer = VerificationConsumer(state, truth, auth, launcher, "replacement")
    with pytest.raises(ValueError, match="no longer resumable: stale_head"):
        consumer.recover(running.run_id)

    current = state.get(running.run_id)
    assert current is not None
    assert current.status == "running"
    assert current.head_sha == HEAD
    assert current.coordinator_session_id == "01900000-0000-7000-8000-000000000014"
    assert truth.pull_calls == 1
    assert truth.check_calls == 0
    assert auth.calls == 0
    assert launcher.calls == []


def test_rate_limit_queues_without_api_fallback_or_duplicate(tmp_path) -> None:
    state = ledger(tmp_path)
    launcher = RateLimitedLauncher()
    queued = VerificationConsumer(
        state, Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    ).consume(request())
    assert queued.status == "backoff"
    assert queued.terminal_receipt["api_fallback"] is False
    assert state.ingest(request()).run_id == queued.run_id
    with state.store._connect() as conn:
        attempts = conn.execute(
            "SELECT attempt_kind, outcome FROM verification_attempts"
        ).fetchall()
    assert [(row[0], row[1]) for row in attempts] == [("verification", "rate_limited")]


def test_negated_rate_limit_summary_does_not_enter_rate_limit_backoff(tmp_path) -> None:
    state = ledger(tmp_path)
    result = VerificationConsumer(
        state,
        Truth(eligible_pr(), GREEN),
        Auth(),
        NegatedRateLimitLauncher(),
        "host",
    ).consume(request())

    assert result.status == "failed"
    assert result.terminal_receipt["summary"] == "[REDACTED]"
    with state.store._connect() as conn:
        attempts = conn.execute(
            "SELECT attempt_kind, outcome FROM verification_attempts"
        ).fetchall()
    assert [(row[0], row[1]) for row in attempts] == [("verification", "launched")]


def test_structured_rate_limit_receipt_replays_without_duplicate_attempt(
    tmp_path,
) -> None:
    state = ledger(tmp_path)
    launcher = RateLimitedLauncher()
    consumer = VerificationConsumer(
        state, Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    )
    first = consumer.consume(request())
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET retry_after='2000-01-01T00:00:00+00:00' "
            "WHERE run_id=?",
            (first.run_id,),
        )
        conn.commit()

    replay = consumer.consume(request())

    assert replay.status == "backoff"
    assert replay.terminal_receipt["outcome"] == "rate_limited"
    with state.store._connect() as conn:
        attempts = conn.execute(
            "SELECT attempt_kind, outcome FROM verification_attempts"
        ).fetchall()
    assert [(row[0], row[1]) for row in attempts] == [("verification", "rate_limited")]


def _nonzero_codex_launcher(tmp_path, stderr: str) -> CodexExecLauncher:
    class Result:
        returncode = 1
        stdout = '{"type":"thread.started","thread_id":"01900000-0000-7000-8000-000000000015"}\n'

        def __init__(self, failure_stderr: str) -> None:
            self.stderr = failure_stderr

    def runner(*args, **kwargs):
        return Result(stderr)

    return CodexExecLauncher(
        tmp_path,
        Path(__file__).resolve().parents[2]
        / "app/dispatcher/schemas/verification_closer_receipt.schema.json",
        tmp_path / "context.json",
        adapter_path=Path(__file__).resolve().parents[2]
        / ".codex/agents/verification-closer.toml",
        runner=runner,
    )


def _codex_json_usage_failure_launcher(
    tmp_path: Path,
    *,
    message: str,
    nested: bool = False,
    stderr: str = "",
    extra_event_fields: Mapping[str, object] | None = None,
) -> tuple[CodexExecLauncher, list[list[str]]]:
    class Result:
        returncode = 1

        def __init__(self) -> None:
            event = (
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": json.dumps({"type": "error", "message": message}),
                    },
                }
                if nested
                else {
                    "type": "error",
                    "message": message,
                    **(extra_event_fields or {}),
                }
            )
            self.stdout = "\n".join(
                (
                    json.dumps(
                        {
                            "type": "thread.started",
                            "thread_id": "01900000-0000-7000-8000-000000000017",
                        }
                    ),
                    json.dumps(event),
                    json.dumps(
                        {
                            "type": "turn.failed",
                            "error": {"message": "synthetic execution failure"},
                        }
                    ),
                )
            )
            self.stderr = stderr

    calls: list[list[str]] = []

    def runner(command: list[str], **_kwargs: object) -> Result:
        calls.append(command)
        return Result()

    launcher = CodexExecLauncher(
        tmp_path,
        Path(__file__).resolve().parents[2]
        / "app/dispatcher/schemas/verification_closer_receipt.schema.json",
        tmp_path / "context.json",
        adapter_path=Path(__file__).resolve().parents[2]
        / ".codex/agents/verification-closer.toml",
        runner=runner,
    )
    return launcher, calls


def _codex_retry_timestamp(value: datetime) -> str:
    suffix = (
        "th"
        if 11 <= value.day % 100 <= 13
        else {1: "st", 2: "nd", 3: "rd"}.get(value.day % 10, "th")
    )
    hour = value.strftime("%I").lstrip("0")
    return f"{value.strftime('%b')} {value.day}{suffix}, {value.year} {hour}:{value:%M %p}"


def _next_leap_retry() -> str:
    current = datetime.now().astimezone()
    year = current.year
    while True:
        try:
            candidate = current.replace(
                year=year, month=2, day=29, hour=11, minute=59
            )
        except ValueError:
            year += 1
            continue
        if candidate > current:
            return _codex_retry_timestamp(candidate)
        year += 1


FUTURE_CODEX_RETRY = _codex_retry_timestamp(
    datetime.now().astimezone() + timedelta(days=2)
)
PAST_CODEX_RETRY = _codex_retry_timestamp(
    datetime.now().astimezone() - timedelta(days=1)
)


def _future_single_digit_day_retry() -> str:
    candidate = datetime.now().astimezone() + timedelta(days=1)
    while candidate.day >= 10:
        candidate += timedelta(days=1)
    return _codex_retry_timestamp(candidate)


PADDED_HOUR_CODEX_RETRY = re.sub(
    r" (?P<hour>[1-9]):(?P<minute>[0-9]{2}) (?P<period>AM|PM)$",
    r" 0\g<hour>:\g<minute> \g<period>",
    _codex_retry_timestamp(
        (datetime.now().astimezone() + timedelta(days=2)).replace(hour=9)
    ),
)
PADDED_DAY_CODEX_RETRY = re.sub(
    r"^(?P<month>[A-Z][a-z]{2}) (?P<day>[1-9])(?P<suffix>st|nd|rd|th),",
    r"\g<month> 0\g<day>\g<suffix>,",
    _future_single_digit_day_retry(),
)
CANONICAL_CODEX_USAGE_LIMIT = (
    "You've hit your usage limit. Visit "
    "https://chatgpt.com/codex/settings/usage to purchase more credits "
    f"or try again at {FUTURE_CODEX_RETRY}."
)
MODEL_SPECIFIC_CODEX_USAGE_LIMIT = (
    "You've hit your usage limit for gpt-5.6-terra. "
    "Switch to another model now, or try again later."
)


@pytest.mark.parametrize(
    "message",
    [
        CANONICAL_CODEX_USAGE_LIMIT,
        "You've hit your usage limit. Try again later.",
        (
            "You've hit your usage limit. Upgrade to Pro "
            "(https://chatgpt.com/explore/pro), visit "
            "https://chatgpt.com/codex/settings/usage to purchase more credits "
            "or try again later."
        ),
        (
            "You've hit your usage limit. To get more access now, send a request "
            "to your admin or try again later."
        ),
        (
            "You've hit your usage limit. Upgrade to Plus to continue using Codex "
            "(https://chatgpt.com/explore/plus), or try again later."
        ),
        f"You've hit your usage limit. Try again at {_next_leap_retry()}.",
    ],
)
def test_codex_json_usage_limit_event_enters_durable_backoff(
    tmp_path, message: str
) -> None:
    state = ledger(tmp_path)
    launcher, calls = _codex_json_usage_failure_launcher(
        tmp_path,
        message=message,
    )

    result = VerificationConsumer(
        state, Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    ).consume(request())

    assert result.status == "backoff"
    assert result.terminal_receipt["outcome"] == "rate_limited"
    assert result.terminal_receipt["api_fallback"] is False
    assert result.terminal_receipt["failure_receipt"]["failure_class"] == "rate_limit"
    assert len(calls) == 1
    with state.store._connect() as conn:
        attempts = conn.execute(
            "SELECT attempt_kind, outcome FROM verification_attempts"
        ).fetchall()
    assert [(row[0], row[1]) for row in attempts] == [
        ("verification", "rate_limited")
    ]


@pytest.mark.parametrize(
    "message",
    [
        MODEL_SPECIFIC_CODEX_USAGE_LIMIT,
        (
            "You've hit your usage limit for codex_other. "
            f"Switch to another model now, or try again at {FUTURE_CODEX_RETRY}."
        ),
    ],
)
def test_model_specific_codex_usage_limit_event_enters_durable_backoff(
    tmp_path: Path, message: str
) -> None:
    state = ledger(tmp_path)
    launcher, calls = _codex_json_usage_failure_launcher(
        tmp_path,
        message=message,
    )

    result = VerificationConsumer(
        state, Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    ).consume(request())

    assert result.status == "backoff"
    assert result.terminal_receipt["outcome"] == "rate_limited"
    assert result.terminal_receipt["api_fallback"] is False
    assert result.terminal_receipt["failure_receipt"]["failure_class"] == "rate_limit"
    assert len(calls) == 1
    with state.store._connect() as conn:
        attempts = conn.execute(
            "SELECT attempt_kind, outcome FROM verification_attempts"
        ).fetchall()
    assert [(row[0], row[1]) for row in attempts] == [
        ("verification", "rate_limited")
    ]


@pytest.mark.parametrize(
    ("message", "nested", "stderr"),
    [
        (
            "You've hit your usage limit for codex. "
            "Switch to another model now, or try again later.",
            False,
            "",
        ),
        (
            "You've hit your usage limit for gpt 5.6. "
            "Switch to another model now, or try again later.",
            False,
            "",
        ),
        (
            "You've hit your usage limit for gpt-5.6-terra! "
            "Switch to another model now, or try again later.",
            False,
            "",
        ),
        (
            "You've hit your usage limit for gpt-5.6-terra. "
            "Switch to another model now, or try again at 99:99 PM.",
            False,
            "",
        ),
        (
            "You've hit your usage limit for gpt-5.6-terra-extra-long-"
            "identifier-that-exceeds-the-bounded-sixty-four-byte-contract. "
            "Switch to another model now, or try again later.",
            False,
            "",
        ),
        (
            "You've hit your usage limit for gpt-5.6-terra. "
            "Switch to another model now, or try again later.\" is an example.",
            False,
            "",
        ),
        (
            "You've hit your usage limit for gpt-5.6-terrа. "
            "Switch to another model now, or try again later.",
            False,
            "",
        ),
        (MODEL_SPECIFIC_CODEX_USAGE_LIMIT, True, ""),
        ("synthetic execution failure", False, MODEL_SPECIFIC_CODEX_USAGE_LIMIT),
        (
            "synthetic execution failure",
            False,
            json.dumps(
                {"type": "error", "message": MODEL_SPECIFIC_CODEX_USAGE_LIMIT}
            ),
        ),
        (
            "You've hit your usage limit. Managed plan promotion, "
            "or try again later.",
            False,
            "",
        ),
    ],
)
def test_untrusted_model_specific_usage_limit_text_cannot_mint_backoff(
    tmp_path: Path, message: str, nested: bool, stderr: str
) -> None:
    launcher, _ = _codex_json_usage_failure_launcher(
        tmp_path, message=message, nested=nested, stderr=stderr
    )

    result = VerificationConsumer(
        ledger(tmp_path), Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "codex_exec_failed"
    assert result.terminal_receipt["failure_class"] == "execution"


def test_model_specific_usage_limit_backoff_replay_is_idempotent(
    tmp_path: Path,
) -> None:
    state = ledger(tmp_path)
    launcher, calls = _codex_json_usage_failure_launcher(
        tmp_path,
        message=MODEL_SPECIFIC_CODEX_USAGE_LIMIT,
    )
    consumer = VerificationConsumer(
        state, Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    )

    first = consumer.consume(request())
    replay = consumer.consume(request())

    assert first.run_id == replay.run_id
    assert first.status == replay.status == "backoff"
    assert len(calls) == 1
    with state.store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM verification_runs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM verification_attempts").fetchone()[0] == 1


def test_model_specific_usage_limit_event_is_not_durable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    marker = "gpt-5.6-terra-private"
    message = (
        f"You've hit your usage limit for {marker}. "
        "Switch to another model now, or try again later."
    )
    state = ledger(tmp_path)
    launcher, _ = _codex_json_usage_failure_launcher(tmp_path, message=message)

    result = VerificationConsumer(
        state, Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    ).consume(request())
    captured = capsys.readouterr()
    backup = tmp_path / "dispatcher-backup.sqlite3"
    with state.store._connect() as source, sqlite3.connect(backup) as destination:
        source.backup(destination)

    durable = json.dumps(
        {
            "attempts": state.attempts(result.run_id),
            "terminal": result.terminal_receipt,
            "status": _compact_verification_run(result),
        },
        sort_keys=True,
    )
    assert marker not in durable
    assert message not in captured.out
    assert message not in captured.err
    assert marker.encode() not in state.store.db_path.read_bytes()
    assert marker.encode() not in backup.read_bytes()


def test_codex_time_only_retry_accepts_future_fall_back_fold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stockholm = ZoneInfo("Europe/Stockholm")
    current = datetime(2026, 10, 25, 2, 30, tzinfo=stockholm, fold=0)
    monkeypatch.setattr(
        verification_consumer, "_local_now", lambda: current, raising=False
    )
    launcher, _ = _codex_json_usage_failure_launcher(
        tmp_path,
        message="You've hit your usage limit. Try again at 2:15 AM.",
    )

    result = VerificationConsumer(
        ledger(tmp_path), Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    ).consume(request())

    assert result.status == "backoff"
    assert result.terminal_receipt["outcome"] == "rate_limited"


@pytest.mark.parametrize(
    ("current", "retry"),
    [
        (
            datetime(
                2026,
                10,
                25,
                2,
                0,
                tzinfo=ZoneInfo("Europe/Stockholm"),
                fold=0,
            ),
            "Oct 25th, 2026 2:45 AM",
        ),
        (
            datetime(
                2026, 3, 28, 12, 0, tzinfo=ZoneInfo("Europe/Stockholm")
            ),
            "Mar 29th, 2026 2:30 AM",
        ),
    ],
)
def test_noncanonical_or_nonexistent_local_retry_cannot_mint_backoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    current: datetime,
    retry: str,
) -> None:
    monkeypatch.setattr(verification_consumer, "_local_now", lambda: current)
    launcher, _ = _codex_json_usage_failure_launcher(
        tmp_path,
        message=f"You've hit your usage limit. Try again at {retry}.",
    )

    result = VerificationConsumer(
        ledger(tmp_path), Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    ).consume(request())

    assert result.status == "failed"
    assert result.terminal_receipt["failure_class"] == "execution"


def test_retry_timestamp_fails_closed_without_rule_bearing_local_timezone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(verification_consumer, "_local_now", lambda: None)
    launcher, _ = _codex_json_usage_failure_launcher(
        tmp_path,
        message=f"You've hit your usage limit. Try again at {FUTURE_CODEX_RETRY}.",
    )

    result = VerificationConsumer(
        ledger(tmp_path), Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "codex_exec_failed"
    assert result.terminal_receipt["failure_class"] == "execution"


def test_unrepresentable_retry_timestamp_cannot_mint_technical_backoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = datetime(
        2026, 7, 15, 12, 0, tzinfo=ZoneInfo("America/New_York")
    )
    monkeypatch.setattr(verification_consumer, "_local_now", lambda: current)
    launcher, _ = _codex_json_usage_failure_launcher(
        tmp_path,
        message=(
            "You've hit your usage limit. Try again at "
            "Dec 31st, 9999 11:59 PM."
        ),
    )

    result = VerificationConsumer(
        ledger(tmp_path), Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "codex_exec_failed"
    assert result.terminal_receipt["failure_class"] == "execution"


@pytest.mark.parametrize(
    ("message", "nested", "stderr"),
    [
        ("This is not a usage limit.", False, ""),
        ("Example: You've hit your usage limit.", False, ""),
        ("You've hit your usage limit: false", False, ""),
        ("You've hit your usage limit. false", False, ""),
        ("You've hit your usage limit! false", False, ""),
        ("You've hit your usage limit. . This is not an actual limit.", False, ""),
        ("You've hit your usage limit. Try again at 99:99 PM.", False, ""),
        ("You've hit your usage limit. Try again at 0:00 AM.", False, ""),
        ("You've hit your usage limit. Try again at 09:30 PM.", False, ""),
        (
            f"You've hit your usage limit. Try again at {PADDED_HOUR_CODEX_RETRY}.",
            False,
            "",
        ),
        (
            f"You've hit your usage limit. Try again at {PADDED_DAY_CODEX_RETRY}.",
            False,
            "",
        ),
        (f"You've hit your usage limit. Try again at {PAST_CODEX_RETRY}.", False, ""),
        ("You've hit your usage limit. Try again at Jan 1st, 2020 4:30 PM.", False, ""),
        (
            "You've hit your usage limit. Try again at Feb 99th, 0000 88:77 AM.",
            False,
            "",
        ),
        (
            "You've hit your usage limit. Try again at Jul 11st, 2026 4:30 PM.",
            False,
            "",
        ),
        (
            "You've hit your usage limit. Try again at Feb 29th, 2025 4:30 PM.",
            False,
            "",
        ),
        ("You've hit your uſage limit. Try again later.", False, ""),
        ("You've hit your usage\u00a0limit. Try again later.", False, ""),
        (
            "You've hit your usage limit. To get more acceß now, send a request "
            "to your admin or try again later.",
            False,
            "",
        ),
        (
            "You've hit your usage limit. Visit "
            "httpſ://chatgpt.com/codex/ſettingſ/uſage to purchase more credits "
            "or try again later.",
            False,
            "",
        ),
        (
            "You've hit your usage limit. Try again later.\" is only an example.",
            False,
            "",
        ),
        (CANONICAL_CODEX_USAGE_LIMIT, True, ""),
        (
            "synthetic execution failure",
            False,
            CANONICAL_CODEX_USAGE_LIMIT,
        ),
        (
            "synthetic execution failure",
            False,
            json.dumps(
                {
                    "type": "error",
                    "message": CANONICAL_CODEX_USAGE_LIMIT,
                }
            ),
        ),
    ],
)
def test_untrusted_usage_limit_text_cannot_mint_backoff(
    tmp_path: Path, message: str, nested: bool, stderr: str
) -> None:
    launcher, _ = _codex_json_usage_failure_launcher(
        tmp_path, message=message, nested=nested, stderr=stderr
    )

    result = VerificationConsumer(
        ledger(tmp_path), Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "codex_exec_failed"
    assert result.terminal_receipt["failure_class"] == "execution"


@pytest.mark.parametrize(
    "extra_event_fields",
    [
        {"usage_limit": False},
        {"source": "model"},
        {"payload": {"type": "agent_message", "usage_limit": True}},
    ],
)
def test_noncanonical_codex_usage_limit_event_envelope_cannot_mint_backoff(
    tmp_path: Path, extra_event_fields: Mapping[str, object]
) -> None:
    launcher, _ = _codex_json_usage_failure_launcher(
        tmp_path,
        message=CANONICAL_CODEX_USAGE_LIMIT,
        extra_event_fields=extra_event_fields,
    )

    result = VerificationConsumer(
        ledger(tmp_path), Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "codex_exec_failed"
    assert result.terminal_receipt["failure_class"] == "execution"


def test_codex_json_usage_limit_backoff_replay_is_idempotent(tmp_path) -> None:
    state = ledger(tmp_path)
    launcher, calls = _codex_json_usage_failure_launcher(
        tmp_path,
        message=CANONICAL_CODEX_USAGE_LIMIT,
    )
    consumer = VerificationConsumer(
        state, Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    )

    first = consumer.consume(request())
    replay = consumer.consume(request())

    assert first.run_id == replay.run_id
    assert first.status == replay.status == "backoff"
    assert len(calls) == 1
    with state.store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM verification_runs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM verification_attempts").fetchone()[0] == 1


def test_codex_json_usage_limit_event_is_not_durable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    marker = CANONICAL_CODEX_USAGE_LIMIT
    state = ledger(tmp_path)
    launcher, _ = _codex_json_usage_failure_launcher(tmp_path, message=marker)

    result = VerificationConsumer(
        state, Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    ).consume(request())
    captured = capsys.readouterr()
    backup = tmp_path / "dispatcher-backup.sqlite3"
    with state.store._connect() as source, sqlite3.connect(backup) as destination:
        source.backup(destination)

    durable = json.dumps(
        {
            "attempts": state.attempts(result.run_id),
            "terminal": result.terminal_receipt,
            "status": _compact_verification_run(result),
        },
        sort_keys=True,
    )
    assert marker not in durable
    assert marker not in captured.out
    assert marker not in captured.err
    assert marker.encode() not in state.store.db_path.read_bytes()
    assert marker.encode() not in backup.read_bytes()


def test_negated_nonzero_rate_limit_text_is_not_backoff_evidence(tmp_path) -> None:
    state = ledger(tmp_path)
    result = VerificationConsumer(
        state,
        Truth(eligible_pr(), GREEN),
        Auth(),
        _nonzero_codex_launcher(tmp_path, "this is not a rate limit"),
        "host",
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "codex_exec_failed"
    assert result.terminal_receipt["failure_class"] == "execution"
    with state.store._connect() as conn:
        attempts = conn.execute(
            "SELECT attempt_kind, outcome FROM verification_attempts"
        ).fetchall()
    assert [(row[0], row[1]) for row in attempts] == [
        ("verification", "launch_failed")
    ]


def test_contracted_negated_nonzero_rate_limit_text_is_not_backoff_evidence(
    tmp_path,
) -> None:
    result = VerificationConsumer(
        ledger(tmp_path),
        Truth(eligible_pr(), GREEN),
        Auth(),
        _nonzero_codex_launcher(
            tmp_path, "this isn't a rate limit exceeded response"
        ),
        "host",
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "codex_exec_failed"
    assert result.terminal_receipt["failure_class"] == "execution"


def test_explicit_false_rate_limit_text_is_not_backoff_evidence(tmp_path) -> None:
    result = VerificationConsumer(
        ledger(tmp_path),
        Truth(eligible_pr(), GREEN),
        Auth(),
        _nonzero_codex_launcher(tmp_path, "rate limit exceeded: false"),
        "host",
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "codex_exec_failed"
    assert result.terminal_receipt["failure_class"] == "execution"


def test_nonzero_structured_rate_limit_signal_backs_off(tmp_path) -> None:
    state = ledger(tmp_path)
    result = VerificationConsumer(
        state,
        Truth(eligible_pr(), GREEN),
        Auth(),
        _nonzero_codex_launcher(
            tmp_path,
            '{"error":{"type":"rate_limit_exceeded","status":429}}',
        ),
        "host",
    ).consume(request())

    assert result.status == "backoff"
    assert result.terminal_receipt["api_fallback"] is False
    assert result.terminal_receipt["failure_receipt"]["failure_class"] == "rate_limit"
    with state.store._connect() as conn:
        attempts = conn.execute(
            "SELECT attempt_kind, outcome FROM verification_attempts"
        ).fetchall()
    assert [(row[0], row[1]) for row in attempts] == [
        ("verification", "rate_limited")
    ]


class RawDiagnosticFailureLauncher(Launcher):
    def __init__(self, receipt: Mapping[str, object]) -> None:
        super().__init__()
        self.receipt = dict(receipt)

    def launch(self, context_pack, **kwargs):
        self.calls.append((context_pack, kwargs.get("resume_session_id")))
        if callback := kwargs.get("on_thread_started"):
            callback(str(self.receipt.get("session_id") or "01900000-0000-7000-8000-000000000016"))
        raise CodexExecFailure(self.receipt)


def test_codex_failure_receipt_redacts_stderr_before_persistence_and_status(
    tmp_path,
) -> None:
    private = "credential=SHOULD_NOT_PERSIST /Users/operator/private-vault"
    state = ledger(tmp_path)
    launcher = RawDiagnosticFailureLauncher(
        {
            "outcome": "codex_exec_failed",
            "failure_class": "execution",
            "error_type": "ghp_SHOULD_NOT_PERSIST",
            "returncode": 1,
            "stderr": private,
            "terminal_error": '{"message":"token=also-private"}',
            "session_id": "01900000-0000-7000-8000-000000000016",
        }
    )

    result = VerificationConsumer(
        state, Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    ).consume(request())

    durable = json.dumps(
        {
            "attempts": state.attempts(result.run_id),
            "terminal": result.terminal_receipt,
            "status": _compact_verification_run(result),
        },
        sort_keys=True,
    )
    assert result.status == "failed"
    assert private not in durable
    assert "token=also-private" not in durable
    assert "ghp_SHOULD_NOT_PERSIST" not in durable
    assert "stderr" not in durable
    assert "terminal_error" not in durable
    assert result.terminal_receipt == {
        "outcome": "codex_exec_failed",
        "failure_class": "execution",
        "returncode": 1,
        "session_id": "01900000-0000-7000-8000-000000000016",
    }


def test_untrusted_session_identity_never_reaches_ledger_or_status(tmp_path) -> None:
    private = "thread credential=SHOULD_NOT_PERSIST /Users/operator/private-vault"
    for token_shaped in (
        "sk-proj-SHOULD_NOT_PERSIST",
        "ghp_SHOULD_NOT_PERSIST",
    ):
        assert verification_consumer.bounded_coordinator_session_id(token_shaped) is None
        assert verification_consumer.bounded_error_type(token_shaped) is None

    class UnsafeSessionLauncher(Launcher):
        def launch(self, context_pack, **kwargs):
            if callback := kwargs.get("on_thread_started"):
                callback(private)
            raise AssertionError("unsafe session identity must stop the launcher")

    state = ledger(tmp_path)
    result = VerificationConsumer(
        state, Truth(eligible_pr(), GREEN), Auth(), UnsafeSessionLauncher(), "host"
    ).consume(request())

    assert result.status == "backoff"
    assert result.coordinator_session_id is None
    assert private not in json.dumps(_compact_verification_run(result), sort_keys=True)

    class MismatchedReturnLauncher(Launcher):
        def launch(self, context_pack, **kwargs):
            if callback := kwargs.get("on_thread_started"):
                callback("01900000-0000-7000-8000-000000000017")
            return private, {
                "verdict": "blocked",
                "head_sha": HEAD,
                "summary": "must not be recorded",
                "receipt_ids": [],
                "retry_after": None,
                "review_events": None,
                "human_exception": None,
            }

    mismatch_state = ledger(tmp_path / "mismatch")
    mismatch = VerificationConsumer(
        mismatch_state,
        Truth(eligible_pr(), GREEN),
        Auth(),
        MismatchedReturnLauncher(),
        "host",
    ).consume(request())
    assert mismatch.status == "backoff"
    assert mismatch.coordinator_session_id == "01900000-0000-7000-8000-000000000017"
    assert mismatch_state.attempts(mismatch.run_id) == []
    assert private not in json.dumps(_compact_verification_run(mismatch), sort_keys=True)

    # Status also fails closed for a legacy row written before this boundary.
    legacy_state = ledger(tmp_path / "legacy")
    ingested = legacy_state.ingest(request())
    claimed = legacy_state.claim(ingested.run_id, "legacy")
    legacy_state.start(
        ingested.run_id,
        "legacy",
        claimed.lease_id or "",
        private,
        {"head_sha": HEAD},
    )
    legacy = legacy_state.terminal(
        ingested.run_id,
        "failed",
        {
            "outcome": "codex_exec_failed",
            "failure_class": "execution",
            "error_type": "sk-proj-SHOULD_NOT_PERSIST",
            "returncode": 1,
            "session_id": private,
            "stderr": private,
            "terminal_error": private,
        },
        reason="codex_exec_failed",
        holder="legacy",
        lease_id=claimed.lease_id or "",
    )
    compact = _compact_verification_run(legacy)
    assert compact["coordinator_session_id"] is None
    assert "session_id" not in compact["terminal_receipt"]
    assert "error_type" not in compact["terminal_receipt"]
    assert private not in json.dumps(compact, sort_keys=True)


def test_redacted_nonzero_rate_limit_still_enters_bounded_backoff(tmp_path) -> None:
    private = "credential=SHOULD_NOT_PERSIST /Users/operator/private-vault"
    state = ledger(tmp_path)
    result = VerificationConsumer(
        state,
        Truth(eligible_pr(), GREEN),
        Auth(),
        _nonzero_codex_launcher(
            tmp_path,
                '{"error":{"type":"rate_limit_exceeded","status":429}}\n'
                + private,
        ),
        "host",
    ).consume(request())

    durable = json.dumps(
        {"attempts": state.attempts(result.run_id), "terminal": result.terminal_receipt},
        sort_keys=True,
    )
    assert result.status == "backoff"
    assert result.terminal_receipt["failure_receipt"]["failure_class"] == "rate_limit"
    assert result.terminal_receipt["api_fallback"] is False
    assert private not in durable
    assert "stderr" not in durable
    assert "terminal_error" not in durable


def test_authority_loss_receipt_persists_only_safe_fields(tmp_path) -> None:
    private = "RuntimeError: /Users/operator/private-vault token=SHOULD_NOT_PERSIST"
    result = VerificationConsumer(
        ledger(tmp_path),
        Truth(eligible_pr(), GREEN),
        Auth(),
        RawDiagnosticFailureLauncher(
            {
                "outcome": "heartbeat_authority_lost",
                "failure_class": "authority_loss",
                "error_type": "RuntimeError",
                "returncode": -15,
                "stderr": "heartbeat authority lost",
                "terminal_error": private,
                "session_id": "01900000-0000-7000-8000-000000000012",
            }
        ),
        "host",
    ).consume(request())

    durable = json.dumps(result.terminal_receipt, sort_keys=True)
    assert result.status == "backoff"
    assert result.terminal_receipt["failure_class"] == "authority_loss"
    assert result.terminal_receipt["error_type"] == "RuntimeError"
    assert private not in durable
    assert "stderr" not in durable
    assert "terminal_error" not in durable


def test_redacted_failure_replay_remains_deduplicated(tmp_path) -> None:
    private = "credential=SHOULD_NOT_PERSIST /Users/operator/private-vault"
    state = ledger(tmp_path)
    launcher = RawDiagnosticFailureLauncher(
        {
            "outcome": "codex_exec_failed",
            "failure_class": "execution",
            "returncode": 1,
            "stderr": private,
            "terminal_error": private,
            "session_id": "01900000-0000-7000-8000-000000000018",
        }
    )
    consumer = VerificationConsumer(
        state, Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    )

    first = consumer.consume(request())
    replay = consumer.consume(request())

    assert replay == first
    assert len(launcher.calls) == 1
    assert len(state.attempts(first.run_id)) == 1
    assert private not in json.dumps(
        {"attempts": state.attempts(first.run_id), "terminal": first.terminal_receipt},
        sort_keys=True,
    )
