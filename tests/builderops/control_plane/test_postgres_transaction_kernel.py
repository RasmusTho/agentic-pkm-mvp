from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest

from app.builderops.control_plane import IdempotencyConflict, LeaseRequired

pytestmark = pytest.mark.pg


def _claimed_task(store, envelope, *, task_id: str, key: str):
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
    return lease


def _commit(
    store,
    envelope,
    *,
    lease,
    key="request-1",
    state="effect_pending",
    task_id="task-3792",
    fault_at=None,
):
    return store.commit_transition(
        envelope=envelope,
        task_id=task_id,
        to_state=state,
        idempotency_key=key,
        request={"command": "transition", "expected": None},
        outbox={"effect_type": "github.comment", "payload": {"issue": 3792}},
        lease=lease,
        fault_at=fault_at,
    )


def test_state_receipt_idempotency_and_outbox_commit_atomically(
    control_plane_store, envelope
) -> None:
    store = control_plane_store
    lease = _claimed_task(store, envelope, task_id="task-3792", key="atomic")
    before = store.authority_counts(envelope.repository)
    for fault_at in ("after_state", "after_receipt", "after_idempotency", "after_outbox"):
        with pytest.raises(RuntimeError, match="injected transaction fault"):
            _commit(store, envelope, lease=lease, key=f"fault-{fault_at}", fault_at=fault_at)
    assert store.authority_counts(envelope.repository) == before

    result = _commit(store, envelope, lease=lease)
    assert result.state == "effect_pending"
    assert store.readiness() == {"authority_epoch": 1, "schema_version": 1}
    assert store.authority_counts(envelope.repository) == {
        "tasks": 1,
        "attempts": 0,
        "records": 0,
        "promotions": 0,
        "receipts": before["receipts"] + 1,
        "idempotency": before["idempotency"] + 1,
        "outbox": 1,
    }


