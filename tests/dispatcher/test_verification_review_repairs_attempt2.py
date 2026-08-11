from __future__ import annotations

import sqlite3
import io
import json
import subprocess
from pathlib import Path

import pytest

from app.dispatcher import control_plane
from app.dispatcher.config import load_paths
from app.dispatcher.verification_agent_loop import VerificationAgentLoop
from app.dispatcher.verification_consumer import (
    VerificationConsumer,
    CodexExecLauncher,
    CodexExecFailure,
    live_truth_rejection,
)
from tests.dispatcher.test_verification_consumer import (
    GREEN,
    Auth,
    Launcher,
    TransitionTruth,
    Truth,
    eligible_pr,
    merged_pr,
)
from tests.dispatcher.verification_helpers import HEAD, ledger, request


class DeliveredWithReviewsLauncher(Launcher):
    def launch(
        self,
        context_pack,
        *,
        resume_session_id=None,
        on_thread_started=None,
        on_heartbeat=None,
    ):
        self.calls.append((context_pack, resume_session_id))
        session = resume_session_id or "01900000-0000-7000-8000-000000000009"
        if on_thread_started:
            on_thread_started(session)
        return session, {
            "verdict": "delivered",
            "head_sha": HEAD,
            "summary": "verified",
            "receipt_ids": ["review-1", "review-2"],
            "retry_after": None,
            "review_events": [
                {
                    "kind": "review",
                    "session_id": "review-1",
                    "capability": "gpt-5.6-terra",
                    "reasoning_effort": "high",
                    "outcome": "clean",
                    "finding_id": None,
                    "failure_domain": None,
                    "mechanism_id": None,
                    "strongest": None,
                },
                {
                    "kind": "review",
                    "session_id": "review-2",
                    "capability": "gpt-5.6-terra",
                    "reasoning_effort": "high",
                    "outcome": "clean",
                    "finding_id": None,
                    "failure_domain": None,
                    "mechanism_id": None,
                    "strongest": None,
                },
            ],
            "human_exception": None,
        }


class FailedExecLauncher(Launcher):
    def launch(
        self,
        context_pack,
        *,
        resume_session_id=None,
        on_thread_started=None,
        on_heartbeat=None,
    ):
        if on_thread_started:
            on_thread_started("01900000-0000-7000-8000-000000000019")
        raise CodexExecFailure(
            {
                "outcome": "codex_exec_failed",
                "failure_class": "execution",
                "returncode": 1,
                "stderr": "bounded diagnostic",
                "terminal_error": None,
                "session_id": "01900000-0000-7000-8000-000000000019",
            }
        )


def test_delivered_receipt_records_no_repair_reviews_and_completes(tmp_path) -> None:
    state = ledger(tmp_path)
    result = VerificationConsumer(
        state,
        TransitionTruth(merged_pr()),
        Auth(),
        DeliveredWithReviewsLauncher(),
        "host",
    ).consume(request())

    assert result.status == "completed"
    assert [row["kind"] for row in state.attempts(result.run_id)] == [
        "verification",
        "review",
        "review",
    ]


@pytest.mark.parametrize(
    ("holder", "lease_id"),
    [("intruder", "wrong-token"), ("real-owner", "stale-token")],
)
def test_stop_cannot_borrow_live_owner_lease(tmp_path, holder, lease_id) -> None:
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "real-owner")
    state.start(
        run.run_id,
        "real-owner",
        claimed.lease_id,
        "01900000-0000-7000-8000-000000000009",
        {"head_sha": HEAD},
    )
    loop = VerificationAgentLoop(
        state, run.run_id, holder=holder, lease_id=lease_id
    )

    with pytest.raises(ValueError, match="ownership"):
        loop.repair(
            finding_id="F-stale",
            failure_domain="review_code_correctness",
            mechanism_id="stale-repair",
            session_id="stale-repair",
            capability="gpt-5.6-terra",
            reasoning_effort="high",
            context={"head_sha": HEAD},
            outcome="fixed",
        )
    with pytest.raises(ValueError, match="ownership"):
        loop.stop(
            "authority-critical",
            {
                "failure_class": "authority-critical",
                "original_intent": "verify and close",
                "current_state": "authority is missing",
                "tried_actions": ["checked the governing contract"],
                "evidence": ["issue #3603"],
                "why_unsafe": "continuation would expand authority",
                "options": [
                    {"id": "hold", "label": "Hold", "consequence": "delivery waits"},
                    {
                        "id": "authorize",
                        "label": "Authorize",
                        "consequence": "delivery continues",
                    },
                ],
                "no_action_option": "hold",
                "recommended_option": "hold",
                "recommendation_rationale": "authority has not been granted",
                "consequence_of_doing_nothing": "delivery remains blocked",
            },
        )
    assert state.get(run.run_id).status == "running"  # type: ignore[union-attr]


