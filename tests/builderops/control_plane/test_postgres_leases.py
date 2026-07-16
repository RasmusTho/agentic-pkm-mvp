from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from inspect import signature
from threading import Barrier
from time import sleep

import pytest

from app.builderops.control_plane import (
    IdempotencyConflict,
    Lease,
    LeaseRequired,
    LeaseUnavailable,
    StateConflict,
    StaleFencingToken,
    StorePort,
)

pytestmark = pytest.mark.pg


def _expire_lease(store, lease: Lease) -> None:
    with store._connect() as conn:
        conn.execute(
            "UPDATE builderops_leases SET expires_at = clock_timestamp() - interval '1 second' "
            "WHERE repository = %s AND resource_id = %s AND fencing_token = %s",
            (lease.repository, lease.resource_id, lease.fencing_token),
        )


def test_lock_wait_past_expiry_cannot_resurrect_lease(control_plane_store, envelope) -> None:
    store = control_plane_store
    lease = store.claim_lease(
        envelope=envelope,
        resource_id="lock-wait-expiry",
        holder="worker-a",
        ttl_seconds=1,
    )
    pool = ThreadPoolExecutor(max_workers=1)
    with store._connect() as blocker:
        blocker.execute(
            "SELECT 1 FROM builderops_leases WHERE repository = %s AND resource_id = %s FOR UPDATE",
            (lease.repository, lease.resource_id),
        )
        future = pool.submit(store.heartbeat_lease, lease, ttl_seconds=30)
        sleep(1.5)
    try:
        with pytest.raises(StaleFencingToken):
            future.result(timeout=5)
    finally:
        pool.shutdown(wait=True)


def test_stale_fencing_token_cannot_mutate_after_reassignment(
    control_plane_store, envelope
) -> None:
    store = control_plane_store
    assert isinstance(store, StorePort)
    assert {
        "claim_holder",
        "claim_ttl_seconds",
        "release_on_commit",
        "lease_now",
        "now",
        "_now",
    }.isdisjoint(signature(StorePort.commit_transition).parameters)
    for method_name in (
        "claim_task",
        "heartbeat_lease",
        "release_task",
        "complete_task",
        "claim_outbox",
        "effect_eligible",
    ):
        assert {"now", "_now"}.isdisjoint(signature(getattr(StorePort, method_name)).parameters)
    barrier = Barrier(2)

    def concurrent_claim(holder: str) -> Lease | LeaseUnavailable:
        contender = type(store)(store.dsn)
        barrier.wait()
        try:
            return contender.claim_lease(
                envelope=envelope,
                resource_id="concurrent-task",
                holder=holder,
                ttl_seconds=30,
            )
        except LeaseUnavailable as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(concurrent_claim, ("worker-a", "worker-b")))
    assert sum(isinstance(outcome, Lease) for outcome in outcomes) == 1
    assert sum(isinstance(outcome, LeaseUnavailable) for outcome in outcomes) == 1

    store.commit_transition(
        envelope=envelope,
        task_id="lease-required-task",
        to_state="ready",
        idempotency_key="create-before-lease",
        request={"command": "create"},
    )
    with pytest.raises(LeaseRequired):
        store.commit_transition(
            envelope=envelope,
            task_id="lease-required-task",
            to_state="claimed",
            idempotency_key="unfenced-overwrite",
            request={"command": "claim"},
        )

    create_barrier = Barrier(2)

    def concurrent_unleased_create(key: str):
        contender = type(store)(store.dsn)
        create_barrier.wait()
        try:
            return contender.commit_transition(
                envelope=envelope,
                task_id="concurrent-create-task",
                to_state=key,
                idempotency_key=key,
                request={"command": key},
            )
        except LeaseRequired as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        create_outcomes = list(pool.map(concurrent_unleased_create, ("creator-a", "creator-b")))
    assert sum(isinstance(outcome, LeaseRequired) for outcome in create_outcomes) == 1

    store.commit_transition(
        envelope=envelope,
        task_id="task-3792",
        to_state="ready",
        idempotency_key="reassignment-create",
        request={"command": "create"},
    )
    _, first = store.claim_task(
        envelope=envelope,
        task_id="task-3792",
        holder="worker-a",
        idempotency_key="reassignment-claim-a",
        request={"command": "claim"},
        ttl_seconds=30,
    )
    first = store.heartbeat_lease(first, ttl_seconds=30)
    _expire_lease(store, first)

    with pytest.raises(StaleFencingToken):
        store.complete_task(
            envelope=envelope,
            lease=first,
            idempotency_key="expired-before-reassignment",
            request={"command": "complete"},
        )

    restarted_store = type(store)(store.dsn)
    _, second = restarted_store.claim_task(
        envelope=envelope,
        task_id="task-3792",
        holder="worker-b",
        idempotency_key="reassignment-claim-b",
        request={"command": "claim"},
        ttl_seconds=30,
    )
    assert second.fencing_token > first.fencing_token
    replayed_claim, original_lease = restarted_store.claim_task(
        envelope=envelope,
        task_id="task-3792",
        holder="worker-a",
        idempotency_key="reassignment-claim-a",
        request={"command": "claim"},
        ttl_seconds=30,
    )
    assert replayed_claim.replayed is True
    assert original_lease.fencing_token == first.fencing_token
    with pytest.raises(StaleFencingToken):
        store.heartbeat_lease(original_lease, ttl_seconds=30)

    with pytest.raises(StaleFencingToken):
        store.commit_transition(
            envelope=envelope,
            task_id="task-3792",
            to_state="completed",
            idempotency_key="stale-worker",
            request={"command": "complete"},
            lease=first,
        )

    accepted = restarted_store.complete_task(
        envelope=envelope,
        lease=second,
        idempotency_key="current-worker",
        request={"command": "complete"},
    )
    assert accepted.state == "completed"


