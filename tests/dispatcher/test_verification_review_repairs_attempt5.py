from __future__ import annotations

import pytest

from app.dispatcher.verification_consumer import VerificationConsumer
from app.dispatcher.verification_dispatch import VerificationDispatchLedger
from tests.dispatcher.test_verification_consumer import (
    GREEN,
    Auth,
    Launcher,
    Truth,
    merged_pr,
)
from tests.dispatcher.verification_helpers import HEAD, ledger, request


REPAIRED_HEAD = "b" * 40


def _delivered_receipt(
    head_sha: str, *, include_repair: bool = True
) -> dict[str, object]:
    repair_events: list[dict[str, object]] = []
    if include_repair:
        repair_events.append(
            {
                "kind": "repair",
                "session_id": "repair-1",
                "capability": "gpt-5.6-terra",
                "reasoning_effort": "high",
                "outcome": "fixed",
                "finding_id": "head-rebind",
                "strongest": False,
            }
        )
    return {
        "verdict": "delivered",
        "head_sha": head_sha,
        "summary": "verified and merged",
        "receipt_ids": [
            *(["repair-1"] if include_repair else []),
            "review-1",
            "review-2",
        ],
        "retry_after": None,
        "review_events": [
            *repair_events,
            {
                "kind": "review",
                "session_id": "review-1",
                "capability": "gpt-5.6-sol",
                "reasoning_effort": "xhigh",
                "outcome": "clean",
                "finding_id": None,
                "strongest": True,
            },
            {
                "kind": "review",
                "session_id": "review-2",
                "capability": "gpt-5.6-sol",
                "reasoning_effort": "xhigh",
                "outcome": "clean",
                "finding_id": None,
                "strongest": True,
            },
        ],
        "human_exception": None,
    }


def _pending_delivered_run(
    state: VerificationDispatchLedger,
    *,
    receipt: dict[str, object] | None = None,
) -> tuple[str, dict[str, object]]:
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "original-host")
    receipt = receipt or _delivered_receipt(REPAIRED_HEAD)
    state.record_attempt(
        run.run_id,
        "verification",
        "01900000-0000-7000-8000-000000000051",
        "gpt-5.6-sol",
        "xhigh",
        {"head_sha": HEAD},
        "launched",
        receipt,
        holder="original-host",
        lease_id=claimed.lease_id or "",
    )
    state.backoff(
        run.run_id,
        {
            "outcome": "blocked",
            "reason": "postlaunch_live_truth_unavailable",
            "pending_terminal_receipt": receipt,
        },
        "2000-01-01T00:00:00+00:00",
        holder="original-host",
        lease_id=claimed.lease_id or "",
    )
    return run.run_id, receipt


def test_pending_delivered_replay_rebinds_to_merged_receipt_head(tmp_path) -> None:
    state = ledger(tmp_path)
    run_id, _ = _pending_delivered_run(state)
    truth = Truth(
        merged_pr(head={"ref": "branch", "sha": REPAIRED_HEAD}),
        GREEN,
    )

    completed = VerificationConsumer(
        state, truth, Auth(), Launcher(), "replay-host"
    ).consume(request())

    assert completed.run_id == run_id
    assert completed.status == "completed"
    assert completed.requested_head_sha == HEAD
    assert completed.current_head_sha == REPAIRED_HEAD
    assert completed.verified_head_sha == REPAIRED_HEAD
    assert [row["kind"] for row in state.attempts(run_id)] == [
        "verification",
        "standard_repair",
        "review",
        "review",
    ]
    for attempt in state.attempts(run_id)[1:]:
        assert attempt["receipt"]["head_sha"] == REPAIRED_HEAD


def test_pending_delivered_replay_rejects_head_change_without_repair_event(
    tmp_path,
) -> None:
    state = ledger(tmp_path)
    run_id, _ = _pending_delivered_run(
        state,
        receipt=_delivered_receipt(REPAIRED_HEAD, include_repair=False),
    )
    truth = Truth(
        merged_pr(head={"ref": "branch", "sha": REPAIRED_HEAD}),
        GREEN,
    )

    rejected = VerificationConsumer(
        state, truth, Auth(), Launcher(), "replay-host"
    ).consume(request())

    assert rejected.run_id == run_id
    assert rejected.status == "failed"
    assert rejected.stop_reason == "receipt_head_mismatch"
    assert rejected.current_head_sha == HEAD
    assert rejected.verified_head_sha is None
    assert [row["kind"] for row in state.attempts(run_id)] == ["verification"]


def test_pending_delivered_replay_lost_lease_cannot_rebind_or_apply_events(
    tmp_path, monkeypatch
) -> None:
    state = ledger(tmp_path)
    run_id, _ = _pending_delivered_run(state)
    truth = Truth(
        merged_pr(head={"ref": "branch", "sha": REPAIRED_HEAD}),
        GREEN,
    )
    original_rebind = state.rebind_head

    def expire_then_rebind(*args, **kwargs):
        with state.store._connect() as conn:
            conn.execute(
                "UPDATE verification_runs "
                "SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE run_id=?",
                (run_id,),
            )
            conn.commit()
        return original_rebind(*args, **kwargs)

    monkeypatch.setattr(state, "rebind_head", expire_then_rebind)

    current = VerificationConsumer(
        state, truth, Auth(), Launcher(), "replay-host"
    ).consume(request())

    assert current.run_id == run_id
    assert current.status == "claimed"
    assert current.current_head_sha == HEAD
    assert current.verified_head_sha is None
    assert [row["kind"] for row in state.attempts(run_id)] == ["verification"]