def test_live_truth_uses_latest_check_rerun_by_name(tmp_path) -> None:
    state = ledger(tmp_path)
    run = state.ingest(request())
    checks = [
        {
            "id": 10,
            "name": "Unit tests (not pg)",
            "app": {"id": 7, "slug": "github-actions"},
            "check_suite": {"id": 10},
            "workflow_run": {
                "id": 110,
                "workflow_id": 198962230,
                "path": ".github/workflows/ci-smoke.yaml",
                "event": "pull_request",
                "head_sha": HEAD,
                "check_suite_id": 10,
            },
            "status": "completed",
            "conclusion": "failure",
        },
        {
            "id": 11,
            "name": "Unit tests (not pg)",
            "app": {"id": 7, "slug": "github-actions"},
            "check_suite": {"id": 11},
            "workflow_run": {
                "id": 111,
                "workflow_id": 198962230,
                "path": ".github/workflows/ci-smoke.yaml",
                "event": "pull_request",
                "head_sha": HEAD,
                "check_suite_id": 11,
            },
            "status": "completed",
            "conclusion": "success",
        },
    ]

    assert live_truth_rejection(run, eligible_pr(), checks) is None


def test_v3_health_and_backup_reject_missing_verification_audit_table(tmp_path) -> None:
    paths = load_paths({"DISPATCHER_STATE_DIR": str(tmp_path / "state")})
    state = ledger(paths.state_dir)
    paths = load_paths({"DISPATCHER_STATE_DIR": str(paths.state_dir)})
    paths.events_path.touch()
    # The helper uses dispatcher.sqlite3 under its argument, matching the control-plane path.
    assert state.store.db_path == paths.db_path
    with sqlite3.connect(paths.db_path) as conn:
        conn.execute("DROP TABLE verification_attempts")

    proof = control_plane.health(paths)
    assert proof["ok"] is False
    assert "verification_attempts" in proof["db"]["error"]
    with pytest.raises(ValueError, match="unsafe"):
        control_plane.backup(paths, tmp_path / "backup")


def test_codex_nonzero_exit_drains_stderr_and_rejects_valid_receipt(
    tmp_path, monkeypatch
) -> None:
    class Stderr(io.StringIO):
        drained = False

        def read(self, *args, **kwargs):
            self.drained = True
            return super().read(*args, **kwargs)

    stderr = Stderr("diagnostic\n" * 1000)
    receipt = {
        "verdict": "delivered",
        "head_sha": HEAD,
        "summary": "must not be accepted",
        "receipt_ids": [],
        "review_events": [],
    }

    class Process:
        stdout = iter(
            [
                json.dumps({"type": "thread.started", "thread_id": "01900000-0000-7000-8000-000000000010"}) + "\n",
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": json.dumps(receipt)},
                    }
                )
                + "\n",
            ]
        )
        returncode = 1

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            assert timeout == 0.25, "terminal wait must remain bounded"
            assert stderr.drained, "stderr must be drained before waiting"
            return self.returncode

    process = Process()
    process.stderr = stderr
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)

    class ProvenContainment:
        def environment(self, base):
            return dict(base)

        def attach(self, root_pid):
            return None

        def cleanup(self):
            return True

    root = Path(__file__).resolve().parents[2]
    launcher = CodexExecLauncher(
        tmp_path,
        root / "app/dispatcher/schemas/verification_closer_receipt.schema.json",
        tmp_path / "context.json",
        adapter_path=root / ".codex/agents/verification-closer.toml",
        containment_factory=ProvenContainment,
    )

    with pytest.raises(CodexExecFailure, match="class=execution") as exc_info:
        launcher.launch({"head_sha": HEAD})
    assert str(exc_info.value.receipt["stderr"]).startswith("diagnostic")


def test_consumer_persists_sanitized_codex_failure_receipt(tmp_path) -> None:
    state = ledger(tmp_path)
    result = VerificationConsumer(
        state,
        Truth(eligible_pr(), GREEN),
        Auth(),
        FailedExecLauncher(),
        "host",
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "codex_exec_failed"
    assert result.terminal_receipt == {
        "outcome": "codex_exec_failed",
        "failure_class": "execution",
        "returncode": 1,
        "session_id": "01900000-0000-7000-8000-000000000019",
    }
    assert state.attempts(result.run_id)[-1]["outcome"] == "launch_failed"
