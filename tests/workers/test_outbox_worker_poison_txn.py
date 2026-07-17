"""Atomic poison-path bookkeeping for #3930.

With per-call autocommit connections, ``run()``'s failure path committed
``bump_outbox_attempts``, the dead-letter audit insert, and ``ack_outbox`` as
three independent transactions. A worker crash between them stranded partial
durable state: a row durably ``attempts == max`` yet undelivered, one extra
dispatch attempt past the configured budget on restart, and a duplicate
dead-letter audit row under the next attempt-scoped idempotency key
(``poison:<n+1>``) inflating ``dead_letter_stats()``.

These tests drive the production ``run()``/``run_once()`` paths against an
in-memory connection that models real transaction semantics (staged writes
become durable only on ``commit()``; ``close()`` rolls back like psycopg3) and
lock in the #3930 contract:

1. bump + dead-letter + ack commit as ONE transaction on ONE connection;
2. a crash before the final commit leaves NO partial durable state;
3. below the poison threshold the bump alone commits durably before the
   crash-retry re-raise (the budget survives supervised restarts, #2252);
4. the dead-letter DB write stays best-effort (savepoint): its failure never
   blocks the ack;
5. the schema-violation dead-letter+ack pair shares the same mechanism.
"""

from __future__ import annotations

import copy
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest

from app.events.types import INGEST_VAULT_CHANGED
from app.workers import outbox_worker

pytestmark = pytest.mark.not_pg


class _FakeCursor:
    def __init__(self, rows: list[tuple]):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeTxnConn:
    """In-memory ``outbox`` table with explicit transaction semantics.

    Unlike the autocommit-shaped fakes elsewhere in the suite, writes are
    staged per transaction and become durable only on ``commit()``;
    ``close()`` with a pending transaction rolls back (psycopg3 behavior).
    ``transaction()`` models a savepoint: on exception the staged state is
    restored to the snapshot and the exception re-raised.
    """

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.committed: dict[str, dict[str, Any]] = {r["id"]: dict(r) for r in (rows or [])}
        self.pending: dict[str, dict[str, Any]] | None = None
        self.ops: list[str] = []
        self.commits = 0
        self.closes = 0
        self.fail_on: set[str] = set()
        self.autocommit = False

    def _staged(self) -> dict[str, dict[str, Any]]:
        if self.pending is None:
            self.pending = copy.deepcopy(self.committed)
            self.ops.append("begin")
        return self.pending

    def execute(self, sql: str, params: tuple = ()) -> _FakeCursor:
        text = " ".join(sql.lower().split())
        rows = self._staged()

        if text.startswith("update outbox set attempts"):
            self.ops.append("bump")
            if "bump" in self.fail_on:
                raise RuntimeError("injected bump failure")
            row = rows.get(params[0])
            if row and row["delivered_at"] is None:
                row["attempts"] = int(row.get("attempts", 0)) + 1
                return _FakeCursor([(row["attempts"],)])
            return _FakeCursor([])

        if text.startswith("insert into outbox"):
            self.ops.append("dead_letter_insert")
            if "dead_letter_insert" in self.fail_on:
                raise RuntimeError("injected dead-letter insert failure")
            row_id, topic, payload, created_at, attempts = params
            if row_id in rows:
                return _FakeCursor([])
            rows[row_id] = {
                "id": row_id,
                "topic": topic,
                "payload": payload,
                "created_at": created_at,
                "delivered_at": None,
                "attempts": attempts,
            }
            return _FakeCursor([(row_id,)])

        if text.startswith("update outbox set delivered_at"):
            self.ops.append("ack")
            if "ack" in self.fail_on:
                raise RuntimeError("injected ack failure")
            row = rows.get(params[0])
            if row and row["delivered_at"] is None:
                row["delivered_at"] = "acked"
                return _FakeCursor([(1,)])
            return _FakeCursor([])

        return _FakeCursor([])

    def commit(self) -> None:
        self.ops.append("commit")
        if "commit" in self.fail_on:
            raise RuntimeError("injected commit failure")
        self.commits += 1
        if self.pending is not None:
            self.committed = self.pending
            self.pending = None

    def rollback(self) -> None:
        self.ops.append("rollback")
        self.pending = None

    @contextmanager
    def transaction(self) -> Iterator[None]:
        # psycopg3 semantics: the outermost block (no transaction in progress)
        # BEGINs and commits on clean exit / rolls back on exception; a nested
        # block (transaction already open) only creates a savepoint and never
        # commits the outer transaction.
        outermost = self.pending is None
        snapshot = copy.deepcopy(self._staged())
        self.ops.append("txn_begin" if outermost else "savepoint")
        try:
            yield
        except Exception:
            if outermost:
                self.rollback()
            else:
                self.pending = snapshot
            raise
        else:
            if outermost:
                self.commit()

    def close(self) -> None:
        self.closes += 1
        if self.pending is not None:
            self.ops.append("rollback_on_close")
            self.pending = None

    # Test helpers
    def committed_row(self, row_id: str) -> dict[str, Any]:
        return self.committed[row_id]

    def committed_dead_letters(self) -> list[dict[str, Any]]:
        return [
            r
            for r in self.committed.values()
            if r["topic"] == outbox_worker.OUTBOX_EVENT_DEAD_LETTERED
        ]


