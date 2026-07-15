from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.dispatcher.verification_agent_loop import VerificationAgentLoop
from app.dispatcher.verification_consumer import (
    CodexExecFailure,
    VerificationConsumer,
)
from tests.dispatcher.test_verification_consumer import (
    Auth,
    Launcher,
    eligible_pr,
    green_checks,
    merged_pr,
)
from tests.dispatcher.verification_helpers import HEAD, ledger, request


NEW_HEAD = "b" * 40
STALE_HEAD = "c" * 40


def _running_loop(tmp_path):
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "host")
    state.start(
        run.run_id,
        "host",
        claimed.lease_id,
        "01900000-0000-7000-8000-000000000022",
        {"head_sha": HEAD},
    )
    state.record_attempt(
        run.run_id,
        "verification",
        "01900000-0000-7000-8000-000000000022",
        "gpt-5.6-terra",
        "high",
        {"head_sha": HEAD},
        "launched",
        {"head_sha": HEAD},
        holder="host",
        lease_id=claimed.lease_id,
    )
    return state, run, VerificationAgentLoop(
        state,
        run.run_id,
        holder="host",
        lease_id=claimed.lease_id,
    )


def _clean_reviews() -> list[dict[str, object]]:
    return [
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
    ]


def test_review_event_batch_exact_replay_is_idempotent(tmp_path) -> None:
    state, run, loop = _running_loop(tmp_path)
    events = _clean_reviews()

    loop.apply_events(events, context={"head_sha": HEAD})
    first = state.attempts(run.run_id)
    loop.apply_events(events, context={"head_sha": HEAD})

    assert state.attempts(run.run_id) == first
    assert [row["kind"] for row in first] == ["verification", "review", "review"]


def test_review_event_batch_rolls_back_when_later_event_conflicts(tmp_path) -> None:
    state, run, loop = _running_loop(tmp_path)
    events = _clean_reviews()
    events[1]["session_id"] = "review-1"

    with pytest.raises(ValueError, match="fresh session"):
        loop.apply_events(events, context={"head_sha": HEAD})

    assert [row["kind"] for row in state.attempts(run.run_id)] == ["verification"]


class NonzeroRateLimitedLauncher(Launcher):
    def launch(
        self,
        context_pack,
        *,
        resume_session_id=None,
        on_thread_started=None,
        on_heartbeat=None,
    ):
        self.calls.append((context_pack, resume_session_id))
        if on_thread_started:
            on_thread_started("01900000-0000-7000-8000-000000000021")
        raise CodexExecFailure(
            {
                "outcome": "codex_exec_failed",
                "failure_class": "rate_limit",
                "returncode": 1,
                "stderr": "rate limit exceeded; retry after 900s",
                "terminal_error": '{"type":"error","message":"credit exhausted"}',
                "session_id": "01900000-0000-7000-8000-000000000021",
            }
        )


def test_nonzero_codex_rate_limit_uses_durable_backoff_without_duplicate(tmp_path) -> None:
    state = ledger(tmp_path)
    launcher = NonzeroRateLimitedLauncher()
    consumer = VerificationConsumer(
        state,
        StaticTruth(HEAD),
        Auth(),
        launcher,
        "host",
    )

    result = consumer.consume(request())

    assert result.status == "backoff"
    assert result.stop_reason is None
    assert result.terminal_receipt["outcome"] == "rate_limited"  # type: ignore[index]
    assert result.terminal_receipt["api_fallback"] is False  # type: ignore[index]
    assert result.retry_after is not None
    retry_at = datetime.fromisoformat(result.retry_after)
    delay = (retry_at - datetime.now(timezone.utc)).total_seconds()
    assert 890 <= delay <= 900
    assert state.attempts(result.run_id)[-1]["outcome"] == "rate_limited"

    replay = consumer.consume(request())
    assert replay.status == "backoff"
    assert len(launcher.calls) == 1


