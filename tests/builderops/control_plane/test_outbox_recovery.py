from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.builderops.control_plane import (
    RecoveryWatermark,
    StaleFencingToken,
    UnknownEffectNeedsReconciliation,
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
    now = datetime.now(timezone.utc)
    first_claim = control_plane_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="executor-1",
        watermark=intent_watermark,
        claim_ttl_seconds=1,
        now=now,
    )
    restarted_store = type(control_plane_store)(control_plane_store.dsn)
    orphaned_claim = restarted_store.outbox_claim(envelope.repository, result.operation_key)
    assert restarted_store.outbox_status(envelope.repository, result.operation_key) == "unknown"
    assert orphaned_claim == first_claim
    assert (
        restarted_store.effect_eligible(
            first_claim,
            watermark=_observed_claim(intent_watermark, first_claim),
            now=now,
        )
        is False
    )
    restarted_store.reconcile_outbox(
        orphaned_claim, observed_applied=False, evidence={"readback": "not-found"}
    )
    claim = restarted_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="executor-2",
        watermark=intent_watermark,
        now=now + timedelta(seconds=2),
    )
    assert claim.fencing_token > first_claim.fencing_token
    assert (
        restarted_store.effect_eligible(
            first_claim,
            watermark=_observed_claim(intent_watermark, first_claim),
            now=now + timedelta(seconds=2),
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

    restarted_store.reconcile_outbox(claim, observed_applied=True, evidence={"merge_sha": "a" * 40})
    assert restarted_store.outbox_status(envelope.repository, result.operation_key) == "succeeded"


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
    recovered.reconcile_outbox(
        orphaned_claim,
        observed_applied=False,
        evidence={"readback": "not-found"},
    )
    retried = recovered.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="replacement-executor",
        watermark=intent_watermark,
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
    now = datetime.now(timezone.utc)
    first = control_plane_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="expired-executor",
        watermark=intent_watermark,
        claim_ttl_seconds=1,
        now=now,
    )

    with pytest.raises(UnknownEffectNeedsReconciliation):
        control_plane_store.claim_outbox(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="replacement-executor",
            watermark=intent_watermark,
            now=now + timedelta(seconds=2),
        )
    recovered = control_plane_store.outbox_claim(envelope.repository, result.operation_key)
    assert recovered == first
    assert control_plane_store.outbox_status(envelope.repository, result.operation_key) == "unknown"
