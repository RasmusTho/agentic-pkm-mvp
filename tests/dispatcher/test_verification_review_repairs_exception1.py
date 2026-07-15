from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
import sqlite3
from threading import Event, Lock, Thread

import pytest

import app.dispatcher.verification_dispatch as verification_dispatch
from app.dispatcher.verification_dispatch import VerificationDispatchLedger
from tests.dispatcher.verification_helpers import HEAD, ledger, request


BEFORE_EXPIRY = "2030-01-01T00:00:00.000000+00:00"
LEASE_EXPIRY = "2030-01-01T00:00:00.000001+00:00"
AFTER_EXPIRY = "2030-01-01T00:00:00.000002+00:00"
NEW_HEAD = "b" * 40


class _ControlledClock:
    def __init__(self) -> None:
        self._value = BEFORE_EXPIRY
        self._lock = Lock()

    def now(self) -> str:
        with self._lock:
            return self._value

    def future(self, seconds: int) -> str:
        current = datetime.fromisoformat(self.now())
        return (current + timedelta(seconds=seconds)).isoformat(timespec="microseconds")

    def cross_expiry(self) -> None:
        with self._lock:
            self._value = AFTER_EXPIRY


class _InstrumentedConnection:
    """Signal immediately before a write attempts to acquire SQLite's lock."""

    def __init__(self, connection: sqlite3.Connection, write_attempted: Event) -> None:
        self._connection = connection
        self._write_attempted = write_attempted

    def __enter__(self) -> _InstrumentedConnection:
        self._connection.__enter__()
        return self

    def __exit__(self, *args: object) -> bool | None:
        return self._connection.__exit__(*args)

    def execute(
        self, sql: str, parameters: Sequence[object] = ()
    ) -> sqlite3.Cursor:
        statement = " ".join(sql.lower().split())
        if statement.startswith("begin immediate") or statement.startswith(
            "update verification_runs"
        ):
            self._write_attempted.set()
        return self._connection.execute(sql, parameters)

    def __getattr__(self, name: str) -> object:
        return getattr(self._connection, name)


def _claimed_run(
    tmp_path,
) -> tuple[VerificationDispatchLedger, str, str]:
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "host")
    assert claimed.lease_id is not None
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET lease_expires_at=? WHERE run_id=?",
            (LEASE_EXPIRY, run.run_id),
        )
        conn.commit()
    return state, run.run_id, claimed.lease_id


def _batch_planner(
    _attempts: list[dict[str, object]],
    attempt_id: Callable[[int], str],
) -> Sequence[Mapping[str, object]]:
    return [
        {
            "attempt_id": attempt_id(0),
            "kind": "review",
            "ordinal": 1,
            "session_id": "stale-review",
            "capability": "gpt-5.6-sol",
            "reasoning_effort": "xhigh",
            "context_hash": "stale-context",
            "outcome": "clean",
            "receipt": {"head_sha": HEAD},
        }
    ]


def _invoke_mutation(
    mutation: str,
    state: VerificationDispatchLedger,
    run_id: str,
    lease_id: str,
) -> object:
    if mutation == "heartbeat":
        return state.heartbeat(run_id, "host", lease_id)
    if mutation == "start":
        return state.start(
            run_id, "host", lease_id, "stale-thread", {"head_sha": HEAD}
        )
    if mutation == "attempt":
        return state.record_attempt(
            run_id,
            "verification",
            "stale-thread",
            "gpt-5.6-sol",
            "xhigh",
            {"head_sha": HEAD},
            "launched",
            holder="host",
            lease_id=lease_id,
        )
    if mutation == "event_batch":
        return state.record_attempt_batch(
            run_id,
            "stale-batch",
            1,
            HEAD,
            _batch_planner,
            holder="host",
            lease_id=lease_id,
        )
    if mutation == "head_rebind":
        return state.rebind_head(
            run_id,
            NEW_HEAD,
            expected_head_sha=HEAD,
            observed_repository="RasmusTho/agentic-pkm-mvp",
            observed_pr_number=3603,
            observed_head_sha=NEW_HEAD,
            holder="host",
            lease_id=lease_id,
        )
    if mutation == "backoff":
        return state.backoff(
            run_id,
            {"outcome": "stale"},
            "2999-01-01T00:00:00+00:00",
            holder="host",
            lease_id=lease_id,
        )
    if mutation == "terminal":
        return state.terminal(
            run_id,
            "failed",
            {"outcome": "stale"},
            holder="host",
            lease_id=lease_id,
        )
    if mutation == "human_exception":
        return state.exception(
            run_id,
            "autonomous-failure-critical",
            {"current_state": "stale"},
            holder="host",
            lease_id=lease_id,
        )
    raise AssertionError(f"unknown mutation: {mutation}")


