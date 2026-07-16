from __future__ import annotations

from dataclasses import replace

import pytest

from app.builderops.control_plane import (
    IdempotencyConflict,
    LeaseRequired,
    RecoveryWatermark,
    StateConflict,
)

pytestmark = pytest.mark.pg


def _observed(result) -> RecoveryWatermark:
    return RecoveryWatermark(
        recovered_through=result.recovery_lsn,
        observed_receipts=frozenset(
            {(result.repository, result.receipt_sequence, result.recovery_lsn)}
        ),
    )


def test_record_attempt_and_promotion_use_atomic_idempotent_store_port(
    control_plane_store, envelope
) -> None:
    store = control_plane_store
    record = store.commit_record(
        envelope=envelope,
        record_id="learning-1",
        record_type="LearningSignal",
        state="active",
        payload={"summary": "durable"},
        idempotency_key="record-create",
    )
    assert record.object_kind == "record"
    assert store.get_record(envelope.repository, "learning-1")["state"] == "active"
    assert (
        store.replay(
            envelope.repository,
            "record-create",
            watermark=RecoveryWatermark(recovered_through=record.recovery_lsn),
        )
        is None
    )
    assert store.replay(
        envelope.repository, "record-create", watermark=_observed(record)
    ) == replace(record, replayed=True)
    assert store.commit_record(
        envelope=envelope,
        record_id="learning-1",
        record_type="LearningSignal",
        state="active",
        payload={"summary": "durable"},
        idempotency_key="record-create",
    ) == replace(record, replayed=True)
    with pytest.raises(IdempotencyConflict):
        store.commit_record(
            envelope=envelope,
            record_id="learning-1",
            record_type="LearningSignal",
            state="active",
            payload={"summary": "changed"},
            idempotency_key="record-create",
        )
    with pytest.raises(LeaseRequired):
        store.commit_record(
            envelope=envelope,
            record_id="learning-1",
            record_type="LearningSignal",
            state="processed",
            payload={"summary": "durable"},
            idempotency_key="record-update-unleased",
            expected_states=("active",),
        )
    _, record_lease = store.claim_lease(
        envelope=envelope,
        resource_id="record:learning-1",
        holder="record-worker",
        idempotency_key="record-lease-claim",
        request={"command": "claim-lease"},
    )
    processed = store.commit_record(
        envelope=envelope,
        record_id="learning-1",
        record_type="LearningSignal",
        state="processed",
        payload={"summary": "durable"},
        idempotency_key="record-update",
        lease=record_lease,
        expected_states=("active",),
    )
    assert processed.state == "processed"

    _, forged_task_lease = store.claim_lease(
        envelope=envelope,
        resource_id="missing-task",
        holder="executor",
        idempotency_key="forged-task-lease-claim",
        request={"command": "claim-lease"},
    )
    with pytest.raises(StateConflict, match="existing claimed task"):
        store.commit_attempt(
            envelope=envelope,
            task_id="missing-task",
            attempt_id="forged-attempt",
            state="running",
            payload={},
            idempotency_key="forged-attempt",
            lease=forged_task_lease,
        )

    store.commit_transition(
        envelope=envelope,
        task_id="review-task",
        to_state="ready",
        idempotency_key="attempt-task-create",
        request={"command": "create"},
    )
    _, task_lease = store.claim_task(
        envelope=envelope,
        task_id="review-task",
        holder="executor",
        idempotency_key="attempt-task-claim",
        request={"command": "claim"},
    )
    attempt = store.commit_attempt(
        envelope=envelope,
        task_id="review-task",
        attempt_id="attempt-1",
        state="running",
        payload={"head_sha": "a" * 40},
        idempotency_key="attempt-create",
        lease=task_lease,
    )
    assert attempt.object_kind == "attempt"
    assert store.get_attempt(envelope.repository, "review-task", "attempt-1")["state"] == "running"

    promotion = store.commit_promotion(
        envelope=envelope,
        promotion_id="promotion-1",
        status="pending",
        payload={"target": "github_issue"},
        idempotency_key="promotion-create",
    )
    assert promotion.object_kind == "promotion"
    assert store.get_promotion(envelope.repository, "promotion-1")["state"] == "pending"


