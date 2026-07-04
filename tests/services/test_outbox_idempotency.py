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


def test_revert_emits_new_event() -> None:
    """A→B→A content revert MUST emit — dedup scope is the observation, not content.

    Outbox rows are never purged: a bare content key would collide the revert
    with the original A row and ON CONFLICT DO NOTHING would swallow it while
    the object/file_state write still commits — silent projection divergence.
    Vault-sync payloads carry no mtime; the per-observation marker (observed
    stat mtime) is mixed into the fingerprint via ``observation=``.
    """
    conn = FakeOutboxConn()
    payload_a = {"uuid": "n-7", "title": "T", "content": "A", "path": "/v/n.md"}
    payload_b = dict(payload_a, content="B")

    insert_object_and_outbox(dict(payload_a), INGEST_OBJECT_CREATED, "t-1", conn=conn, observation="m1")
    insert_object_and_outbox(dict(payload_b), INGEST_OBJECT_CREATED, "t-2", conn=conn, observation="m2")
    assert len(conn.rows) == 2

    # Revert to A: byte-identical payload to the original, NEW observation.
    insert_object_and_outbox(dict(payload_a), INGEST_OBJECT_CREATED, "t-3", conn=conn, observation="m3")
    assert len(conn.rows) == 3  # the revert is a genuinely new event

    # Watcher-payload shape: the observation (file mtime) is already embedded
    # in the payload, so the same revert property holds without observation=.
    watcher_a = {
        "vault_path": "/v/n.md",
        "relative_path": "n.md",
        "mtime": 100.0,
        "hash": "hash-A",
        "watcher": "registry:ingest",
    }
    insert_object_and_outbox(dict(watcher_a), INGEST_VAULT_CHANGED, "t-4", conn=conn)
    insert_object_and_outbox(
        dict(watcher_a, mtime=200.0, hash="hash-B"), INGEST_VAULT_CHANGED, "t-5", conn=conn
    )
    insert_object_and_outbox(
        dict(watcher_a, mtime=300.0), INGEST_VAULT_CHANGED, "t-6", conn=conn
    )  # revert to hash-A at a new mtime
    assert len(conn.rows) == 6


def test_crash_retry_same_observation_dedups() -> None:
    """Crash/retry of the SAME observation re-derives the same key and dedups.

    The observation marker must be observation-derived (file stat mtime — it
    re-reads identically after a crash), never emission wall-clock. A new trace
    id on the retry must not defeat the dedup.
    """
    conn = FakeOutboxConn()
    payload = {"uuid": "n-8", "title": "T", "content": "A", "path": "/v/n.md"}

    insert_object_and_outbox(dict(payload), INGEST_OBJECT_CREATED, "t-1", conn=conn, observation="m1")
    insert_object_and_outbox(dict(payload), INGEST_OBJECT_CREATED, "t-2", conn=conn, observation="m1")
    assert len(conn.rows) == 1  # retried emission of the same observation: swallowed

    # Watcher shape: retried tick / post-restart re-observation re-reads the
    # same mtime+hash from the file → identical payload → same key.
    watcher = {
        "vault_path": "/v/n.md",
        "relative_path": "n.md",
        "mtime": 100.0,
        "hash": "hash-A",
        "watcher": "registry:ingest",
    }
    insert_object_and_outbox(dict(watcher), INGEST_VAULT_CHANGED, "t-3", conn=conn)
    insert_object_and_outbox(dict(watcher), INGEST_VAULT_CHANGED, "t-4", conn=conn)
    assert len(conn.rows) == 2

    # The observation marker is fingerprint-only: it must not leak into the
    # emitted payload.
    stored = [r for r in conn.rows.values() if r["topic"] == INGEST_OBJECT_CREATED]
    assert all("__observation__" not in str(r["payload"]) for r in stored)


# --- Shared derivation helper contract ----------------------------------------


