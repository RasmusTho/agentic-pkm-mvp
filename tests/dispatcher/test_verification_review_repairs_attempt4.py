from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

import pytest

from app.dispatcher.verification_dispatch import VerificationDispatchLedger
from tests.dispatcher.verification_helpers import HEAD, ledger, request


EXPIRED_AT = "2000-01-01T00:00:00+00:00"
NEW_HEAD = "b" * 40


def _expired_claim(tmp_path) -> tuple[VerificationDispatchLedger, str, str]:
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "host")
    assert claimed.lease_id is not None
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET lease_expires_at=? WHERE run_id=?",
            (EXPIRED_AT, run.run_id),
        )
        conn.commit()
    return state, run.run_id, claimed.lease_id


def test_expired_verification_lease_cannot_heartbeat_renew(tmp_path) -> None:
    state, run_id, lease_id = _expired_claim(tmp_path)

    with pytest.raises(ValueError, match="heartbeat ownership mismatch"):
        state.heartbeat(run_id, "host", lease_id)

    run = state.get(run_id)
    assert run is not None
    assert run.lease_expires_at == EXPIRED_AT


def test_expired_verification_lease_cannot_start_coordinator(tmp_path) -> None:
    state, run_id, lease_id = _expired_claim(tmp_path)

    with pytest.raises(ValueError, match="start ownership mismatch"):
        state.start(run_id, "host", lease_id, "stale-thread", {"head_sha": HEAD})

    run = state.get(run_id)
    assert run is not None
    assert run.status == "claimed"
    assert run.coordinator_session_id is None
    assert run.context_pack is None


def test_expired_verification_lease_cannot_record_attempt(tmp_path) -> None:
    state, run_id, lease_id = _expired_claim(tmp_path)

    with pytest.raises(ValueError, match="attempt ownership mismatch"):
        state.record_attempt(
            run_id,
            "verification",
            "stale-thread",
            "gpt-5.6-sol",
            "xhigh",
            {"head_sha": HEAD},
            "launched",
            holder="host",
            lease_id=lease_id,
        )

    assert state.attempts(run_id) == []


def test_expired_verification_lease_cannot_record_attempt_batch(tmp_path) -> None:
    state, run_id, lease_id = _expired_claim(tmp_path)

    def planner(
        _attempts: list[dict[str, object]],
        attempt_id: Callable[[int], str],
    ) -> Sequence[Mapping[str, object]]:
        return [
            {
                "attempt_id": attempt_id(0),
                "kind": "review",
                "ordinal": 1,
                "session_id": "stale-review",
                "capability": "gpt-5.6-sol",
                "reasoning_effort": "xhigh",
                "context_hash": "stale-context",
                "outcome": "clean",
                "receipt": {"head_sha": HEAD},
            }
        ]

    with pytest.raises(ValueError, match="event batch ownership mismatch"):
        state.record_attempt_batch(
            run_id,
            "stale-batch",
            1,
            HEAD,
            planner,
            holder="host",
            lease_id=lease_id,
        )

    assert state.attempts(run_id) == []


def test_expired_verification_lease_cannot_rebind_head(tmp_path) -> None:
    state, run_id, lease_id = _expired_claim(tmp_path)

    with pytest.raises(ValueError, match="head rebind ownership or head mismatch"):
        state.rebind_head(
            run_id,
            NEW_HEAD,
            expected_head_sha=HEAD,
            observed_repository="RasmusTho/agentic-pkm-mvp",
            observed_pr_number=3603,
            observed_head_sha=NEW_HEAD,
            holder="host",
            lease_id=lease_id,
        )

    run = state.get(run_id)
    assert run is not None
    assert run.current_head_sha == HEAD


def test_expired_verification_lease_cannot_enter_backoff(tmp_path) -> None:
    state, run_id, lease_id = _expired_claim(tmp_path)

    with pytest.raises(ValueError, match="backoff ownership mismatch"):
        state.backoff(
            run_id,
            {"outcome": "stale"},
            "2999-01-01T00:00:00+00:00",
            holder="host",
            lease_id=lease_id,
        )

    run = state.get(run_id)
    assert run is not None
    assert run.status == "claimed"
    assert run.terminal_receipt is None


def test_expired_verification_lease_cannot_terminal_run(tmp_path) -> None:
    state, run_id, lease_id = _expired_claim(tmp_path)

    with pytest.raises(ValueError, match="terminal ownership mismatch"):
        state.terminal(
            run_id,
            "failed",
            {"outcome": "stale"},
            holder="host",
            lease_id=lease_id,
        )

    run = state.get(run_id)
    assert run is not None
    assert run.status == "claimed"
    assert run.terminal_receipt is None


def test_expired_verification_lease_cannot_record_exception(tmp_path) -> None:
    state, run_id, lease_id = _expired_claim(tmp_path)

    with pytest.raises(ValueError, match="exception ownership mismatch"):
        state.exception(
            run_id,
            "autonomous-failure-critical",
            {"current_state": "stale"},
            holder="host",
            lease_id=lease_id,
        )

    with state.store._connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM verification_exceptions WHERE run_id=?",
            (run_id,),
        ).fetchone()[0]
    assert count == 0