def test_pending_delivered_replay_rejects_unauthorized_head_rebind(tmp_path) -> None:
    state = ledger(tmp_path)
    run_id, _ = _pending_delivered_run(state)
    truth = Truth(
        merged_pr(
            head={"ref": "branch", "sha": REPAIRED_HEAD},
            body="Governing-Issue: #9999\n\nFixes #9999",
        ),
        GREEN,
    )

    rejected = VerificationConsumer(
        state, truth, Auth(), Launcher(), "replay-host"
    ).consume(request())

    assert rejected.run_id == run_id
    assert rejected.status == "failed"
    assert rejected.stop_reason == "receipt_live_truth_governing_issue_mismatch"
    assert rejected.requested_head_sha == HEAD
    assert rejected.current_head_sha == HEAD
    assert rejected.verified_head_sha is None
    assert [row["kind"] for row in state.attempts(run_id)] == ["verification"]


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


def _superseded_exhausted_chain(
    state: VerificationDispatchLedger,
) -> str:
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "host")
    state.start(
        run.run_id,
        "host",
        claimed.lease_id or "",
        "01900000-0000-7000-8000-000000000061",
        {"head_sha": HEAD, "stale_context": True},
    )
    for ordinal in range(1, 3):
        state.record_attempt(
            run.run_id,
            "standard_repair",
            f"superseded-repair-{ordinal}",
            "gpt-5.6-terra",
            "high",
            {"head_sha": HEAD},
            "repaired",
            {"head_sha": HEAD},
            holder="host",
            lease_id=claimed.lease_id or "",
        )
    state.backoff(
        run.run_id,
        {"outcome": "deferred", "reason": "checks_not_green"},
        "2000-01-01T00:00:00+00:00",
        holder="host",
        lease_id=claimed.lease_id or "",
    )
    state.supersede_unclaimed(
        run.run_id,
        {"outcome": "noop", "reason": "stale_head"},
        reason="stale_head",
    )
    return run.run_id


def test_stale_head_superseded_chain_reopens_without_budget_reset(tmp_path) -> None:
    state = ledger(tmp_path)
    run_id = _superseded_exhausted_chain(state)

    reopened = state.ingest(request(REPAIRED_HEAD))

    assert reopened.run_id == run_id
    assert reopened.status == "queued"
    assert reopened.requested_head_sha == HEAD
    assert reopened.current_head_sha == REPAIRED_HEAD
    assert [row["kind"] for row in state.attempts(run_id)] == [
        "standard_repair",
        "standard_repair",
    ]


def test_reopened_stale_head_chain_clears_stale_execution_state(tmp_path) -> None:
    state = ledger(tmp_path)
    _superseded_exhausted_chain(state)

    reopened = state.ingest(request(REPAIRED_HEAD))

    assert reopened.requested_head_sha == HEAD
    assert reopened.current_head_sha == REPAIRED_HEAD
    assert reopened.verified_head_sha is None
    assert reopened.claimed_by is None
    assert reopened.lease_id is None
    assert reopened.lease_expires_at is None
    assert reopened.coordinator_session_id is None
    assert reopened.context_pack is None
    assert reopened.terminal_receipt is None
    assert reopened.stop_reason is None
    assert reopened.retry_after is None


def test_stale_head_superseded_chain_rejects_unrelated_authority(tmp_path) -> None:
    state = ledger(tmp_path)
    run_id = _superseded_exhausted_chain(state)
    unrelated = request(REPAIRED_HEAD)
    unrelated["linked_issue"] = 9999

    with pytest.raises(ValueError, match="governing issue mismatch"):
        state.ingest(unrelated)

    original = state.get(run_id)
    assert original is not None
    assert original.status == "superseded"
    assert original.current_head_sha == HEAD


@pytest.mark.parametrize(
    ("status", "stop_reason"),
    [
        ("failed", "technical_failure"),
        ("completed", None),
        ("needs_human", "human_exception"),
        ("superseded", "closed_unmerged_or_merged"),
    ],
)
def test_non_reopenable_terminal_chains_remain_terminal(
    tmp_path, status: str, stop_reason: str | None
) -> None:
    state = ledger(tmp_path)
    original = state.ingest(request())
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET status=?, stop_reason=?, "
            "terminal_receipt_json=? WHERE run_id=?",
            (status, stop_reason, '{"outcome":"terminal"}', original.run_id),
        )
        conn.commit()

    next_run = state.ingest(request(REPAIRED_HEAD))

    retained = state.get(original.run_id)
    assert retained is not None
    assert retained.status == status
    assert next_run.run_id != original.run_id
