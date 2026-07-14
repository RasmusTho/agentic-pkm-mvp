from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import sqlite3
from threading import Event, Lock, Thread

import pytest

import app.dispatcher.verification_dispatch as verification_dispatch
from app.dispatcher.verification_dispatch import VerificationRun
from tests.dispatcher.verification_helpers import ledger, request
from app.dispatcher.store import SqliteStore


CLAIM_PRE_LOCK = "2030-01-01T00:00:00.000000+00:00"
CLAIM_POST_LOCK = "2030-01-01T00:00:20.000000+00:00"


def test_shared_request_fixture_carries_governing_issue() -> None:
    payload = request()

    assert payload["linked_issue"] == 3603
    assert payload["supporting_issues"] == []


class _ClaimClock:
    def __init__(self) -> None:
        self._value = CLAIM_PRE_LOCK
        self._lock = Lock()
        self.samples: list[str] = []

    def now(self) -> str:
        with self._lock:
            self.samples.append(self._value)
            return self._value

    def future(self, seconds: int) -> str:
        current = datetime.fromisoformat(self.now())
        return (current + timedelta(seconds=seconds)).isoformat(timespec="microseconds")

    def cross_lock_wait(self) -> None:
        with self._lock:
            self._value = CLAIM_POST_LOCK


class _ClaimConnection:
    def __init__(
        self,
        connection: sqlite3.Connection,
        write_attempted: Event,
        write_acquired: Event,
    ) -> None:
        self._connection = connection
        self._write_attempted = write_attempted
        self._write_acquired = write_acquired

    def __enter__(self) -> _ClaimConnection:
        self._connection.__enter__()
        return self

    def __exit__(self, *args: object) -> bool | None:
        return self._connection.__exit__(*args)

    def execute(
        self, sql: str, parameters: Sequence[object] = ()
    ) -> sqlite3.Cursor:
        if " ".join(sql.lower().split()).startswith("begin immediate"):
            self._write_attempted.set()
            result = self._connection.execute(sql, parameters)
            self._write_acquired.set()
            return result
        return self._connection.execute(sql, parameters)

    def __getattr__(self, name: str) -> object:
        return getattr(self._connection, name)


def _claim_across_write_lock(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    ttl_seconds: int,
) -> tuple[VerificationRun, _ClaimClock, Event]:
    state = ledger(tmp_path)
    run = state.ingest(request())
    raw_connect = state.store._connect
    blocker = raw_connect()
    blocker.execute("BEGIN IMMEDIATE")
    write_attempted = Event()
    write_acquired = Event()
    clock = _ClaimClock()

    def instrumented_connect() -> _ClaimConnection:
        return _ClaimConnection(raw_connect(), write_attempted, write_acquired)

    monkeypatch.setattr(state.store, "_connect", instrumented_connect)
    monkeypatch.setattr(verification_dispatch, "_now", clock.now)
    monkeypatch.setattr(verification_dispatch, "_future", clock.future)
    outcome: dict[str, object] = {}

    def claim() -> None:
        try:
            outcome["result"] = state.claim(
                run.run_id, "post-lock-coordinator", ttl_seconds=ttl_seconds
            )
        except BaseException as exc:  # noqa: BLE001 - asserted thread outcome
            outcome["error"] = exc

    worker = Thread(target=claim, daemon=True)
    worker.start()
    try:
        assert write_attempted.wait(timeout=2), "claim never attempted the SQLite write lock"
        assert worker.is_alive(), "claim did not wait on the competing SQLite writer"
        clock.cross_lock_wait()
        blocker.commit()
        worker.join(timeout=5)
    finally:
        if blocker.in_transaction:
            blocker.rollback()
        blocker.close()
        worker.join(timeout=5)

    assert not worker.is_alive(), "claim did not finish after the lock was released"
    assert "error" not in outcome, outcome
    claimed = outcome.get("result")
    assert isinstance(claimed, VerificationRun), outcome
    return claimed, clock, write_acquired