def test_task_claim_release_and_complete_are_atomic_and_fenced(
    control_plane_store, envelope
) -> None:
    store = control_plane_store
    store.commit_transition(
        envelope=envelope,
        task_id="lifecycle-task",
        to_state="ready",
        idempotency_key="lifecycle-create",
        request={"command": "create"},
    )

    with pytest.raises(ValueError, match="positive ttl_seconds"):
        store.claim_task(
            envelope=envelope,
            task_id="lifecycle-task",
            holder="invalid-claimer",
            idempotency_key="lifecycle-zero-ttl",
            request={"command": "claim"},
            ttl_seconds=0,
        )

    with pytest.raises(RuntimeError, match="after_outbox"):
        store.claim_task(
            envelope=envelope,
            task_id="lifecycle-task",
            holder="failed-claimer",
            idempotency_key="lifecycle-failed-claim",
            request={"command": "claim"},
            ttl_seconds=30,
            fault_at="after_outbox",
        )
    claimed, first = store.claim_task(
        envelope=envelope,
        task_id="lifecycle-task",
        holder="worker-a",
        idempotency_key="lifecycle-claim-a",
        request={"command": "claim"},
        ttl_seconds=30,
    )
    assert claimed.state == "claimed"
    claim_receipt = store.receipt(envelope.repository, claimed.receipt_sequence)
    assert claim_receipt["lease_holder"] == first.holder
    assert claim_receipt["lease_fencing_token"] == first.fencing_token
    with pytest.raises(ValueError, match="positive ttl_seconds"):
        store.heartbeat_lease(first, ttl_seconds=0)
    first = store.heartbeat_lease(first, ttl_seconds=30)

    released = store.release_task(
        envelope=envelope,
        lease=first,
        idempotency_key="lifecycle-release-a",
        request={"command": "release"},
    )
    assert released.state == "ready"
    with pytest.raises(StaleFencingToken):
        store.heartbeat_lease(first, ttl_seconds=30)

    claimed_again, second = store.claim_task(
        envelope=envelope,
        task_id="lifecycle-task",
        holder="worker-b",
        idempotency_key="lifecycle-claim-b",
        request={"command": "claim"},
        ttl_seconds=30,
    )
    assert claimed_again.state == "claimed"
    assert second.fencing_token > first.fencing_token
    with pytest.raises(IdempotencyConflict):
        store.release_task(
            envelope=envelope,
            lease=second,
            idempotency_key="lifecycle-release-a",
            request={"command": "release"},
        )
    with pytest.raises(StaleFencingToken):
        store.release_task(
            envelope=envelope,
            lease=first,
            idempotency_key="lifecycle-stale-release",
            request={"command": "release"},
        )

    with pytest.raises(RuntimeError, match="after_outbox"):
        store.complete_task(
            envelope=envelope,
            lease=second,
            idempotency_key="lifecycle-complete",
            request={"command": "complete"},
            fault_at="after_outbox",
        )
    second = store.heartbeat_lease(second, ttl_seconds=30)
    completed = store.complete_task(
        envelope=envelope,
        lease=second,
        idempotency_key="lifecycle-complete",
        request={"command": "complete"},
    )
    assert completed.state == "completed"
    complete_receipt = store.receipt(envelope.repository, completed.receipt_sequence)
    assert complete_receipt["lease_holder"] == second.holder
    assert complete_receipt["lease_fencing_token"] == second.fencing_token
    with pytest.raises(StaleFencingToken):
        store.heartbeat_lease(second, ttl_seconds=30)

    with pytest.raises(StateConflict):
        store.claim_task(
            envelope=envelope,
            task_id="lifecycle-task",
            holder="worker-c",
            idempotency_key="lifecycle-claim-after-complete",
            request={"command": "claim"},
            ttl_seconds=30,
        )

    successor = store.claim_lease(
        envelope=envelope,
        resource_id="lifecycle-task",
        holder="worker-c",
        ttl_seconds=30,
    )
    assert successor.fencing_token > second.fencing_token
