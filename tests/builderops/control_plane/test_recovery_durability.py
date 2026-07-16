from __future__ import annotations

import pytest

pytestmark = pytest.mark.pg


def _commit_outbox_task(store, envelope, *, task_id: str, key: str):
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
        outbox={"effect_type": "github.comment", "payload": {"issue": 3792}},
        lease=lease,
    )


def test_unbound_intent_lsn_is_repaired_from_local_commit(control_plane_store, envelope) -> None:
    result = _commit_outbox_task(
        control_plane_store,
        envelope,
        task_id="unbound-intent",
        key="unbound-intent",
    )
    with control_plane_store._connect() as conn:
        conn.execute(
            "UPDATE builderops_outbox SET intent_lsn = NULL "
            "WHERE repository = %s AND operation_key = %s",
            (envelope.repository, result.operation_key),
        )
    claim = control_plane_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="worker",
    )
    assert claim.intent_lsn != "0/0"
    assert control_plane_store.effect_eligible(claim) is True


def test_local_commit_authorizes_replay_claim_and_effect(control_plane_store, envelope) -> None:
    store = control_plane_store
    result = _commit_outbox_task(
        store,
        envelope,
        task_id="task-3792",
        key="local-commit-gate",
    )

    replayed = store.replay(envelope.repository, "local-commit-gate")
    assert replayed is not None
    assert replayed.replayed is True
    assert replayed.recovery_lsn == result.recovery_lsn

    claim = store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="executor",
    )
    claim_receipt = store.receipt(envelope.repository, claim.receipt_sequence)
    assert claim_receipt["lease_holder"] == claim.worker_id
    assert claim_receipt["lease_fencing_token"] == claim.fencing_token
    assert store.effect_eligible(claim) is True

    store.mark_effect_unknown(claim, detail="response lost")
    reconciliation = store.reconcile_outbox(
        claim, observed_applied=True, evidence={"readback": "found"}
    )
    assert reconciliation.recovery_lsn != "0/0"
    assert store.outbox_status(envelope.repository, result.operation_key) == "succeeded"
