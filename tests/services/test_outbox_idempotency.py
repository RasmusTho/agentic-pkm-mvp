"""KERNEL-02 (#2764): deterministic idempotency keys are mandatory on every DB outbox insert.

Covers the issue's behavioral ACs:

- ``test_key_is_required`` — keyless ``write_outbox_event`` calls fail at the
  signature level (``TypeError``); blank keys fail loud (``ValueError``).
- ``test_duplicate_emit_single_row`` — duplicate emission with the same derived
  key yields exactly one outbox row (``ON CONFLICT (id) DO NOTHING``).
- ``test_retry_events_not_swallowed`` — intentional re-emissions (worker retry
  and dead-letter audit events) carry attempt-scoped keys and produce distinct
  rows per attempt.

The fake connection emulates the exact SQL shape ``write_outbox_event`` sends to
Postgres, including primary-key conflict semantics (same integration-equivalent
harness pattern as ``tests/workers/test_outbox_worker_consumes_ingest.py``).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.events.models import new_event
from app.events.types import INGEST_OBJECT_CREATED, INGEST_VAULT_CHANGED
from app.services.outbox import (
    derive_idempotency_key,
    insert_object_and_outbox,
    payload_fingerprint,
    write_outbox_event,
)
from app.workers import outbox_worker

pytestmark = pytest.mark.not_pg


class _FakeCursor:
    def __init__(self, rows: list[tuple]):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeOutboxConn:
    """In-memory emulation of the keyed outbox insert with PK conflict semantics."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def execute(self, sql: str, params: tuple = ()) -> _FakeCursor:
        text = " ".join(sql.lower().split())
        if text.startswith("insert into outbox (id,"):
            assert "on conflict (id) do nothing" in text
            row_id, topic, payload, created_at, attempts = params
            if row_id in self.rows:
                return _FakeCursor([])  # conflict: no row inserted, nothing returned
            self.rows[row_id] = {
                "id": row_id,
                "topic": topic,
                "payload": payload,
                "created_at": created_at,
                "delivered_at": None,
                "attempts": attempts,
            }
            return _FakeCursor([(row_id,)])
        raise AssertionError(f"unexpected SQL shape reached the outbox: {text!r}")

    def close(self) -> None:  # pragma: no cover - parity with psycopg conn
        pass


def _event(topic: str = INGEST_OBJECT_CREATED, **payload: Any):
    return new_event(event_type=topic, payload=dict(payload) or {"uuid": "n-1"}, trace_id="t-1")


# --- AC: write_outbox_event has no optional-key path -------------------------


def test_key_is_required() -> None:
    conn = FakeOutboxConn()
    with pytest.raises(TypeError):
        write_outbox_event(_event(), conn)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        write_outbox_event(_event())  # type: ignore[call-arg]
    assert conn.rows == {}


@pytest.mark.parametrize("blank", ["", "   ", None, 123])
def test_blank_or_non_string_key_fails_loud(blank: Any) -> None:
    conn = FakeOutboxConn()
    with pytest.raises(ValueError):
        write_outbox_event(_event(), conn, idempotency_key=blank)
    assert conn.rows == {}


# --- AC: duplicate emission with the same derived key yields exactly one row --


def test_duplicate_emit_single_row() -> None:
    conn = FakeOutboxConn()
    key = derive_idempotency_key(INGEST_OBJECT_CREATED, "note-uuid-1", "content-hash-1")

    first = write_outbox_event(_event(uuid="note-uuid-1"), conn, idempotency_key=key)
    second = write_outbox_event(_event(uuid="note-uuid-1"), conn, idempotency_key=key)

    assert first == key
    assert second == ""  # swallowed duplicate returns no row id
    assert len(conn.rows) == 1

    other_key = derive_idempotency_key(INGEST_OBJECT_CREATED, "note-uuid-1", "content-hash-2")
    write_outbox_event(_event(uuid="note-uuid-1"), conn, idempotency_key=other_key)
    assert len(conn.rows) == 2  # changed content is a genuinely new row


def test_insert_object_and_outbox_derives_content_key() -> None:
    conn = FakeOutboxConn()
    payload = {"uuid": "n-9", "title": "T", "content": "body", "path": "/v/n.md"}

    insert_object_and_outbox(dict(payload), INGEST_OBJECT_CREATED, "trace-a", conn=conn)
    # Same content re-emitted (even under a new trace) is a log-layer no-op.
    insert_object_and_outbox(dict(payload), INGEST_OBJECT_CREATED, "trace-b", conn=conn)
    assert len(conn.rows) == 1

    changed = dict(payload, content="body v2")
    insert_object_and_outbox(changed, INGEST_OBJECT_CREATED, "trace-c", conn=conn)
    assert len(conn.rows) == 2


