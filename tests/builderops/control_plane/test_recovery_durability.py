from __future__ import annotations

import pytest

from app.builderops.control_plane import DurabilityPending

pytestmark = pytest.mark.pg


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
    assert store.replay(envelope.repository, "durability-gate", recovered_through="0/0") is None
    with pytest.raises(DurabilityPending):
        store.claim_outbox(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="demerzel",
            recovered_through="0/0",
        )
    assert calls == []

    claim = store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="demerzel",
        recovered_through=result.recovery_lsn,
    )
    assert store.effect_eligible(claim, recovered_through=result.recovery_lsn) is False
    assert calls == []
    assert store.effect_eligible(claim, recovered_through=claim.claim_lsn) is True
    calls.append(claim.operation_key)
    store.mark_effect_unknown(claim, detail="response lost")
    store.reconcile_outbox(claim, observed_applied=True, evidence={"readback": "found"})
    assert calls == [result.operation_key]