def test_idempotency_replay_and_conflict(control_plane_store, envelope) -> None:
    lease = _claimed_task(control_plane_store, envelope, task_id="task-3792", key="idempotency")
    original = _commit(control_plane_store, envelope, lease=lease)
    replay = _commit(control_plane_store, envelope, lease=lease)
    assert replay == original
    assert replay.replayed is True

    with pytest.raises(IdempotencyConflict):
        _commit(control_plane_store, envelope, lease=lease, state="completed")

    changed_authority = replace(
        envelope,
        actor="agent:different",
        source_refs=("github:issue:other",),
    )
    with pytest.raises(IdempotencyConflict):
        _commit(control_plane_store, changed_authority, lease=lease)

    barrier = Barrier(2)
    concurrent_lease = _claimed_task(
        control_plane_store, envelope, task_id="concurrent-task", key="concurrent"
    )

    def concurrent_retry(_: int):
        contender = type(control_plane_store)(control_plane_store.dsn)
        barrier.wait()
        return _commit(
            contender,
            envelope,
            lease=concurrent_lease,
            key="concurrent-request",
            task_id="concurrent-task",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        concurrent = list(pool.map(concurrent_retry, (1, 2)))
    assert concurrent[0] == concurrent[1]
    assert sum(result.replayed for result in concurrent) == 1

    response_lease = _claimed_task(
        control_plane_store, envelope, task_id="response-lost-task", key="response-lost"
    )
    with pytest.raises(RuntimeError, match="after_commit"):
        _commit(
            control_plane_store,
            envelope,
            lease=response_lease,
            key="response-lost",
            task_id="response-lost-task",
            fault_at="after_commit",
        )
    recovered = _commit(
        control_plane_store,
        envelope,
        lease=response_lease,
        key="response-lost",
        task_id="response-lost-task",
    )
    assert recovered.replayed is True
    assert recovered.recovery_lsn != "0/0"


def test_idempotency_distinguishes_absent_and_empty_outbox(control_plane_store, envelope) -> None:
    lease = _claimed_task(
        control_plane_store, envelope, task_id="optional-outbox-shape", key="optional-outbox"
    )
    kwargs = {
        "envelope": envelope,
        "task_id": "optional-outbox-shape",
        "to_state": "reviewed",
        "idempotency_key": "optional-outbox-shape",
        "request": {"command": "create"},
        "lease": lease,
    }
    control_plane_store.commit_transition(**kwargs)
    with pytest.raises(IdempotencyConflict):
        control_plane_store.commit_transition(**kwargs, outbox={})


def test_new_claimed_task_requires_atomic_fenced_ownership(control_plane_store, envelope) -> None:
    before = control_plane_store.authority_counts(envelope.repository)
    with pytest.raises(LeaseRequired, match="atomically bound fenced ownership"):
        control_plane_store.commit_transition(
            envelope=envelope,
            task_id="unowned-claimed-task",
            to_state="claimed",
            idempotency_key="unowned-claimed-task",
            request={"command": "claim"},
            outbox={"effect_type": "github.merge", "payload": {"pr": 3852}},
        )
    assert control_plane_store.authority_counts(envelope.repository) == before
    with pytest.raises(LeaseRequired, match="outbox intent requires"):
        control_plane_store.commit_transition(
            envelope=envelope,
            task_id="unowned-ready-effect",
            to_state="ready",
            idempotency_key="unowned-ready-effect",
            request={"command": "create"},
            outbox={"effect_type": "github.merge", "payload": {"pr": 3852}},
        )
    assert control_plane_store.authority_counts(envelope.repository) == before

    control_plane_store.commit_transition(
        envelope=envelope,
        task_id="existing-unowned-effect",
        to_state="ready",
        idempotency_key="existing-unowned-effect-create",
        request={"command": "create"},
    )
    existing_before = control_plane_store.authority_counts(envelope.repository)
    with pytest.raises(LeaseRequired, match="outbox intent requires"):
        control_plane_store.commit_transition(
            envelope=envelope,
            task_id="existing-unowned-effect",
            to_state="effect_pending",
            idempotency_key="existing-unowned-effect",
            request={"command": "schedule-effect"},
            outbox={"effect_type": "github.merge", "payload": {"pr": 3852}},
        )
    assert control_plane_store.authority_counts(envelope.repository) == existing_before


def test_generic_leases_cannot_authorize_task_effects(control_plane_store, envelope) -> None:
    store = control_plane_store

    store.commit_transition(
        envelope=envelope,
        task_id="generic-existing-task",
        to_state="ready",
        idempotency_key="generic-existing-task-create",
        request={"command": "create"},
    )
    _, existing_lease = store.claim_lease(
        envelope=envelope,
        resource_id="generic-existing-task",
        holder="generic-worker",
        idempotency_key="generic-existing-task-lease",
        request={"command": "claim-lease"},
    )
    existing_before = store.authority_counts(envelope.repository)
    with pytest.raises(LeaseRequired, match="lease provenance"):
        _commit(
            store,
            envelope,
            lease=existing_lease,
            key="generic-existing-task-effect",
            task_id="generic-existing-task",
        )
    assert store.authority_counts(envelope.repository) == existing_before

    _, nonexistent_lease = store.claim_lease(
        envelope=envelope,
        resource_id="generic-nonexistent-task",
        holder="generic-worker",
        idempotency_key="generic-nonexistent-task-lease",
        request={"command": "claim-lease"},
    )
    nonexistent_before = store.authority_counts(envelope.repository)
    with pytest.raises(LeaseRequired, match="lease provenance"):
        _commit(
            store,
            envelope,
            lease=nonexistent_lease,
            key="generic-nonexistent-task-effect",
            task_id="generic-nonexistent-task",
        )
    assert store.authority_counts(envelope.repository) == nonexistent_before

    task_id = "generic-reassigned-task"
    store.commit_transition(
        envelope=envelope,
        task_id=task_id,
        to_state="ready",
        idempotency_key=f"{task_id}-create",
        request={"command": "create"},
    )
    _, claimed_lease = store.claim_task(
        envelope=envelope,
        task_id=task_id,
        holder="task-worker",
        idempotency_key=f"{task_id}-claim",
        request={"command": "claim"},
    )
    with store._connect() as conn:
        conn.execute(
            "UPDATE builderops_leases SET expires_at = clock_timestamp() - interval '1 second' "
            "WHERE repository = %s AND lease_kind = 'task' AND resource_id = %s",
            (envelope.repository, task_id),
        )
    _, reassigned_lease = store.claim_lease(
        envelope=envelope,
        resource_id=task_id,
        holder="generic-worker",
        idempotency_key=f"{task_id}-generic-lease",
        request={"command": "claim-lease"},
    )
    assert claimed_lease.lease_kind == "task"
    assert reassigned_lease.lease_kind == "generic"
    reassigned_before = store.authority_counts(envelope.repository)
    with pytest.raises(LeaseRequired, match="lease provenance"):
        _commit(
            store,
            envelope,
            lease=reassigned_lease,
            key=f"{task_id}-effect",
            task_id=task_id,
        )
    assert store.authority_counts(envelope.repository) == reassigned_before


def test_transaction_result_binds_receipt_sequence_and_recovery_lsn(
    control_plane_store, envelope
) -> None:
    lease = _claimed_task(control_plane_store, envelope, task_id="task-3792", key="receipt-binding")
    result = _commit(control_plane_store, envelope, lease=lease)
    assert result.receipt_sequence > 0
    assert result.recovery_lsn and "/" in result.recovery_lsn
    stored = control_plane_store.receipt(envelope.repository, result.receipt_sequence)
    assert stored["task_id"] == result.task_id
    assert stored["recovery_lsn"] == result.recovery_lsn
    assert stored["idempotency_key"] == "request-1"
