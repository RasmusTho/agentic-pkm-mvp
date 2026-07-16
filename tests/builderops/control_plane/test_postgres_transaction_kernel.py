from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest

from app.builderops.control_plane import IdempotencyConflict

pytestmark = pytest.mark.pg


def _commit(
    store, envelope, *, key="request-1", state="claimed", task_id="task-3792", fault_at=None
):
    return store.commit_transition(
        envelope=envelope,
        task_id=task_id,
        to_state=state,
        idempotency_key=key,
        request={"command": "claim", "expected": "ready"},
        outbox={"effect_type": "github.comment", "payload": {"issue": 3792}},
        fault_at=fault_at,
    )


def test_state_receipt_idempotency_and_outbox_commit_atomically(
    control_plane_store, envelope
) -> None:
    store = control_plane_store
    for fault_at in ("after_state", "after_receipt", "after_idempotency", "after_outbox"):
        with pytest.raises(RuntimeError, match="injected transaction fault"):
            _commit(store, envelope, key=f"fault-{fault_at}", fault_at=fault_at)
    assert store.authority_counts(envelope.repository) == {
        "tasks": 0,
        "attempts": 0,
        "records": 0,
        "promotions": 0,
        "receipts": 0,
        "idempotency": 0,
        "outbox": 0,
    }

    result = _commit(store, envelope)
    assert result.state == "claimed"
    assert store.readiness() == {"authority_epoch": 1, "schema_version": 1}
    assert store.authority_counts(envelope.repository) == {
        "tasks": 1,
        "attempts": 0,
        "records": 0,
        "promotions": 0,
        "receipts": 1,
        "idempotency": 1,
        "outbox": 1,
    }


def test_idempotency_replay_and_conflict(control_plane_store, envelope) -> None:
    original = _commit(control_plane_store, envelope)
    replay = _commit(control_plane_store, envelope)
    assert replay == original
    assert replay.replayed is True

    with pytest.raises(IdempotencyConflict):
        _commit(control_plane_store, envelope, state="completed")

    changed_authority = replace(
        envelope,
        actor="agent:different",
        source_refs=("github:issue:other",),
    )
    with pytest.raises(IdempotencyConflict):
        _commit(control_plane_store, changed_authority)

    barrier = Barrier(2)

    def concurrent_retry(_: int):
        contender = type(control_plane_store)(control_plane_store.dsn)
        barrier.wait()
        return _commit(
            contender,
            envelope,
            key="concurrent-request",
            task_id="concurrent-task",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        concurrent = list(pool.map(concurrent_retry, (1, 2)))
    assert concurrent[0] == concurrent[1]
    assert sum(result.replayed for result in concurrent) == 1

    with pytest.raises(RuntimeError, match="after_commit"):
        _commit(
            control_plane_store,
            envelope,
            key="response-lost",
            task_id="response-lost-task",
            fault_at="after_commit",
        )
    recovered = _commit(
        control_plane_store,
        envelope,
        key="response-lost",
        task_id="response-lost-task",
    )
    assert recovered.replayed is True
    assert recovered.recovery_lsn != "0/0"


def test_transaction_result_binds_receipt_sequence_and_recovery_lsn(
    control_plane_store, envelope
) -> None:
    result = _commit(control_plane_store, envelope)
    assert result.receipt_sequence > 0
    assert result.recovery_lsn and "/" in result.recovery_lsn
    stored = control_plane_store.receipt(envelope.repository, result.receipt_sequence)
    assert stored["task_id"] == result.task_id
    assert stored["recovery_lsn"] == result.recovery_lsn
    assert stored["idempotency_key"] == "request-1"