@pytest.mark.parametrize(
    "object_kind",
    ["record", "attempt", "promotion"],
)
def test_authority_object_state_receipt_and_idempotency_commit_atomically(
    control_plane_store, envelope, object_kind: str
) -> None:
    store = control_plane_store
    before = store.authority_counts(envelope.repository)
    kwargs = {}
    if object_kind == "record":
        operation = store.commit_record
        kwargs = {
            "record_id": "atomic-record",
            "record_type": "LearningSignal",
            "state": "active",
            "payload": {"value": 1},
        }
    elif object_kind == "attempt":
        store.commit_transition(
            envelope=envelope,
            task_id="atomic-task",
            to_state="ready",
            idempotency_key="atomic-task-create",
            request={"command": "create"},
        )
        _, lease = store.claim_task(
            envelope=envelope,
            task_id="atomic-task",
            holder="executor",
            idempotency_key="atomic-task-claim",
            request={"command": "claim"},
        )
        before = store.authority_counts(envelope.repository)
        operation = store.commit_attempt
        kwargs = {
            "task_id": "atomic-task",
            "attempt_id": "atomic-attempt",
            "state": "running",
            "payload": {"value": 1},
            "lease": lease,
        }
    else:
        operation = store.commit_promotion
        kwargs = {
            "promotion_id": "atomic-promotion",
            "status": "pending",
            "payload": {"value": 1},
        }

    with pytest.raises(RuntimeError, match="after_authority_receipt"):
        operation(
            envelope=envelope,
            idempotency_key=f"atomic-{object_kind}",
            fault_at="after_authority_receipt",
            **kwargs,
        )

    after = store.authority_counts(envelope.repository)
    assert after["receipts"] == before["receipts"]
    assert after["idempotency"] == before["idempotency"]
    with store._connect() as conn:
        table = {
            "record": "builderops_records",
            "attempt": "builderops_attempts",
            "promotion": "builderops_promotions",
        }[object_kind]
        row = conn.execute(
            f"SELECT count(*) AS count FROM {table} WHERE repository = %s",  # noqa: S608
            (envelope.repository,),
        ).fetchone()
    assert row is not None
    assert row["count"] == 0


def test_promotion_identity_is_repository_namespaced(control_plane_store, envelope) -> None:
    other = replace(
        envelope,
        repository="OtherOrg/other-repo",
        source_refs=("github:issue:9999",),
    )
    first = control_plane_store.commit_promotion(
        envelope=envelope,
        promotion_id="shared-promotion",
        status="pending",
        payload={"target": "issue:1"},
        idempotency_key="shared-promotion-key",
    )
    second = control_plane_store.commit_promotion(
        envelope=other,
        promotion_id="shared-promotion",
        status="pending",
        payload={"target": "issue:2"},
        idempotency_key="shared-promotion-key",
    )
    assert first.repository != second.repository
    assert control_plane_store.get_promotion(first.repository, first.object_id)["payload"] == {
        "target": "issue:1"
    }
    assert control_plane_store.get_promotion(second.repository, second.object_id)["payload"] == {
        "target": "issue:2"
    }


def test_authority_object_response_loss_replays_one_receipted_result(
    control_plane_store, envelope
) -> None:
    with pytest.raises(RuntimeError, match="after_authority_commit"):
        control_plane_store.commit_promotion(
            envelope=envelope,
            promotion_id="response-loss-promotion",
            status="pending",
            payload={"target": "issue:3792"},
            idempotency_key="response-loss-promotion",
            fault_at="after_authority_commit",
        )

    recovered = control_plane_store.commit_promotion(
        envelope=envelope,
        promotion_id="response-loss-promotion",
        status="pending",
        payload={"target": "issue:3792"},
        idempotency_key="response-loss-promotion",
    )
    assert recovered.replayed is True
    assert recovered.recovery_lsn != "0/0"
    assert control_plane_store.authority_counts(envelope.repository)["promotions"] == 1
    assert control_plane_store.authority_counts(envelope.repository)["receipts"] == 1