class StaticTruth:
    def __init__(self, head: str) -> None:
        self.head = head
        self.merged = False
        self.checked_heads: list[str] = []

    def pull_request(self, repository, pr_number):
        if self.merged:
            return merged_pr(head={"ref": "branch", "sha": self.head})
        return eligible_pr(head={"ref": "branch", "sha": self.head})

    def checks(self, repository, head_sha):
        self.checked_heads.append(head_sha)
        return green_checks(self.head)


class RepairedDeliveryLauncher(Launcher):
    def __init__(self, truth: StaticTruth, *, live_head: str = NEW_HEAD) -> None:
        super().__init__()
        self.truth = truth
        self.live_head = live_head

    def launch(
        self,
        context_pack,
        *,
        resume_session_id=None,
        on_thread_started=None,
        on_heartbeat=None,
    ):
        self.calls.append((context_pack, resume_session_id))
        if on_thread_started:
            on_thread_started("01900000-0000-7000-8000-000000000022")
        self.truth.head = self.live_head
        self.truth.merged = True
        return "01900000-0000-7000-8000-000000000022", {
            "verdict": "delivered",
            "head_sha": NEW_HEAD,
            "summary": "repair pushed and independently re-reviewed",
            "receipt_ids": ["repair-1", "review-1", "review-2"],
            "retry_after": None,
            "review_events": [
                {
                    "kind": "repair",
                    "session_id": "repair-1",
                    "capability": "gpt-5.6-terra",
                    "reasoning_effort": "high",
                    "outcome": "fixed",
                    "finding_id": "discussion_r3573344490",
                    "failure_domain": "review_code_correctness",
                    "mechanism_id": "discussion-repair",
                    "strongest": False,
                },
                *_clean_reviews(),
            ],
            "human_exception": None,
        }


def test_repair_rebinds_exact_live_head_and_records_two_clean_reviews(tmp_path) -> None:
    state = ledger(tmp_path)
    truth = StaticTruth(HEAD)
    result = VerificationConsumer(
        state,
        truth,
        Auth(),
        RepairedDeliveryLauncher(truth),
        "host",
    ).consume(request())

    assert result.status == "completed"
    assert result.requested_head_sha == HEAD
    assert result.head_sha == NEW_HEAD
    assert result.verified_head_sha == NEW_HEAD
    assert result.request["current_head_sha"] == HEAD
    attempts = state.attempts(result.run_id)
    assert [row["kind"] for row in attempts] == [
        "verification",
        "standard_repair",
        "review",
        "review",
    ]
    assert [row["receipt"]["head_sha"] for row in attempts[-2:]] == [
        NEW_HEAD,
        NEW_HEAD,
    ]
    assert truth.checked_heads == [HEAD, HEAD, NEW_HEAD]


def test_repair_receipt_cannot_rebind_to_non_live_head(tmp_path) -> None:
    state = ledger(tmp_path)
    truth = StaticTruth(HEAD)
    result = VerificationConsumer(
        state,
        truth,
        Auth(),
        RepairedDeliveryLauncher(truth, live_head=STALE_HEAD),
        "host",
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "receipt_head_mismatch"
    assert result.requested_head_sha == HEAD
    assert result.head_sha == HEAD
    assert result.verified_head_sha is None


def test_head_rebind_requires_the_exact_live_lease_token(tmp_path) -> None:
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "host")

    with pytest.raises(ValueError, match="ownership or head mismatch"):
        state.rebind_head(
            run.run_id,
            NEW_HEAD,
            expected_head_sha=HEAD,
            observed_repository=run.repository,
            observed_pr_number=run.pr_number,
            observed_head_sha=NEW_HEAD,
            holder="host",
            lease_id="stale-token",
        )

    current = state.get(run.run_id)
    assert current is not None
    assert current.lease_id == claimed.lease_id
    assert current.requested_head_sha == HEAD
    assert current.head_sha == HEAD
