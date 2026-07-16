from __future__ import annotations

import pytest

from app.builderops.control_plane import DurabilityPending, RecoveryWatermark

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
    store.reconcile_outbox(claim, observed_applied=True, evidence={"readback": "found"})
    assert calls == [result.operation_key]
