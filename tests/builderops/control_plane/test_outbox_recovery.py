from __future__ import annotations

from dataclasses import replace

import pytest

from app.builderops.control_plane import (
    DurabilityPending,
    IdempotencyConflict,
    LeaseUnavailable,
    RecoveryWatermark,
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


def _observed_transition(result) -> RecoveryWatermark:
    assert result.operation_key is not None
    return RecoveryWatermark(
        recovered_through=result.recovery_lsn,
        observed_receipts=frozenset(
            {(result.repository, result.receipt_sequence, result.recovery_lsn)}
        ),
        observed_intents=frozenset(
            {(result.repository, result.operation_key, result.recovery_lsn)}
        ),
    )


def _observed_claim(intent: RecoveryWatermark, claim) -> RecoveryWatermark:
    return RecoveryWatermark(
        recovered_through=claim.claim_lsn,
        observed_receipts=intent.observed_receipts
        | {(claim.repository, claim.receipt_sequence, claim.claim_lsn)},
        observed_intents=intent.observed_intents,
        observed_claims=frozenset(
            {
                (
                    claim.repository,
                    claim.operation_key,
                    claim.fencing_token,
                    claim.receipt_sequence,
                    claim.claim_lsn,
                )
            }
        ),
    )


def _observed_reconciliation(prior: RecoveryWatermark, reconciliation) -> RecoveryWatermark:
    return RecoveryWatermark(
        recovered_through=reconciliation.recovery_lsn,
        observed_receipts=prior.observed_receipts
        | {
            (
                reconciliation.repository,
                reconciliation.receipt_sequence,
                reconciliation.recovery_lsn,
            )
        },
        observed_intents=prior.observed_intents,
        observed_claims=prior.observed_claims,
        observed_reconciliations=frozenset(
            {
                (
                    reconciliation.repository,
                    reconciliation.operation_key,
                    reconciliation.fencing_token,
                    reconciliation.receipt_sequence,
                    reconciliation.recovery_lsn,
                    reconciliation.status,
                )
            }
        ),
    )


def test_unknown_external_effect_requires_readback_before_retry(
    control_plane_store, envelope
) -> None:
    result = control_plane_store.commit_transition(
        envelope=envelope,
        task_id="task-3792",
        to_state="claimed",
        idempotency_key="unknown-effect",
        request={"command": "claim"},
        outbox={"effect_type": "github.merge", "payload": {"pr": 4000}},
    )
    intent_watermark = _observed_transition(result)
    first_claim = control_plane_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="executor-1",
        watermark=intent_watermark,
        claim_ttl_seconds=1,
    )
    restarted_store = type(control_plane_store)(control_plane_store.dsn)
    orphaned_claim = restarted_store.outbox_claim(envelope.repository, result.operation_key)
    assert restarted_store.outbox_status(envelope.repository, result.operation_key) == "unknown"
    assert orphaned_claim == first_claim
    assert (
        restarted_store.effect_eligible(
            first_claim,
            watermark=_observed_claim(intent_watermark, first_claim),
        )
        is False
    )
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
    with pytest.raises(DurabilityPending):
        restarted_store.claim_outbox(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="executor-2",
            watermark=intent_watermark,
        )
    retryable = restarted_store.reconcile_outbox(
        orphaned_claim, observed_applied=False, evidence={"readback": "not-found"}
    )
    assert retryable.replayed is True
    retry_receipt = restarted_store.receipt(envelope.repository, retryable.receipt_sequence)
    assert retry_receipt["event_type"] == "outbox.reconciled.pending"
    assert retry_receipt["lease_holder"] == orphaned_claim.worker_id
    assert retry_receipt["lease_fencing_token"] == orphaned_claim.fencing_token
    assert retry_receipt["recovery_lsn"] == retryable.recovery_lsn
    assert (
        RecoveryWatermark(recovered_through=retryable.recovery_lsn).covers_reconciliation(retryable)
        is False
    )
    with pytest.raises(IdempotencyConflict):
        restarted_store.reconcile_outbox(
            orphaned_claim,
            observed_applied=False,
            evidence={"readback": "different"},
        )
    claim = restarted_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="executor-2",
        watermark=_observed_reconciliation(intent_watermark, retryable),
    )
    assert claim.fencing_token > first_claim.fencing_token
    assert (
        restarted_store.effect_eligible(
            first_claim,
            watermark=_observed_claim(intent_watermark, first_claim),
        )
        is False
    )
    with pytest.raises(StaleFencingToken):
        control_plane_store.mark_effect_unknown(first_claim, detail="late stale worker")
    restarted_store.mark_effect_unknown(claim, detail="network timeout after request")

    with pytest.raises(UnknownEffectNeedsReconciliation):
        restarted_store.claim_outbox(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="executor-2",
            watermark=intent_watermark,
        )

    terminal = restarted_store.reconcile_outbox(
        claim, observed_applied=True, evidence={"merge_sha": "a" * 40}
    )
    terminal_receipt = restarted_store.receipt(envelope.repository, terminal.receipt_sequence)
    assert terminal_receipt["event_type"] == "outbox.reconciled.succeeded"
    assert terminal_receipt["lease_holder"] == claim.worker_id
    assert terminal_receipt["lease_fencing_token"] == claim.fencing_token
    assert terminal_receipt["recovery_lsn"] == terminal.recovery_lsn
    with pytest.raises(DurabilityPending):
        restarted_store.claim_outbox(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="executor-3",
            watermark=intent_watermark,
        )
    terminal_watermark = _observed_reconciliation(intent_watermark, terminal)
    with pytest.raises(LeaseUnavailable, match="terminal"):
        restarted_store.claim_outbox(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="executor-3",
            watermark=terminal_watermark,
        )
    with pytest.raises(DurabilityPending):
        restarted_store.outbox_status(envelope.repository, result.operation_key)
    assert (
        restarted_store.outbox_status(
            envelope.repository,
            result.operation_key,
            watermark=terminal_watermark,
        )
        == "succeeded"
    )


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
    result = control_plane_store.commit_transition(
        envelope=envelope,
        task_id=f"reconciliation-atomic-{fault_at}",
        to_state="merge_pending",
        idempotency_key=f"reconciliation-atomic-{fault_at}",
        request={"command": "claim"},
        outbox={"effect_type": "github.merge", "payload": {"pr": 3852}},
    )
    claim = control_plane_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="executor",
        watermark=_observed_transition(result),
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
    result = control_plane_store.commit_transition(
        envelope=envelope,
        task_id="claim-binding-crash",
        to_state="merge_pending",
        idempotency_key="claim-binding-crash",
        request={"command": "claim"},
        outbox={"effect_type": "github.merge", "payload": {"pr": 3852}},
    )
    intent_watermark = _observed_transition(result)

    with pytest.raises(RuntimeError, match="after_claim_commit"):
        control_plane_store.claim_outbox(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="crashed-executor",
            watermark=intent_watermark,
            fault_at="after_claim_commit",
        )

    recovered = type(control_plane_store)(control_plane_store.dsn)
    orphaned_claim = recovered.outbox_claim(envelope.repository, result.operation_key)
    assert orphaned_claim.claim_lsn == "0/0"
    assert recovered.outbox_status(envelope.repository, result.operation_key) == "unknown"
    assert recovered.effect_eligible(orphaned_claim, watermark=RecoveryWatermark.stalled()) is False
    retryable = recovered.reconcile_outbox(
        orphaned_claim,
        observed_applied=False,
        evidence={"readback": "not-found"},
    )
    retried = recovered.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="replacement-executor",
        watermark=_observed_reconciliation(intent_watermark, retryable),
    )
    assert retried.fencing_token > orphaned_claim.fencing_token


def test_expired_claim_cannot_be_directly_reassigned(control_plane_store, envelope) -> None:
    result = control_plane_store.commit_transition(
        envelope=envelope,
        task_id="expired-claim",
        to_state="merge_pending",
        idempotency_key="expired-claim",
        request={"command": "claim"},
        outbox={"effect_type": "github.merge", "payload": {"pr": 3852}},
    )
    intent_watermark = _observed_transition(result)
    first = control_plane_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="expired-executor",
        watermark=intent_watermark,
        claim_ttl_seconds=1,
    )
    _expire_outbox_claim(control_plane_store, envelope.repository, result.operation_key)

    with pytest.raises(UnknownEffectNeedsReconciliation):
        control_plane_store.claim_outbox(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="replacement-executor",
            watermark=intent_watermark,
        )
    recovered = control_plane_store.outbox_claim(envelope.repository, result.operation_key)
    assert recovered.operation_key == first.operation_key
    assert recovered.worker_id == first.worker_id
    assert recovered.fencing_token == first.fencing_token
    assert recovered.receipt_sequence == first.receipt_sequence
    assert control_plane_store.outbox_status(envelope.repository, result.operation_key) == "unknown"
