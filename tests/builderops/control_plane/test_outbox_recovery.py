from __future__ import annotations

from dataclasses import replace

import pytest

from app.builderops.control_plane import (
    IdempotencyConflict,
    LeaseUnavailable,
    StaleFencingToken,
    UnknownEffectNeedsReconciliation,
)

pytestmark = pytest.mark.pg


def _expire_outbox_claim(store, repository: str, operation_key: str) -> None:
    with store._connect() as conn:
        conn.execute(
            "UPDATE builderops_outbox SET claim_expires_at = clock_timestamp() - interval '1 second' "
            "WHERE repository = %s AND operation_key = %s",
            (repository, operation_key),
        )


def _commit_outbox_task(
    store, envelope, *, task_id: str, key: str, effect_type: str, payload: dict
):
    store.commit_transition(
        envelope=envelope,
        task_id=task_id,
        to_state="ready",
        idempotency_key=f"{key}-create",
        request={"command": "create"},
    )
    _, lease = store.claim_task(
        envelope=envelope,
        task_id=task_id,
        holder="executor",
        idempotency_key=f"{key}-claim",
        request={"command": "claim"},
    )
    return store.commit_transition(
        envelope=envelope,
        task_id=task_id,
        to_state="effect_pending",
        idempotency_key=key,
        request={"command": "schedule-effect"},
        outbox={"effect_type": effect_type, "payload": payload},
        lease=lease,
    )


def test_unknown_external_effect_requires_readback_before_retry(
    control_plane_store, envelope
) -> None:
    result = _commit_outbox_task(
        control_plane_store,
        envelope,
        task_id="task-3792",
        key="unknown-effect",
        effect_type="github.merge",
        payload={"pr": 4000},
    )
    first_claim = control_plane_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="executor-1",
        claim_ttl_seconds=1,
    )
    restarted_store = type(control_plane_store)(control_plane_store.dsn)
    orphaned_claim = restarted_store.outbox_claim(envelope.repository, result.operation_key)
    assert restarted_store.outbox_status(envelope.repository, result.operation_key) == "unknown"
    assert orphaned_claim == first_claim
    assert restarted_store.effect_eligible(first_claim) is False
    with pytest.raises(StaleFencingToken):
        restarted_store.reconcile_outbox(
            replace(orphaned_claim, worker_id="wrong-holder"),
            observed_applied=False,
            evidence={"readback": "forged"},
        )
    with pytest.raises(RuntimeError, match="after_reconciliation_commit"):
        restarted_store.reconcile_outbox(
            orphaned_claim,
            observed_applied=False,
            evidence={"readback": "not-found"},
            fault_at="after_reconciliation_commit",
        )
    assert restarted_store.outbox_status(envelope.repository, result.operation_key) == "pending"
    retryable = restarted_store.reconcile_outbox(
        orphaned_claim, observed_applied=False, evidence={"readback": "not-found"}
    )
    assert retryable.replayed is True
    retry_receipt = restarted_store.receipt(envelope.repository, retryable.receipt_sequence)
    assert retry_receipt["event_type"] == "outbox.reconciled.pending"
    assert retry_receipt["lease_holder"] == orphaned_claim.worker_id
    assert retry_receipt["lease_fencing_token"] == orphaned_claim.fencing_token
    assert retry_receipt["recovery_lsn"] == retryable.recovery_lsn
    with pytest.raises(IdempotencyConflict):
        restarted_store.reconcile_outbox(
            orphaned_claim,
            observed_applied=False,
            evidence={"readback": "different"},
        )
    assert restarted_store.outbox_status(envelope.repository, result.operation_key) == "pending"
    claim = restarted_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="executor-2",
    )
    assert claim.fencing_token > first_claim.fencing_token
    assert restarted_store.effect_eligible(first_claim) is False
    with pytest.raises(StaleFencingToken):
        control_plane_store.mark_effect_unknown(first_claim, detail="late stale worker")
    restarted_store.mark_effect_unknown(claim, detail="network timeout after request")

    with pytest.raises(UnknownEffectNeedsReconciliation):
        restarted_store.claim_outbox(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="executor-2",
        )

    terminal = restarted_store.reconcile_outbox(
        claim, observed_applied=True, evidence={"merge_sha": "a" * 40}
    )
    terminal_receipt = restarted_store.receipt(envelope.repository, terminal.receipt_sequence)
    assert terminal_receipt["event_type"] == "outbox.reconciled.succeeded"
    assert terminal_receipt["lease_holder"] == claim.worker_id
    assert terminal_receipt["lease_fencing_token"] == claim.fencing_token
    assert terminal_receipt["recovery_lsn"] == terminal.recovery_lsn
    with pytest.raises(LeaseUnavailable, match="terminal"):
        restarted_store.claim_outbox(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="executor-3",
        )
    assert restarted_store.outbox_status(envelope.repository, result.operation_key) == "succeeded"


