from __future__ import annotations

import pytest

from app.dispatcher.verification_dispatch import VerificationDispatchLedger
from tests.dispatcher.verification_helpers import HEAD, ledger, request


REPAIRED_HEAD = "b" * 40


def _record_exhausted_repair_budget(
    state: VerificationDispatchLedger,
    run_id: str,
) -> None:
    claimed = state.claim(run_id, "host")
    assert claimed.lease_id is not None
    for ordinal in range(1, 3):
        state.record_attempt(
            run_id,
            "standard_repair",
            f"repair-{ordinal}",
            "gpt-5.6-terra",
            "high",
            {"head_sha": HEAD},
            "repaired",
            {"head_sha": HEAD},
            holder="host",
            lease_id=claimed.lease_id,
        )
    state.rebind_head(
        run_id,
        REPAIRED_HEAD,
        expected_head_sha=HEAD,
        observed_repository="RasmusTho/agentic-pkm-mvp",
        observed_pr_number=3603,
        observed_head_sha=REPAIRED_HEAD,
        holder="host",
        lease_id=claimed.lease_id,
    )
    state.backoff(
        run_id,
        {"outcome": "deferred", "reason": "checks_not_green"},
        "2999-01-01T00:00:00+00:00",
        holder="host",
        lease_id=claimed.lease_id,
    )


def test_repaired_head_artifact_reuses_canonical_run_and_budget(tmp_path) -> None:
    state = ledger(tmp_path)
    original = state.ingest(request())
    _record_exhausted_repair_budget(state, original.run_id)

    redispatched = state.ingest(request(REPAIRED_HEAD))

    assert redispatched.run_id == original.run_id
    assert redispatched.requested_head_sha == HEAD
    assert redispatched.current_head_sha == REPAIRED_HEAD
    assert [
        attempt["kind"] for attempt in state.attempts(redispatched.run_id)
    ] == ["standard_repair", "standard_repair"]
    with pytest.raises(
        ValueError, match="artifact head does not match canonical run"
    ):
        state.ingest(request("c" * 40))


def test_repaired_head_artifact_cannot_merge_unrelated_authority(tmp_path) -> None:
    state = ledger(tmp_path)
    original = state.ingest(request())
    _record_exhausted_repair_budget(state, original.run_id)
    unrelated = request(REPAIRED_HEAD)
    unrelated["linked_issue"] = 9999

    with pytest.raises(ValueError, match="governing issue mismatch"):
        state.ingest(unrelated)

    same_head_state = ledger(tmp_path / "same-head")
    same_head = same_head_state.ingest(request(REPAIRED_HEAD))
    with pytest.raises(ValueError, match="governing issue mismatch"):
        same_head_state.ingest(unrelated)

    claimed = same_head_state.claim(same_head.run_id, "host")
    same_head_state.terminal(
        same_head.run_id,
        "failed",
        {"outcome": "technical_failure"},
        holder="host",
        lease_id=claimed.lease_id or "",
    )
    with pytest.raises(ValueError, match="idempotency authority conflict"):
        same_head_state.ingest(unrelated)
