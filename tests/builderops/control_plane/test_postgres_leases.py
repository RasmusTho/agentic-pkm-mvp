from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest

from app.builderops.control_plane import Lease, LeaseUnavailable, StaleFencingToken

pytestmark = pytest.mark.pg


def test_stale_fencing_token_cannot_mutate_after_reassignment(
    control_plane_store, envelope
) -> None:
    store = control_plane_store
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

    first = store.claim_lease(
        envelope=envelope,
        resource_id="task-3792",
        holder="worker-a",
        ttl_seconds=30,
        now=now,
    )
    store.heartbeat_lease(first, ttl_seconds=30, now=now + timedelta(seconds=10))

    restarted_store = type(store)(store.dsn)
    second = restarted_store.claim_lease(
        envelope=envelope,
        resource_id="task-3792",
        holder="worker-b",
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

    accepted = restarted_store.commit_transition(
        envelope=envelope,
        task_id="task-3792",
        to_state="completed",
        idempotency_key="current-worker",
        request={"command": "complete"},
        lease=second,
    )
    assert accepted.state == "completed"