def test_claim_lock_wait_samples_time_after_authoritative_lock(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _claimed, clock, write_acquired = _claim_across_write_lock(
        tmp_path, monkeypatch, ttl_seconds=10
    )

    assert write_acquired.is_set()
    assert clock.samples
    assert clock.samples[0] == CLAIM_POST_LOCK


def test_claim_lock_wait_never_commits_already_expired_lease(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ttl_seconds = 10
    claimed, _clock, write_acquired = _claim_across_write_lock(
        tmp_path, monkeypatch, ttl_seconds=ttl_seconds
    )

    expected_expiry = (
        datetime.fromisoformat(CLAIM_POST_LOCK) + timedelta(seconds=ttl_seconds)
    ).isoformat(timespec="microseconds")
    assert write_acquired.is_set()
    assert claimed.lease_expires_at == expected_expiry


def test_existing_schema_v2_upgrades_to_verification_schema_v3(tmp_path) -> None:
    db = tmp_path / "dispatcher.sqlite3"
    initial = SqliteStore(db)
    initial.initialize()
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE verification_exceptions")
        conn.execute("DROP TABLE verification_attempts")
        conn.execute("DROP TABLE verification_runs")
        conn.execute("UPDATE dispatcher_meta SET value='2' WHERE key='schema_version'")
        conn.commit()

    upgraded = SqliteStore(db)
    upgraded.list_tasks()
    with sqlite3.connect(db) as conn:
        version = conn.execute(
            "SELECT value FROM dispatcher_meta WHERE key='schema_version'"
        ).fetchone()[0]
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'verification_%'"
            )
        }
    assert version == "3"
    assert tables == {"verification_runs", "verification_attempts", "verification_exceptions"}


def test_existing_schema_v3_backfills_current_head_without_losing_request_audit(
    tmp_path,
) -> None:
    db = tmp_path / "dispatcher.sqlite3"
    state = ledger(tmp_path)
    original = state.ingest(request())
    with sqlite3.connect(db) as conn:
        conn.execute("ALTER TABLE verification_runs DROP COLUMN verified_head_sha")
        conn.execute("ALTER TABLE verification_runs DROP COLUMN current_head_sha")
        conn.commit()

    migrated = ledger(tmp_path).get(original.run_id)

    assert migrated is not None
    assert migrated.requested_head_sha == original.requested_head_sha
    assert migrated.head_sha == original.requested_head_sha
    assert migrated.verified_head_sha is None


def test_ingest_claim_and_terminal_lifecycle_is_idempotent(tmp_path) -> None:
    state = ledger(tmp_path)
    first = state.ingest(request())
    assert state.ingest(request()).run_id == first.run_id
    claimed = state.claim(first.run_id, "coordinator")
    assert state.heartbeat(first.run_id, "coordinator", claimed.lease_id).lease_id == claimed.lease_id
    running = state.start(first.run_id, "coordinator", claimed.lease_id, "thread-1", {"head": first.head_sha})
    assert running.status == "running"
    done = state.terminal(first.run_id, "failed", {"outcome": "blocked"}, holder="coordinator", lease_id=claimed.lease_id)
    assert done.status == "failed"
    with pytest.raises(ValueError):
        state.terminal(first.run_id, "failed", {"outcome": "other"}, holder="coordinator", lease_id=claimed.lease_id)

    second = state.ingest(request("b" * 40))
    second_claim = state.claim(second.run_id, "coordinator")
    failed = state.terminal(second.run_id, "failed", {"outcome": "launch_failed"}, holder="coordinator", lease_id=second_claim.lease_id)
    assert failed.status == "failed"


def test_duplicate_and_concurrent_claims_start_one_run(tmp_path) -> None:
    state = ledger(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        runs = list(pool.map(lambda _: state.ingest(request()), range(4)))
    assert len({run.run_id for run in runs}) == 1
    run_id = runs[0].run_id

    def claim(holder: str) -> bool:
        try:
            state.claim(run_id, holder)
        except ValueError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(claim, ["one", "two"]))
    assert outcomes.count(True) == 1

    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET lease_expires_at='2000-01-01T00:00:00+00:00' "
            "WHERE run_id=?",
            (run_id,),
        )
        conn.commit()
    with ThreadPoolExecutor(max_workers=2) as pool:
        recovered = list(pool.map(claim, ["recovery-one", "recovery-two"]))
    assert recovered.count(True) == 1