def _assert_unchanged(
    mutation: str, state: VerificationDispatchLedger, run_id: str
) -> None:
    run = state.get(run_id)
    assert run is not None
    if mutation == "heartbeat":
        assert run.lease_expires_at == LEASE_EXPIRY
    elif mutation == "start":
        assert run.status == "claimed"
        assert run.coordinator_session_id is None
        assert run.context_pack is None
    elif mutation in {"attempt", "event_batch"}:
        assert state.attempts(run_id) == []
    elif mutation == "head_rebind":
        assert run.current_head_sha == HEAD
    elif mutation in {"backoff", "terminal"}:
        assert run.status == "claimed"
        assert run.terminal_receipt is None
    elif mutation == "human_exception":
        with state.store._connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM verification_exceptions WHERE run_id=?",
                (run_id,),
            ).fetchone()[0]
        assert count == 0


@pytest.mark.parametrize(
    ("mutation", "failure_message"),
    [
        ("heartbeat", "heartbeat ownership mismatch"),
        ("start", "start ownership mismatch"),
        ("attempt", "attempt ownership mismatch"),
        ("event_batch", "event batch ownership mismatch"),
        ("head_rebind", "head rebind ownership or head mismatch"),
        ("backoff", "backoff ownership mismatch"),
        ("terminal", "terminal ownership mismatch"),
        ("human_exception", "exception ownership mismatch"),
    ],
)
def test_token_mutation_waiting_on_write_lock_rechecks_expiry(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    failure_message: str,
) -> None:
    state, run_id, lease_id = _claimed_run(tmp_path)
    clock = _ControlledClock()
    monkeypatch.setattr(verification_dispatch, "_now", clock.now)
    monkeypatch.setattr(verification_dispatch, "_future", clock.future)

    raw_connect = state.store._connect
    blocker = raw_connect()
    blocker.execute("BEGIN IMMEDIATE")
    write_attempted = Event()

    def instrumented_connect() -> _InstrumentedConnection:
        return _InstrumentedConnection(raw_connect(), write_attempted)

    monkeypatch.setattr(state.store, "_connect", instrumented_connect)
    outcome: dict[str, object] = {}

    def mutate() -> None:
        try:
            outcome["result"] = _invoke_mutation(mutation, state, run_id, lease_id)
        except BaseException as exc:  # noqa: BLE001 - thread outcome is asserted below
            outcome["error"] = exc

    worker = Thread(target=mutate, daemon=True)
    worker.start()
    try:
        assert write_attempted.wait(timeout=2), "mutation never reached the SQLite write lock"
        assert worker.is_alive(), "mutation did not wait on the competing SQLite writer"
        assert clock.now() == BEFORE_EXPIRY
        assert clock.now() < LEASE_EXPIRY

        clock.cross_expiry()
        assert clock.now() > LEASE_EXPIRY
        blocker.commit()
        worker.join(timeout=5)
    finally:
        if blocker.in_transaction:
            blocker.rollback()
        blocker.close()
        worker.join(timeout=5)

    assert not worker.is_alive(), "mutation did not finish after the write lock was released"
    error = outcome.get("error")
    assert isinstance(error, ValueError), outcome
    assert failure_message in str(error)
    assert "result" not in outcome
    _assert_unchanged(mutation, state, run_id)


@pytest.mark.parametrize("mutation", ["claim", "defer", "supersede"])
@pytest.mark.parametrize(
    ("now", "is_expired"),
    [(BEFORE_EXPIRY, False), (LEASE_EXPIRY, True)],
)
def test_unclaimed_recovery_uses_less_than_or_equal_expiry_boundary(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    now: str,
    is_expired: bool,
) -> None:
    state, run_id, _lease_id = _claimed_run(tmp_path)
    monkeypatch.setattr(verification_dispatch, "_now", lambda: now)
    monkeypatch.setattr(
        verification_dispatch,
        "_future",
        lambda seconds: (
            datetime.fromisoformat(now) + timedelta(seconds=seconds)
        ).isoformat(timespec="microseconds"),
    )

    def recover() -> object:
        if mutation == "claim":
            return state.claim(run_id, "recovery-host")
        if mutation == "defer":
            return state.defer_unclaimed(
                run_id,
                {"outcome": "deferred"},
                "2999-01-01T00:00:00+00:00",
            )
        return state.supersede_unclaimed(
            run_id,
            {"outcome": "superseded"},
            reason="stale_head",
        )

    if is_expired:
        assert recover() is not None
    else:
        with pytest.raises(ValueError):
            recover()