def test_ingest_key_ignores_mtime() -> None:
    """Spec: ingest keys on (topic, note_path, content_hash) — NOT file timestamps.

    A content-identical touch (same hash, new mtime, new trace) is the same
    logical emission and must dedup; a content change must not.
    """
    conn = FakeOutboxConn()
    watcher_payload = {
        "vault_path": "/v/n.md",
        "relative_path": "n.md",
        "mtime": 100.0,
        "hash": "content-hash-1",
        "watcher": "registry:ingest",
    }

    insert_object_and_outbox(dict(watcher_payload), INGEST_VAULT_CHANGED, "trace-a", conn=conn)
    touched = dict(watcher_payload, mtime=200.0)
    insert_object_and_outbox(touched, INGEST_VAULT_CHANGED, "trace-b", conn=conn)
    assert len(conn.rows) == 1  # metadata-only touch: same key, swallowed

    changed = dict(watcher_payload, mtime=300.0, hash="content-hash-2")
    insert_object_and_outbox(changed, INGEST_VAULT_CHANGED, "trace-c", conn=conn)
    assert len(conn.rows) == 2  # content change: new key, new row


# --- Shared derivation helper contract ----------------------------------------


def test_derive_idempotency_key_is_deterministic_uuid() -> None:
    a = derive_idempotency_key("topic.x", "source-1", "fp-1")
    b = derive_idempotency_key("topic.x", "source-1", "fp-1")
    assert a == b
    assert str(uuid.UUID(a)) == a  # valid uuid text for the outbox uuid PK
    assert derive_idempotency_key("topic.y", "source-1", "fp-1") != a
    assert derive_idempotency_key("topic.x", "source-2", "fp-1") != a
    assert derive_idempotency_key("topic.x", "source-1", "fp-2") != a


@pytest.mark.parametrize("args", [("", "s", "f"), ("t", "", "f"), ("t", "s", " "), (None, "s", "f")])
def test_derive_idempotency_key_rejects_blank_parts(args: tuple) -> None:
    with pytest.raises(ValueError):
        derive_idempotency_key(*args)


def test_payload_fingerprint_excludes_trace_id_and_orders_keys() -> None:
    fp = payload_fingerprint({"b": 1, "a": 2, "trace_id": "t-1"})
    assert fp == payload_fingerprint({"a": 2, "trace_id": "t-other", "b": 1})
    assert fp != payload_fingerprint({"a": 2, "b": 999})


# --- AC: intentional re-emissions (retry/dead-letter) are attempt-scoped -------


def _capture_worker_keys(monkeypatch: pytest.MonkeyPatch, conn: FakeOutboxConn) -> list[str]:
    keys: list[str] = []
    real = write_outbox_event

    def _spy(event, inner_conn=None, *, idempotency_key: str) -> str:
        keys.append(idempotency_key)
        return real(event, conn, idempotency_key=idempotency_key)

    monkeypatch.setattr(outbox_worker, "write_outbox_event", _spy)
    monkeypatch.setattr(outbox_worker, "_use_db_outbox", lambda: True)
    return keys


def test_retry_events_not_swallowed(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeOutboxConn()
    keys = _capture_worker_keys(monkeypatch, conn)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "audit.jsonl"))

    payload = {"event_id": "orig-evt-1", "vault_path": "/v/n.md", "trace_id": "t-1"}
    note_path = tmp_path / "n.md"

    # Attempt 1 and attempt 2 are intentional re-emissions: distinct rows.
    assert outbox_worker._queue_transient_retry(
        INGEST_VAULT_CHANGED, payload, note_path=note_path, reason="db down"
    )
    retried_once = dict(payload, _worker_retry_count=1)
    assert outbox_worker._queue_transient_retry(
        INGEST_VAULT_CHANGED, retried_once, note_path=note_path, reason="db down"
    )
    assert len(keys) == 2
    assert keys[0] != keys[1]
    assert len(conn.rows) == 2

    # Re-enqueue of the SAME attempt is a duplicate: same key, still 2 rows.
    assert outbox_worker._queue_transient_retry(
        INGEST_VAULT_CHANGED, payload, note_path=note_path, reason="db down"
    )
    assert keys[2] == keys[0]
    assert len(conn.rows) == 2


def test_dead_letter_emissions_are_attempt_scoped(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeOutboxConn()
    keys = _capture_worker_keys(monkeypatch, conn)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "audit.jsonl"))

    common = dict(
        topic=INGEST_VAULT_CHANGED,
        payload={"event_id": "orig-evt-2"},
        reason="poison",
        trace_id="t-2",
        error="boom",
    )
    outbox_worker._dead_letter_outbox_message(message_id="row-1", attempts=5, **common)
    outbox_worker._dead_letter_outbox_message(message_id="row-1", attempts=5, **common)
    assert len(conn.rows) == 1  # duplicate audit of the same drop dedups

    outbox_worker._dead_letter_outbox_message(message_id="row-1", attempts=6, **common)
    assert len(conn.rows) == 2  # a later re-poisoning is a genuine new row
    assert len(set(keys)) == 2
