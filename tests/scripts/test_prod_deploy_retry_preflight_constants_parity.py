"""Drift enforcement for scripts/prod_deploy_retry_preflight.py (#3903).

The PROD deploy preflight deliberately duplicates the worker's retry-budget
constants and threshold-resolution/counter-reading behavior instead of
importing ``app.workers.outbox_worker`` at runtime: the worker module pulls
httpx/yaml/pydantic plus module-level side effects, and deploy hosts may run
a bare ``python3`` without the venv. That import-light posture is correct --
but copies drift. This test (DB-free; mirrors the parity pattern of
``tests/migrations/test_outbox_schema_parity.py``) imports BOTH modules at
test time and pins them together, so any change to the worker's budgets or
semantics fails here until the preflight copy is updated.
"""

from __future__ import annotations

import json

import pytest

from app.workers import outbox_worker
from scripts import prod_deploy_retry_preflight as preflight


def test_retry_budget_constants_match_worker() -> None:
    assert preflight.MAX_TRANSIENT_RETRY_ATTEMPTS == outbox_worker._MAX_TRANSIENT_RETRY_ATTEMPTS
    assert preflight.DEFAULT_MAX_DISPATCH_ATTEMPTS == outbox_worker._MAX_DISPATCH_ATTEMPTS


@pytest.mark.parametrize(
    "raw_env",
    [
        None,  # unset -> default
        "7",  # valid override
        "1",  # smallest accepted override
        "abc",  # invalid -> default
        "-2",  # negative -> default
        "0",  # below minimum -> default
        "  ",  # whitespace junk -> default
    ],
)
def test_resolve_max_dispatch_attempts_parity(
    raw_env: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    if raw_env is None:
        monkeypatch.delenv("WORKER_MAX_DISPATCH_ATTEMPTS", raising=False)
    else:
        monkeypatch.setenv("WORKER_MAX_DISPATCH_ATTEMPTS", raw_env)

    assert (
        preflight._resolve_max_dispatch_attempts()
        == outbox_worker._resolve_max_dispatch_attempts()
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},  # missing key
        {"_worker_retry_count": 3},  # valid
        {"_worker_retry_count": 0},  # explicit zero
        {"_worker_retry_count": -1},  # negative -> clamped to 0
        {"_worker_retry_count": "abc"},  # non-numeric string -> 0
        {"_worker_retry_count": "3"},  # numeric string -> int() accepts
        {"_worker_retry_count": None},  # explicit null -> 0
        {"_worker_retry_count": 2.9},  # float -> int() truncates identically
    ],
)
def test_payload_retry_count_parity(payload: dict) -> None:
    assert preflight._payload_retry_count(payload) == outbox_worker._payload_retry_count(payload)


def test_envelope_unwrap_reads_the_same_counter_the_worker_reads() -> None:
    """write_outbox_event stores the Event ENVELOPE; the worker coerces it and
    reads _worker_retry_count off the INNER payload. The preflight's unwrap +
    count must agree with the worker's count on that inner payload -- for the
    envelope as a dict, the envelope as a JSON string (driver/text tolerance),
    and the legacy flat shape."""
    inner = {"_worker_retry_count": 3, "note_path": "/x/y.md"}
    envelope = {
        "event_type": "panel.scan.requested",
        "event_id": "e" * 32,
        "payload": inner,
    }

    expected = outbox_worker._payload_retry_count(inner)
    assert (
        preflight._payload_retry_count(preflight._pending_row_inner_payload(envelope)) == expected
    )
    assert (
        preflight._payload_retry_count(preflight._pending_row_inner_payload(json.dumps(envelope)))
        == expected
    )
    # Legacy flat rows: the whole column value IS the payload.
    assert (
        preflight._payload_retry_count(preflight._pending_row_inner_payload(inner)) == expected
    )


class _FakeCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows
        self.executed: list[tuple[str, dict]] = []

    def execute(self, sql: str, params: dict | None = None) -> None:
        self.executed.append((sql, dict(params or {})))

    def fetchall(self) -> list[tuple]:
        return self._rows


class _FakeConn:
    def __init__(self, rows: list[tuple]) -> None:
        self.cursor_obj = _FakeCursor(rows)

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj


def test_classification_boundary_tracks_live_worker_constants() -> None:
    """The corrected -1 boundary, pinned against the worker's OWN constants:
    the worker bumps attempts then dead-letters+acks in the same consume
    cycle, so a PENDING row at attempts == max - 1 is terminal (next
    non-transient failure dead-letters) while max - 2 still has a full retry
    cycle left. If the worker's budget changes, this test re-derives the
    boundary from the new value and the preflight must follow."""
    max_attempts = outbox_worker._MAX_DISPATCH_ATTEMPTS
    retry_budget = outbox_worker._MAX_TRANSIENT_RETRY_ATTEMPTS
    rows = [
        ("dispatch.terminal", {}, max_attempts - 1),
        ("dispatch.not-terminal", {}, max_attempts - 2),
        (
            "retry.terminal",
            {"event_type": "retry.terminal", "payload": {"_worker_retry_count": retry_budget}},
            0,
        ),
        (
            "retry.not-terminal",
            {
                "event_type": "retry.not-terminal",
                "payload": {"_worker_retry_count": retry_budget - 1},
            },
            0,
        ),
    ]
    conn = _FakeConn(rows)

    receipt = preflight.evaluate(conn, max_dispatch_attempts=max_attempts)

    assert receipt["status"] == "blocked"
    assert receipt["terminal_pending_count"] == 2
    assert receipt["by_topic"] == {"dispatch.terminal": 1, "retry.terminal": 1}
    assert receipt["by_classification"] == {
        "transient_retry_exhausted": 1,
        "dispatch_attempts_exhausted": 1,
    }
    assert receipt["thresholds"]["pending_attempts_threshold"] == max_attempts - 1
    # The server-side pre-filter must be threshold-parameterized the same way.
    sql, params = conn.cursor_obj.executed[0]
    assert "delivered_at is null" in sql
    assert params == {"attempts_threshold": max_attempts - 1}