def _wire_worker_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    conn: FakeTxnConn,
    *,
    max_attempts: int,
) -> None:
    vault = tmp_path / "selected-vault"
    vault.mkdir(exist_ok=True)
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.delenv("WATCHER_VAULT_PATH", raising=False)
    # _use_db_outbox() must be true so the dead-letter audit takes the DB
    # branch; the value is never dialed (every connection is the fake).
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused-in-test")
    # The JSONL audit sink defaults to /app/tmp, which does not exist here; a
    # failing JSONL append would swallow the DB write this test asserts on.
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "index-outbox.jsonl"))
    monkeypatch.setenv("WORKER_MAX_DISPATCH_ATTEMPTS", str(max_attempts))
    monkeypatch.setattr(outbox_worker, "bootstrap", lambda: None)
    monkeypatch.setattr(outbox_worker, "write_worker_heartbeat", lambda **_: None)
    monkeypatch.setattr(outbox_worker, "open_outbox_txn_conn", lambda: conn)
    outbox_worker._EVENT_DEDUP._seen.clear()


def _poison_message() -> dict[str, Any]:
    return {
        "id": "row-poison",
        "topic": INGEST_VAULT_CHANGED,
        "payload": {"trace_id": "trace-poison"},
    }


def _run_one_tick(monkeypatch: pytest.MonkeyPatch, message: dict[str, Any]) -> None:
    messages = [message]
    monkeypatch.setattr(
        outbox_worker, "poll_outbox_one", lambda: messages.pop(0) if messages else None
    )
    outbox_worker.run(
        interval=0.0,
        heartbeat_interval=9999,
        log_heartbeat_interval=None,
        stop_after_ticks=1,
    )


def test_poison_path_commits_bump_dead_letter_ack_in_one_transaction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """At the attempt cap, bump + dead-letter + ack commit once, together."""
    conn = FakeTxnConn(
        rows=[
            {
                "id": "row-poison",
                "topic": INGEST_VAULT_CHANGED,
                "payload": "{}",
                "created_at": "t0",
                "delivered_at": None,
                "attempts": 0,
            }
        ]
    )
    _wire_worker_env(monkeypatch, tmp_path, conn, max_attempts=1)

    def _permanent_failure(*_a: Any, **_k: Any) -> None:
        raise ValueError("permanent poison payload")

    monkeypatch.setattr(outbox_worker, "_dispatch_topic", _permanent_failure)

    _run_one_tick(monkeypatch, _poison_message())

    assert conn.commits == 1
    assert conn.ops.count("commit") == 1
    # All three statements ran on this single connection, in order, with the
    # only commit after the ack — no independent transaction per statement.
    assert (
        conn.ops.index("bump")
        < conn.ops.index("dead_letter_insert")
        < conn.ops.index("ack")
        < conn.ops.index("commit")
    )
    assert conn.closes >= 1

    row = conn.committed_row("row-poison")
    assert row["attempts"] == 1
    assert row["delivered_at"] is not None
    dead_letters = conn.committed_dead_letters()
    assert len(dead_letters) == 1
    stored = json.loads(dead_letters[0]["payload"])
    assert stored["payload"]["outbox_id"] == "row-poison"
    assert stored["payload"]["reason"] == "dispatch_failed:ValueError"
    assert stored["payload"]["attempts"] == 1


