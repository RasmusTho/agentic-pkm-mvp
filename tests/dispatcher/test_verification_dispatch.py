from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from tests.dispatcher.verification_helpers import ledger, request
from app.dispatcher.store import SqliteStore


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


def test_ingest_claim_and_terminal_lifecycle_is_idempotent(tmp_path) -> None:
    state = ledger(tmp_path)
    first = state.ingest(request())
    assert state.ingest(request()).run_id == first.run_id
    claimed = state.claim(first.run_id, "coordinator")
    assert state.heartbeat(first.run_id, "coordinator").lease_id == claimed.lease_id
    running = state.start(first.run_id, "coordinator", "thread-1", {"head": first.head_sha})
    assert running.status == "running"
    done = state.terminal(first.run_id, "completed", {"outcome": "merged"})
    assert state.terminal(first.run_id, "completed", {"outcome": "merged"}) == done
    with pytest.raises(ValueError):
        state.terminal(first.run_id, "failed", {"outcome": "other"})

    second = state.ingest(request("b" * 40))
    failed = state.terminal(second.run_id, "failed", {"outcome": "launch_failed"})
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
