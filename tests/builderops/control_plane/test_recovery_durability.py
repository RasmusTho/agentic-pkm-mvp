from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.builderops.control_plane import (
    DurabilityPending,
    OutboxClaim,
    OutboxReconciliation,
    RecoveryWatermark,
    TransactionResult,
)

pytestmark = pytest.mark.pg


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


def _observed_reconciliation(prior: RecoveryWatermark, result) -> RecoveryWatermark:
    return RecoveryWatermark(
        recovered_through=result.recovery_lsn,
        observed_receipts=prior.observed_receipts
        | {(result.repository, result.receipt_sequence, result.recovery_lsn)},
        observed_intents=prior.observed_intents,
        observed_claims=prior.observed_claims,
        observed_reconciliations=frozenset(
            {
                (
                    result.repository,
                    result.operation_key,
                    result.fencing_token,
                    result.receipt_sequence,
                    result.recovery_lsn,
                    result.status,
                )
            }
        ),
    )


def test_unbound_or_malformed_lsn_never_authorizes_exact_observed_identity() -> None:
    transition = TransactionResult("owner/repo", "task", "ready", 1, "0/0", "operation")
    claim = OutboxClaim("owner/repo", "operation", "worker", 1, "0/0", "0/0", 2, datetime.now(UTC))
    reconciliation = OutboxReconciliation(
        "owner/repo", "operation", "task", "succeeded", "worker", 1, 2, 3, "0/0"
    )
    proof = RecoveryWatermark(
        recovered_through="0/0",
        observed_receipts=frozenset(
            {("owner/repo", 1, "0/0"), ("owner/repo", 2, "0/0"), ("owner/repo", 3, "0/0")}
        ),
        observed_intents=frozenset({("owner/repo", "operation", "0/0")}),
        observed_claims=frozenset({("owner/repo", "operation", 1, 2, "0/0")}),
        observed_reconciliations=frozenset({("owner/repo", "operation", 1, 3, "0/0", "succeeded")}),
    )
    assert proof.covers_transition(transition) is False
    assert proof.covers_intent(transition) is False
    assert proof.covers_claim(claim) is False
    assert proof.covers_reconciliation(reconciliation) is False
    assert RecoveryWatermark(recovered_through="invalid").covers_transition(transition) is False
    bound = TransactionResult("owner/repo", "task", "ready", 4, "0/1", None)
    invalid_recovery = RecoveryWatermark(
        recovered_through="invalid",
        observed_receipts=frozenset({("owner/repo", 4, "0/1")}),
    )
    malformed_binding = TransactionResult("owner/repo", "task", "ready", 5, "invalid", None)
    malformed_proof = RecoveryWatermark(
        recovered_through="0/10",
        observed_receipts=frozenset({("owner/repo", 5, "invalid")}),
    )
    assert invalid_recovery.covers_transition(bound) is False
    assert malformed_proof.covers_transition(malformed_binding) is False


def test_unbound_intent_lsn_is_durability_pending(control_plane_store, envelope) -> None:
    result = control_plane_store.commit_transition(
        envelope=envelope,
        task_id="unbound-intent",
        to_state="ready",
        idempotency_key="unbound-intent",
        request={"command": "create"},
        outbox={"effect_type": "github.comment", "payload": {}},
    )
    with control_plane_store._connect() as conn:
        conn.execute(
            "UPDATE builderops_outbox SET intent_lsn = NULL "
            "WHERE repository = %s AND operation_key = %s",
            (envelope.repository, result.operation_key),
        )
    with pytest.raises(DurabilityPending, match="binding is incomplete"):
        control_plane_store.claim_outbox(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="worker",
            watermark=_observed_transition(result),
        )


def test_external_effect_waits_for_intent_and_claim_recovery_lsn(
    control_plane_store, envelope
) -> None:
    store = control_plane_store
    result = store.commit_transition(
        envelope=envelope,
        task_id="task-3792",
        to_state="claimed",
        idempotency_key="durability-gate",
        request={"command": "claim"},
        outbox={"effect_type": "github.comment", "payload": {"issue": 3792}},
    )
    calls: list[str] = []
    stalled = RecoveryWatermark.stalled()
    scalar_only = RecoveryWatermark(recovered_through=result.recovery_lsn)
    assert store.replay(envelope.repository, "durability-gate", watermark=stalled) is None
    assert store.replay(envelope.repository, "durability-gate", watermark=scalar_only) is None
    with pytest.raises(DurabilityPending):
        store.claim_outbox(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="executor",
            watermark=stalled,
        )
    with pytest.raises(DurabilityPending):
        store.claim_outbox(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="executor",
            watermark=scalar_only,
        )
    assert calls == []

    intent_watermark = _observed_transition(result)
    assert store.replay(envelope.repository, "durability-gate", watermark=intent_watermark)
    claim = store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="executor",
        watermark=intent_watermark,
    )
    claim_receipt = store.receipt(envelope.repository, claim.receipt_sequence)
    assert claim_receipt["lease_holder"] == claim.worker_id
    assert claim_receipt["lease_fencing_token"] == claim.fencing_token
    assert store.effect_eligible(claim, watermark=intent_watermark) is False
    claim_scalar_only = RecoveryWatermark(recovered_through=claim.claim_lsn)
    assert store.effect_eligible(claim, watermark=claim_scalar_only) is False
    assert calls == []
    claim_watermark = _observed_claim(intent_watermark, claim)
    assert store.effect_eligible(claim, watermark=claim_watermark) is True
    calls.append(claim.operation_key)
    store.mark_effect_unknown(claim, detail="response lost")
    reconciliation = store.reconcile_outbox(
        claim, observed_applied=True, evidence={"readback": "found"}
    )
    assert (
        RecoveryWatermark(recovered_through=reconciliation.recovery_lsn).covers_reconciliation(
            reconciliation
        )
        is False
    )
    assert _observed_reconciliation(claim_watermark, reconciliation).covers_reconciliation(
        reconciliation
    )
    assert calls == [result.operation_key]