def test_poison_path_crash_before_commit_leaves_no_partial_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A crash between the statements rolls the whole cycle back.

    With the historical per-call autocommit connections this scenario left the
    row durably ``attempts == max`` yet undelivered and, on the next cycle,
    produced a second dead-letter audit row under ``poison:<n+1>``.

    The ack itself is the injected failure here (round-2 #3930 review): an
    unguarded ``ack_outbox(conn, message_id)`` would previously let this
    "injected ack failure" propagate and mask the real dispatch error
    (``ValueError("permanent poison payload")``) by the time it reached the
    worker's crash-retry re-raise. The fix (``_ack_and_commit_or_log``) logs
    the ack failure and lets the original dispatch error propagate instead —
    asserted below by matching on that original error, not the ack failure.
    """
    conn = FakeTxnConn(
        rows=[
            {
                "id": "row-poison",
                "topic": INGEST_VAULT_CHANGED,
                "payload": "{}",
                "created_at": "t0",
                "delivered_at": None,
                "attempts": 0,
            }
        ]
    )
    conn.fail_on = {"ack"}
    _wire_worker_env(monkeypatch, tmp_path, conn, max_attempts=1)

    def _permanent_failure(*_a: Any, **_k: Any) -> None:
        raise ValueError("permanent poison payload")

    monkeypatch.setattr(outbox_worker, "_dispatch_topic", _permanent_failure)

    with pytest.raises(ValueError, match="permanent poison payload"):
        _run_one_tick(monkeypatch, _poison_message())

    # Nothing became durable: no commit, bump rolled back, no dead-letter row,
    # row still pending — the restarted worker retries the whole cycle cleanly.
    assert conn.commits == 0
    row = conn.committed_row("row-poison")
    assert row["attempts"] == 0
    assert row["delivered_at"] is None
    assert conn.committed_dead_letters() == []


def test_poison_path_commit_failure_does_not_mask_original_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Same guarantee as above, triggered by a commit failure instead of an ack failure.

    Closes a coverage gap round-2 #3930 review flagged: the round-1 fix added
    ``_commit_or_log`` (guarding ``conn.commit()`` so a failure there can't
    mask ``handler_exc``, the real dispatch error, with an unrelated
    commit-failure exception by the time it reaches the worker's crash-retry
    re-raise) but shipped with no test exercising the failure branch itself —
    only the round-2 ack-failure fix (the test above) was regression-tested.
    This test exercises ``_ack_and_commit_or_log`` specifically (the at-cap
    path); the sibling below asserts the same for below-cap's ``_commit_or_log``.
    """
    conn = FakeTxnConn(
        rows=[
            {
                "id": "row-poison",
                "topic": INGEST_VAULT_CHANGED,
                "payload": "{}",
                "created_at": "t0",
                "delivered_at": None,
                "attempts": 0,
            }
        ]
    )
    conn.fail_on = {"commit"}
    _wire_worker_env(monkeypatch, tmp_path, conn, max_attempts=1)

    def _permanent_failure(*_a: Any, **_k: Any) -> None:
        raise ValueError("permanent poison payload")

    monkeypatch.setattr(outbox_worker, "_dispatch_topic", _permanent_failure)

    with pytest.raises(ValueError, match="permanent poison payload"):
        _run_one_tick(monkeypatch, _poison_message())

    assert conn.commits == 0
    row = conn.committed_row("row-poison")
    assert row["attempts"] == 0
    assert row["delivered_at"] is None
    assert conn.committed_dead_letters() == []


def test_below_threshold_commit_failure_does_not_mask_original_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Below the cap, a failed bump-commit still lets the original dispatch error propagate.

    Closes the same round-2-flagged coverage gap as the at-cap test above, for
    ``_commit_or_log``'s below-cap call site (only the attempts bump is
    committed below the poison cap; ``_ack_and_commit_or_log`` is not
    involved here).
    """
    conn = FakeTxnConn(
        rows=[
            {
                "id": "row-poison",
                "topic": INGEST_VAULT_CHANGED,
                "payload": "{}",
                "created_at": "t0",
                "delivered_at": None,
                "attempts": 0,
            }
        ]
    )
    conn.fail_on = {"commit"}
    _wire_worker_env(monkeypatch, tmp_path, conn, max_attempts=3)

    def _permanent_failure(*_a: Any, **_k: Any) -> None:
        raise ValueError("permanent poison payload")

    monkeypatch.setattr(outbox_worker, "_dispatch_topic", _permanent_failure)

    with pytest.raises(ValueError, match="permanent poison payload"):
        _run_one_tick(monkeypatch, _poison_message())

    assert conn.commits == 0
    row = conn.committed_row("row-poison")
    assert row["attempts"] == 0


def test_below_threshold_bump_commits_before_reraise(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Below the cap the bump alone commits durably before the crash-retry.

    The re-raise models the supervised restart (#2252); losing the bump with it
    would reset the poison budget and reintroduce the infinite crash-loop.
    """
    conn = FakeTxnConn(
        rows=[
            {
                "id": "row-poison",
                "topic": INGEST_VAULT_CHANGED,
                "payload": "{}",
                "created_at": "t0",
                "delivered_at": None,
                "attempts": 0,
            }
        ]
    )
    _wire_worker_env(monkeypatch, tmp_path, conn, max_attempts=3)

    def _permanent_failure(*_a: Any, **_k: Any) -> None:
        raise ValueError("permanent poison payload")

    monkeypatch.setattr(outbox_worker, "_dispatch_topic", _permanent_failure)

    with pytest.raises(ValueError, match="permanent poison payload"):
        _run_one_tick(monkeypatch, _poison_message())

    assert conn.commits == 1
    assert "dead_letter_insert" not in conn.ops
    assert "ack" not in conn.ops
    row = conn.committed_row("row-poison")
    assert row["attempts"] == 1
    assert row["delivered_at"] is None
    assert conn.committed_dead_letters() == []