def test_save_object_content_change_emits_new_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """save_object (objects/API path) must emit a new event when content changes.

    The emitted payload is only ``{uuid, kind}``; under mandatory content-derived
    keys (#2764) a later save of the SAME uuid with CHANGED content would derive
    the same key and be swallowed by ``ON CONFLICT DO NOTHING`` while the durable
    store write still lands — silent event loss (KERNEL-02, #2863). The fix mixes
    the durable payload's content fingerprint into the key via ``observation=``,
    so content changes emit distinct events while a crash-retry of the same save
    still dedups. This drives the real ``ObjectStore.save_object`` production path.
    """
    from types import SimpleNamespace

    import app.objects as objects_mod
    from app.objects import DomainObject, ObjectStore

    conn = FakeOutboxConn()

    def _routed(payload, topic, trace_id=None, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.pop("conn", None)
        return insert_object_and_outbox(payload, topic, trace_id, conn=conn, **kwargs)

    # Force a non-memory backend so save_object takes the durable + emit branch;
    # the stub store's put() is a no-op (we only assert on emitted outbox rows).
    stub_binding = SimpleNamespace(backend="pg", store=SimpleNamespace(put=lambda *a, **k: None))
    monkeypatch.setattr(objects_mod, "resolve_object_store_port", lambda: stub_binding)
    monkeypatch.setattr(objects_mod, "insert_object_and_outbox", _routed)

    store = ObjectStore()
    obj_uuid = "11111111-1111-1111-1111-111111111111"

    def _save(content: str) -> None:
        store.save_object(
            DomainObject(uuid=obj_uuid, kind="note", payload={"content": content}, source_ref=None, created_at=None)
        )

    _save("A")
    _save("A")  # crash-retry of the same save: identical content → dedups
    assert len(conn.rows) == 1

    _save("B")  # changed content → genuinely new event
    assert len(conn.rows) == 2

    # The objects/API path has no per-observation marker (unlike vault-sync's
    # file mtime), so the content fingerprint IS the emission identity: a
    # byte-identical re-save (here, a revert to A) re-derives the first key and
    # dedups. Distinct content — not recurrence — is the signal that emits.
    _save("A")
    assert len(conn.rows) == 2

    # The content fingerprint is fingerprint-only: it must not leak into payloads.
    assert all("__observation__" not in str(r["payload"]) for r in conn.rows.values())
    assert all("content" not in str(r["payload"]) for r in conn.rows.values())


def test_ingest_route_content_only_key_accepted_limitation(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ``/ingest`` API route keys on content only — accepted limitation (#2902).

    The route embeds ``content`` in its payload, so a content CHANGE already
    emits a distinct event (it never had ``save_object``'s pre-#2863
    ``{uuid, kind}`` content-invariant over-dedup). It passes no ``observation=``
    marker because an API push is not a file-observation source — there is no
    natural per-observation mtime — so the content fingerprint IS the emission
    identity. Consequences pinned here:

    - a byte-identical crash-retry of the same POST dedups (KERNEL-02 intent);
    - a content change emits a genuinely new event;
    - a byte-identical A→B→A content revert ALSO dedups (the lesser revert
      hole): the revert re-derives the original A key and ``ON CONFLICT (id) DO
      NOTHING`` swallows it while any durable write still lands.

    Decision #2902: accepted, NOT fixed. A caller-supplied idempotency/observation
    token would let a naive client (per-request UUID) defeat crash-retry dedup
    entirely — reintroducing the at-least-once-multiplies-effects bug KERNEL-02
    exists to kill, a worse failure than the rare revert dedup. Residual revert
    divergence is reconcilable via the incremental reconcile / doctor staleness
    path (#2880). This drives the real route + ``normalize_artifact_state_axes``
    path. See ``docs/EVENTS.md :: Event Idempotency (normative)`` and
    ``docs/RUNTIME_CORRECTNESS_KERNEL/MANDATORY_OUTBOX_IDEMPOTENCY.md ::
    Known deferrals (tracked)``.
    """
    from fastapi.testclient import TestClient

    from app.api.app import app

    conn = FakeOutboxConn()

    def _routed(payload, topic, trace_id=None, **kwargs):  # type: ignore[no-untyped-def]
        # The route must NOT supply an observation marker (accepted limitation):
        # content is the only emission identity on the API push path.
        assert kwargs.get("observation") is None
        kwargs.pop("conn", None)
        return insert_object_and_outbox(payload, topic, trace_id, conn=conn, **kwargs)

    monkeypatch.setattr("app.api.routes.ingest.insert_object_and_outbox", _routed)
    client = TestClient(app)

    def _post(content: str):
        return client.post(
            "/ingest",
            json={"uuid": "ingest-1", "title": "T", "review_state": "inbox", "content": content},
        )

    assert _post("A").status_code == 200
    assert _post("A").status_code == 200  # crash-retry of the same POST: dedups
    assert len(conn.rows) == 1

    assert _post("B").status_code == 200  # content change: genuinely new event
    assert len(conn.rows) == 2

    # A→B→A byte-identical revert re-derives the first A key and dedups. Accepted:
    # distinct content — not recurrence — is the signal that emits on this path.
    assert _post("A").status_code == 200
    assert len(conn.rows) == 2

    # No observation marker is threaded, so nothing fingerprint-only leaks.
    assert all("__observation__" not in str(r["payload"]) for r in conn.rows.values())


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
