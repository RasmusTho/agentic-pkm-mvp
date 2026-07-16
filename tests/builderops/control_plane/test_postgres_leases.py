from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from inspect import signature
from threading import Barrier
from time import sleep

import pytest

from app.builderops.control_plane import (
    IdempotencyConflict,
    Lease,
    LeaseRequired,
    LeaseUnavailable,
    RecoveryWatermark,
    StateConflict,
    StaleFencingToken,
    StorePort,
)

pytestmark = pytest.mark.pg


def _expire_lease(store, lease: Lease) -> None:
    with store._connect() as conn:
        conn.execute(
            "UPDATE builderops_leases SET expires_at = clock_timestamp() - interval '1 second' "
            "WHERE repository = %s AND lease_kind = %s AND resource_id = %s "
            "AND fencing_token = %s",
            (lease.repository, lease.lease_kind, lease.resource_id, lease.fencing_token),
        )


def _claim_generic_lease(
    store, envelope, *, resource_id: str, holder: str, key: str, ttl_seconds: int = 30
):
    return store.claim_lease(
        envelope=envelope,
        resource_id=resource_id,
        holder=holder,
        idempotency_key=key,
        request={"command": "claim-lease"},
        ttl_seconds=ttl_seconds,
    )


def _heartbeat(store, envelope, lease: Lease, *, key: str, ttl_seconds: int = 30):
    return store.heartbeat_lease(
        envelope=envelope,
        lease=lease,
        idempotency_key=key,
        request={"command": "heartbeat-lease"},
        ttl_seconds=ttl_seconds,
    )


def _observed(result) -> RecoveryWatermark:
    return RecoveryWatermark(
        recovered_through=result.recovery_lsn,
        observed_receipts=frozenset(
            {(result.repository, result.receipt_sequence, result.recovery_lsn)}
        ),
    )


def test_generic_lease_operations_are_atomic_durable_and_replay_exact_snapshots(
    control_plane_store, envelope
) -> None:
    store = control_plane_store
    claim_args = {
        "envelope": envelope,
        "resource_id": "durable-generic-lease",
        "holder": "worker-a",
        "idempotency_key": "durable-generic-claim",
        "request": {"command": "claim-lease"},
        "ttl_seconds": 30,
    }
    with pytest.raises(RuntimeError, match="after_lease_receipt"):
        store.claim_lease(**claim_args, fault_at="after_lease_receipt")

    claimed, lease = store.claim_lease(**claim_args)
    assert claimed.state == "lease.claimed"
    assert claimed.replayed is False
    assert lease.fencing_token == 1
    receipt = store.receipt(envelope.repository, claimed.receipt_sequence)
    assert receipt["event_type"] == "lease.claimed"
    assert receipt["lease_holder"] == lease.holder
    assert receipt["lease_fencing_token"] == lease.fencing_token
    assert receipt["recovery_lsn"] == claimed.recovery_lsn
    assert (
        store.replay(
            envelope.repository,
            claim_args["idempotency_key"],
            watermark=RecoveryWatermark(recovered_through=claimed.recovery_lsn),
        )
        is None
    )
    assert store.replay(
        envelope.repository, claim_args["idempotency_key"], watermark=_observed(claimed)
    ) == replace(claimed, replayed=True)
    replayed_claim, replayed_lease = store.claim_lease(**claim_args)
    assert replayed_claim == replace(claimed, replayed=True)
    assert replayed_lease == lease
    with pytest.raises(IdempotencyConflict):
        store.claim_lease(**{**claim_args, "ttl_seconds": 31})

    heartbeat_args = {
        "envelope": envelope,
        "lease": lease,
        "idempotency_key": "durable-generic-heartbeat",
        "request": {"command": "heartbeat-lease"},
        "ttl_seconds": 60,
    }
    with pytest.raises(RuntimeError, match="after_lease_commit"):
        store.heartbeat_lease(**heartbeat_args, fault_at="after_lease_commit")
    heartbeat, extended = store.heartbeat_lease(**heartbeat_args)
    assert heartbeat.state == "lease.heartbeat"
    assert heartbeat.replayed is True
    assert extended.expires_at > lease.expires_at
    replayed_heartbeat, replayed_extended = store.heartbeat_lease(**heartbeat_args)
    assert replayed_heartbeat == heartbeat
    assert replayed_extended == extended
    with pytest.raises(IdempotencyConflict):
        store.heartbeat_lease(**{**heartbeat_args, "ttl_seconds": 61})

    release_args = {
        "envelope": envelope,
        "lease": extended,
        "idempotency_key": "durable-generic-release",
        "request": {"command": "release-lease"},
    }
    with pytest.raises(RuntimeError, match="after_lease_commit"):
        store.release_lease(**release_args, fault_at="after_lease_commit")
    released = store.release_lease(**release_args)
    assert released.state == "lease.released"
    assert released.replayed is True
    assert store.release_lease(**release_args) == released
    with pytest.raises(StaleFencingToken):
        store.heartbeat_lease(
            envelope=envelope,
            lease=extended,
            idempotency_key="heartbeat-after-generic-release",
            request={"command": "heartbeat-lease"},
            ttl_seconds=30,
        )


