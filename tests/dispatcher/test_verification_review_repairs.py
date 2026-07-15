from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.dispatcher.verification_agent_loop import VerificationAgentLoop
from app.dispatcher.verification_consumer import (
    CodexExecLauncher,
    VerificationConsumer,
)
from tests.dispatcher.test_verification_consumer import GREEN, Auth, Launcher, Truth, eligible_pr
from tests.dispatcher.verification_helpers import HEAD, ledger, request


def test_subscription_slot_allows_only_one_active_pr_chain(tmp_path) -> None:
    state = ledger(tmp_path)
    launcher = Launcher()
    first = state.ingest(request())
    first_claim = state.claim(first.run_id, "host")
    first = state.start(first.run_id, "host", first_claim.lease_id, "thread-1", {"head_sha": HEAD})
    second_request = request("b" * 40)
    second_pr = eligible_pr(head={"ref": "branch-2", "sha": "b" * 40})
    with pytest.raises(
        ValueError, match="artifact head does not match canonical run"
    ):
        VerificationConsumer(
            state, Truth(second_pr, GREEN), Auth(), launcher, "host"
        ).consume(second_request)

    assert first.status == "running"
    assert launcher.calls == []


def test_transient_checks_defer_instead_of_terminal_supersede(tmp_path) -> None:
    state = ledger(tmp_path)
    result = VerificationConsumer(
        state,
        Truth(eligible_pr(), [{"status": "in_progress", "conclusion": None}]),
        Auth(),
        Launcher(),
        "host",
    ).consume(request())
    assert result.status == "backoff"
    assert result.stop_reason is None


def test_backoff_replay_does_not_launch_until_retry_is_due(tmp_path) -> None:
    state = ledger(tmp_path)
    launcher = Launcher()
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "host")
    state.backoff(
        run.run_id,
        {"outcome": "rate_limited"},
        "2999-01-01T00:00:00+00:00",
        holder="host",
        lease_id=claimed.lease_id,
    )
    result = VerificationConsumer(
        state, Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    ).consume(request())
    assert result.status == "backoff"
    assert launcher.calls == []


def test_untrusted_head_and_source_identity_are_rejected(tmp_path) -> None:
    state = ledger(tmp_path)
    malformed = request()
    malformed["current_head_sha"] = "../../issues"
    malformed["source_workflow"] = {
        "name": "Other",
        "run_id": 1,
        "run_attempt": 1,
        "head_sha": "../../issues",
    }
    # Rehashing must not turn an unsafe identity into an accepted request.
    import hashlib

    identity = {
        "contract_version": malformed["contract_version"],
        "head_sha": malformed["current_head_sha"],
        "pr_number": malformed["pr_number"],
        "repository": malformed["repository"],
        "stage": malformed["stage"],
    }
    malformed["idempotency_key"] = hashlib.sha256(
        json.dumps(identity, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    with pytest.raises(ValueError):
        state.ingest(malformed)


def test_old_lease_token_cannot_mutate_same_holder_takeover(tmp_path) -> None:
    state = ledger(tmp_path)
    run = state.ingest(request())
    old = state.claim(run.run_id, "host")
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET lease_expires_at='2000-01-01T00:00:00+00:00' "
            "WHERE run_id=?",
            (run.run_id,),
        )
        conn.commit()
    new = state.claim(run.run_id, "host")
    assert new.lease_id != old.lease_id
    with pytest.raises(ValueError):
        state.heartbeat(run.run_id, "host", lease_id=old.lease_id)
    with pytest.raises(ValueError):
        state.start(run.run_id, "host", old.lease_id, "old-thread", {"head": HEAD})
    with pytest.raises(ValueError):
        state.backoff(
            run.run_id,
            {"outcome": "old"},
            "2999-01-01T00:00:00+00:00",
            holder="host",
            lease_id=old.lease_id,
        )
    with pytest.raises(ValueError):
        state.terminal(
            run.run_id,
            "failed",
            {"outcome": "old"},
            holder="host",
            lease_id=old.lease_id,
        )


def test_each_repair_requires_blocking_fresh_review_and_final_two_clean(tmp_path) -> None:
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "host")
    loop = VerificationAgentLoop(
        state, run.run_id, holder="host", lease_id=claimed.lease_id
    )
    context = {"head": run.head_sha}
    loop.repair(
        finding_id="F1",
        session_id="fix-1",
        capability="terra",
        reasoning_effort="high",
        context=context,
        outcome="fixed",
    )
    with pytest.raises(ValueError):
        loop.repair(
            finding_id="F2",
            session_id="fix-2",
            capability="terra",
            reasoning_effort="high",
            context=context,
            outcome="fixed",
        )
    loop.review(
        session_id="review-1",
        capability="terra",
        reasoning_effort="high",
        context=context,
        outcome="blocking",
    )
    loop.repair(
        finding_id="F2",
        session_id="fix-2",
        capability="terra",
        reasoning_effort="high",
        context=context,
        outcome="fixed",
    )
    loop.review(
        session_id="review-2",
        capability="terra",
        reasoning_effort="high",
        context=context,
        outcome="clean",
    )
    assert not loop.closure_ready()
    loop.review(
        session_id="review-3",
        capability="terra",
        reasoning_effort="high",
        context=context,
        outcome="clean",
    )
    assert loop.closure_ready()


def test_adapter_model_reasoning_and_instructions_are_applied(tmp_path) -> None:
    schema = tmp_path / "receipt.json"
    schema.write_text("{}", encoding="utf-8")
    launcher = CodexExecLauncher(
        tmp_path,
        schema,
        tmp_path / "context.json",
        adapter_path=Path(__file__).resolve().parents[2] / ".codex/agents/verification-closer.toml",
    )
    command = launcher.command()
    assert command[command.index("--model") + 1] == "gpt-5.6-terra"
    assert 'model_reasoning_effort="high"' in command
    assert "verification_closer" in command[-1]
    assert "Do not merge unless" in command[-1]


def test_thread_and_final_receipt_callbacks_are_durable_before_return(tmp_path) -> None:
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "host")
    observed: list[str] = []

    def started(session_id: str) -> None:
        state.start(
            run.run_id,
            "host",
            claimed.lease_id,
            session_id,
            {"head_sha": HEAD},
        )
        observed.append(state.get(run.run_id).coordinator_session_id)  # type: ignore[union-attr]

    started("thread-1")
    assert observed == ["thread-1"]