@pytest.mark.parametrize(
    "fault_at",
    [
        "after_reconciliation_receipt",
        "after_reconciliation_state",
        "after_reconciliation_record",
    ],
)
def test_reconciliation_receipt_state_and_evidence_commit_atomically(
    control_plane_store, envelope, fault_at: str
) -> None:
    result = _commit_outbox_task(
        control_plane_store,
        envelope,
        task_id=f"reconciliation-atomic-{fault_at}",
        key=f"reconciliation-atomic-{fault_at}",
        effect_type="github.merge",
        payload={"pr": 3852},
    )
    claim = control_plane_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="executor",
    )
    control_plane_store.mark_effect_unknown(claim, detail="response lost")
    receipt_count = control_plane_store.authority_counts(envelope.repository)["receipts"]

    with pytest.raises(RuntimeError, match=fault_at):
        control_plane_store.reconcile_outbox(
            claim,
            observed_applied=True,
            evidence={"readback": "found"},
            fault_at=fault_at,
        )

    assert control_plane_store.outbox_status(envelope.repository, result.operation_key) == "unknown"
    assert control_plane_store.authority_counts(envelope.repository)["receipts"] == receipt_count
    with control_plane_store._connect() as conn:
        row = conn.execute(
            "SELECT count(*) AS count FROM builderops_outbox_reconciliations "
            "WHERE repository = %s AND operation_key = %s",
            (envelope.repository, result.operation_key),
        ).fetchone()
    assert row is not None
    assert row["count"] == 0


def test_claim_crash_before_lsn_binding_is_recoverable(control_plane_store, envelope) -> None:
    result = _commit_outbox_task(
        control_plane_store,
        envelope,
        task_id="claim-binding-crash",
        key="claim-binding-crash",
        effect_type="github.merge",
        payload={"pr": 3852},
    )
    with pytest.raises(RuntimeError, match="after_claim_commit"):
        control_plane_store.claim_outbox(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="crashed-executor",
            fault_at="after_claim_commit",
        )

    recovered = type(control_plane_store)(control_plane_store.dsn)
    orphaned_claim = recovered.outbox_claim(envelope.repository, result.operation_key)
    assert orphaned_claim.claim_lsn != "0/0"
    claim_receipt = recovered.receipt(envelope.repository, orphaned_claim.receipt_sequence)
    assert claim_receipt["recovery_lsn"] == orphaned_claim.claim_lsn
    assert recovered.outbox_status(envelope.repository, result.operation_key) == "unknown"
    assert recovered.effect_eligible(orphaned_claim) is False
    reconciliation = recovered.reconcile_outbox(
        orphaned_claim,
        observed_applied=False,
        evidence={"readback": "not-found"},
    )
    with recovered._connect() as conn:
        persisted = conn.execute(
            "SELECT claim_lsn::text AS claim_lsn FROM builderops_outbox_reconciliations "
            "WHERE repository = %s AND operation_key = %s AND claim_fencing_token = %s",
            (envelope.repository, result.operation_key, orphaned_claim.fencing_token),
        ).fetchone()
    assert persisted is not None
    assert persisted["claim_lsn"] == orphaned_claim.claim_lsn
    assert reconciliation.claim_receipt_sequence == orphaned_claim.receipt_sequence
    retried = recovered.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="replacement-executor",
    )
    assert retried.fencing_token > orphaned_claim.fencing_token


def test_expired_claim_cannot_be_directly_reassigned(control_plane_store, envelope) -> None:
    result = _commit_outbox_task(
        control_plane_store,
        envelope,
        task_id="expired-claim",
        key="expired-claim",
        effect_type="github.merge",
        payload={"pr": 3852},
    )
    first = control_plane_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="expired-executor",
        claim_ttl_seconds=1,
    )
    _expire_outbox_claim(control_plane_store, envelope.repository, result.operation_key)

    with pytest.raises(UnknownEffectNeedsReconciliation):
        control_plane_store.claim_outbox(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="replacement-executor",
        )
    recovered = control_plane_store.outbox_claim(envelope.repository, result.operation_key)
    assert recovered.operation_key == first.operation_key
    assert recovered.worker_id == first.worker_id
    assert recovered.fencing_token == first.fencing_token
    assert recovered.receipt_sequence == first.receipt_sequence
    assert control_plane_store.outbox_status(envelope.repository, result.operation_key) == "unknown"