def test_dead_letter_db_failure_does_not_block_ack(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The dead-letter DB write stays best-effort on the shared transaction.

    Its failure rolls back only the savepoint; the bump and the ack still
    commit, so a broken audit write can never wedge the queue (the documented
    KERNEL dead-letter contract).
    """
    conn = FakeTxnConn(
        rows=[
            {
                "id": "row-poison",
                "topic": INGEST_VAULT_CHANGED,
                "payload": "{}",
                "created_at": "t0",
                "delivered_at": None,
                "attempts": 0,
            }
        ]
    )
    conn.fail_on = {"dead_letter_insert"}
    _wire_worker_env(monkeypatch, tmp_path, conn, max_attempts=1)

    def _permanent_failure(*_a: Any, **_k: Any) -> None:
        raise ValueError("permanent poison payload")

    monkeypatch.setattr(outbox_worker, "_dispatch_topic", _permanent_failure)

    _run_one_tick(monkeypatch, _poison_message())

    assert "savepoint" in conn.ops
    assert conn.commits == 1
    row = conn.committed_row("row-poison")
    assert row["attempts"] == 1
    assert row["delivered_at"] is not None
    assert conn.committed_dead_letters() == []


def test_schema_violation_dead_letter_and_ack_share_transaction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The immediate dead-letter branches pair audit + ack in one transaction.

    Uses ``run_once`` with a registered-schema violation (KERNEL-08 shape from
    ``tests/workers/test_outbox_worker.py``); ``run()``'s matching branch
    shares the same helper.
    """
    from app.events.models import new_event

    conn = FakeTxnConn(
        rows=[
            {
                "id": "row-schema-violation",
                "topic": "index.embedding.requested",
                "payload": "{}",
                "created_at": "t0",
                "delivered_at": None,
                "attempts": 0,
            }
        ]
    )
    _wire_worker_env(monkeypatch, tmp_path, conn, max_attempts=3)

    # index.embedding.requested.v1 requires payload.object_id; this payload lacks it.
    bad_payload = {"not_object_id": "x"}
    tagged_event = new_event(
        event_type="index.embedding.requested",
        payload=bad_payload,
        meta={"payload_schema": "index.embedding.requested.v1"},
    )
    message = {
        "id": "row-schema-violation",
        "topic": "index.embedding.requested",
        "payload": bad_payload,
        "event": tagged_event,
    }
    monkeypatch.setattr(outbox_worker, "poll_outbox_one", lambda: message)

    def _fail_handler(*_a: Any, **_k: Any) -> None:  # pragma: no cover - must never run
        raise AssertionError("real topic handler must not run on a schema violation")

    monkeypatch.setattr(outbox_worker, "process_indexer_event", _fail_handler)

    result = outbox_worker.run_once(vault_root=None)

    assert result.state == "processed"
    assert conn.commits == 1
    assert "bump" not in conn.ops  # no poison budget spent on the first attempt
    assert (
        conn.ops.index("dead_letter_insert") < conn.ops.index("ack") < conn.ops.index("commit")
    )
    row = conn.committed_row("row-schema-violation")
    assert row["delivered_at"] is not None
    dead_letters = conn.committed_dead_letters()
    assert len(dead_letters) == 1
    stored = json.loads(dead_letters[0]["payload"])
    assert stored["payload"]["reason"] == "schema_violation"
    assert stored["payload"]["outbox_id"] == "row-schema-violation"
