from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest

from app.builderops.control_plane import (
    Lease,
    LeaseRequired,
    LeaseUnavailable,
    StateConflict,
    StaleFencingToken,
    StorePort,
)

pytestmark = pytest.mark.pg


def test_stale_fencing_token_cannot_mutate_after_reassignment(
    control_plane_store, envelope
) -> None:
    store = control_plane_store
    assert isinstance(store, StorePort)
    now = datetime.now(timezone.utc)
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
                now=now,
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
        now=now,
    )
    store.heartbeat_lease(first, ttl_seconds=30, now=now + timedelta(seconds=10))

    restarted_store = type(store)(store.dsn)
    _, second = restarted_store.claim_task(
        envelope=envelope,
        task_id="task-3792",
        holder="worker-b",
        idempotency_key="reassignment-claim-b",
        request={"command": "claim"},
        ttl_seconds=30,
        now=now + timedelta(seconds=41),
    )
    assert second.fencing_token > first.fencing_token

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
        now=now + timedelta(seconds=42),
    )
    assert accepted.state == "completed"


def test_task_claim_release_and_complete_are_atomic_and_fenced(
    control_plane_store, envelope
) -> None:
    store = control_plane_store
    now = datetime.now(timezone.utc)
    store.commit_transition(
        envelope=envelope,
        task_id="lifecycle-task",
        to_state="ready",
        idempotency_key="lifecycle-create",
        request={"command": "create"},
    )

    with pytest.raises(RuntimeError, match="after_outbox"):
        store.claim_task(
            envelope=envelope,
            task_id="lifecycle-task",
            holder="failed-claimer",
            idempotency_key="lifecycle-failed-claim",
            request={"command": "claim"},
            ttl_seconds=30,
            now=now,
            fault_at="after_outbox",
        )
    claimed, first = store.claim_task(
        envelope=envelope,
        task_id="lifecycle-task",
        holder="worker-a",
        idempotency_key="lifecycle-claim-a",
        request={"command": "claim"},
        ttl_seconds=30,
        now=now,
    )
    assert claimed.state == "claimed"
    first = store.heartbeat_lease(first, ttl_seconds=30, now=now + timedelta(seconds=5))

    released = store.release_task(
        envelope=envelope,
        lease=first,
        idempotency_key="lifecycle-release-a",
        request={"command": "release"},
        now=now + timedelta(seconds=6),
    )
    assert released.state == "ready"
    with pytest.raises(StaleFencingToken):
        store.heartbeat_lease(first, ttl_seconds=30, now=now + timedelta(seconds=7))

    claimed_again, second = store.claim_task(
        envelope=envelope,
        task_id="lifecycle-task",
        holder="worker-b",
        idempotency_key="lifecycle-claim-b",
        request={"command": "claim"},
        ttl_seconds=30,
        now=now + timedelta(seconds=7),
    )
    assert claimed_again.state == "claimed"
    assert second.fencing_token > first.fencing_token
    with pytest.raises(StaleFencingToken):
        store.release_task(
            envelope=envelope,
            lease=first,
            idempotency_key="lifecycle-stale-release",
            request={"command": "release"},
            now=now + timedelta(seconds=8),
        )

    with pytest.raises(RuntimeError, match="after_outbox"):
        store.complete_task(
            envelope=envelope,
            lease=second,
            idempotency_key="lifecycle-complete",
            request={"command": "complete"},
            now=now + timedelta(seconds=8),
            fault_at="after_outbox",
        )
    second = store.heartbeat_lease(second, ttl_seconds=30, now=now + timedelta(seconds=9))
    completed = store.complete_task(
        envelope=envelope,
        lease=second,
        idempotency_key="lifecycle-complete",
        request={"command": "complete"},
        now=now + timedelta(seconds=10),
    )
    assert completed.state == "completed"
    with pytest.raises(StaleFencingToken):
        store.heartbeat_lease(second, ttl_seconds=30, now=now + timedelta(seconds=11))

    with pytest.raises(StateConflict):
        store.claim_task(
            envelope=envelope,
            task_id="lifecycle-task",
            holder="worker-c",
            idempotency_key="lifecycle-claim-after-complete",
            request={"command": "claim"},
            ttl_seconds=30,
            now=now + timedelta(seconds=11),
        )

    successor = store.claim_lease(
        envelope=envelope,
        resource_id="lifecycle-task",
        holder="worker-c",
        ttl_seconds=30,
        now=now + timedelta(seconds=11),
    )
    assert successor.fencing_token > second.fencing_token