def test_lock_wait_past_expiry_cannot_resurrect_lease(control_plane_store, envelope) -> None:
    store = control_plane_store
    _, lease = _claim_generic_lease(
        store,
        envelope,
        resource_id="lock-wait-expiry",
        holder="worker-a",
        key="lock-wait-expiry-claim",
        ttl_seconds=1,
    )
    pool = ThreadPoolExecutor(max_workers=1)
    with store._connect() as blocker:
        blocker.execute(
            "SELECT 1 FROM builderops_leases WHERE repository = %s AND lease_kind = %s "
            "AND resource_id = %s FOR UPDATE",
            (lease.repository, lease.lease_kind, lease.resource_id),
        )
        future = pool.submit(
            _heartbeat,
            store,
            envelope,
            lease,
            key="lock-wait-expiry-heartbeat",
            ttl_seconds=30,
        )
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
            _, lease = _claim_generic_lease(
                contender,
                envelope,
                resource_id="concurrent-task",
                holder=holder,
                key=f"concurrent-task-{holder}",
                ttl_seconds=30,
            )
            return lease
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


def test_generic_and_task_leases_use_disjoint_ownership_domains(
    control_plane_store, envelope
) -> None:
    store = control_plane_store
    for task_id in ("cross-holder-domain", "same-holder-domain"):
        store.commit_transition(
            envelope=envelope,
            task_id=task_id,
            to_state="ready",
            idempotency_key=f"{task_id}-create",
            request={"command": "create"},
        )

    _, cross_holder_generic = _claim_generic_lease(
        store,
        envelope,
        resource_id="cross-holder-domain",
        holder="generic-worker",
        key="cross-holder-generic",
    )
    cross_claim, cross_holder_task = store.claim_task(
        envelope=envelope,
        task_id="cross-holder-domain",
        holder="task-worker",
        idempotency_key="cross-holder-task-claim",
        request={"command": "claim"},
    )
    assert cross_holder_generic.lease_kind == "generic"
    assert cross_holder_task.lease_kind == "task"
    assert cross_claim.state == "claimed"

    _, same_holder_generic = _claim_generic_lease(
        store,
        envelope,
        resource_id="same-holder-domain",
        holder="shared-worker",
        key="same-holder-generic",
    )
    same_claim, same_holder_task = store.claim_task(
        envelope=envelope,
        task_id="same-holder-domain",
        holder="shared-worker",
        idempotency_key="same-holder-task-claim",
        request={"command": "claim"},
    )
    assert same_holder_generic.lease_kind == "generic"
    assert same_holder_task.lease_kind == "task"
    assert same_claim.state == "claimed"

    with store._connect() as conn:
        rows = conn.execute(
            "SELECT lease_kind, holder, fencing_token FROM builderops_leases "
            "WHERE repository = %s AND resource_id IN (%s, %s) "
            "ORDER BY resource_id, lease_kind",
            (envelope.repository, "cross-holder-domain", "same-holder-domain"),
        ).fetchall()
    assert [(row["lease_kind"], row["holder"]) for row in rows] == [
        ("generic", "generic-worker"),
        ("task", "task-worker"),
        ("generic", "shared-worker"),
        ("task", "shared-worker"),
    ]

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
    _, first = _heartbeat(store, envelope, first, key="reassignment-heartbeat-a")
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
        _heartbeat(store, envelope, original_lease, key="reassignment-stale-heartbeat")

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
    with pytest.raises(IdempotencyConflict):
        store.claim_task(
            envelope=envelope,
            task_id="lifecycle-task",
            holder="worker-a",
            idempotency_key="lifecycle-claim-a",
            request={"command": "claim"},
            ttl_seconds=31,
        )
    with pytest.raises(ValueError, match="positive ttl_seconds"):
        _heartbeat(store, envelope, first, key="lifecycle-zero-heartbeat", ttl_seconds=0)
    _, first = _heartbeat(store, envelope, first, key="lifecycle-heartbeat-a")

    released = store.release_task(
        envelope=envelope,
        lease=first,
        idempotency_key="lifecycle-release-a",
        request={"command": "release"},
    )
    assert released.state == "ready"
    with pytest.raises(StaleFencingToken):
        _heartbeat(store, envelope, first, key="lifecycle-released-heartbeat")

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
    _, second = _heartbeat(store, envelope, second, key="lifecycle-heartbeat-b")
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
        _heartbeat(store, envelope, second, key="lifecycle-completed-heartbeat")

    with pytest.raises(StateConflict):
        store.claim_task(
            envelope=envelope,
            task_id="lifecycle-task",
            holder="worker-c",
            idempotency_key="lifecycle-claim-after-complete",
            request={"command": "claim"},
            ttl_seconds=30,
        )

    _, successor = _claim_generic_lease(
        store,
        envelope,
        resource_id="lifecycle-task",
        holder="worker-c",
        key="lifecycle-successor-claim",
        ttl_seconds=30,
    )
    assert second.lease_kind == "task"
    assert successor.lease_kind == "generic"
    assert successor.fencing_token == 1
