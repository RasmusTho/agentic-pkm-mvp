"""Merge-gate coverage for #2252.

These tests exercise the *real* DB-outbox consume path of the worker
(`write_outbox_event` -> `poll_outbox_one` -> dispatch -> `ack_outbox`) against an
in-memory fake connection that emulates the `outbox` table contract. They lock in
two guarantees:

1. An enqueued ``ingest.vault.changed`` row is consumed by the worker and results in
   a ``store_objects`` write (here: the in-memory ObjectStore), with
   ``processed_total`` incrementing.
2. A poison ``ingest.vault.changed`` row whose handler raises a *permanent* error is
   acked and dropped instead of crash-looping at the head of the queue and blocking
   every following row (the failure mode behind ``processed_total=0`` despite many
   ticks). At-least-once semantics are preserved for transient failures, which still
   crash-and-retry.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from app.events.types import INGEST_VAULT_CHANGED
from app.services import outbox as outbox_service
from app.services.outbox import write_outbox_event
from app.store import object_store as object_store_module
from app.store.object_store import ObjectStore
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
    """Minimal in-memory emulation of the Postgres ``outbox`` table.

    Only the SQL shapes used by ``write_outbox_event``, ``poll_outbox_one`` and
    ``ack_outbox`` are supported. Rows are stored as dicts keyed by id.
    """

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self._seq = 0

    # outbox.py routes conn.execute(sql, params) for execute-style connections.
    def execute(self, sql: str, params: tuple = ()) -> _FakeCursor:
        text = " ".join(sql.lower().split())

        if text.startswith("insert into outbox"):
            self._seq += 1
            row_id = f"row-{self._seq:04d}"
            topic = params[0]
            payload = params[1]
            created_at = params[2] if len(params) > 2 else datetime.now(timezone.utc)
            self.rows[row_id] = {
                "id": row_id,
                "topic": topic,
                "payload": payload,
                "created_at": created_at,
                "delivered_at": None,
                "attempts": 0,
            }
            return _FakeCursor([(row_id,)])

        if "from outbox where delivered_at is null" in text:
            undelivered = [r for r in self.rows.values() if r["delivered_at"] is None]
            undelivered.sort(key=lambda r: (str(r["created_at"]), r["id"]))
            if not undelivered:
                return _FakeCursor([])
            head = undelivered[0]
            return _FakeCursor([(head["id"], head["topic"], head["payload"])])

        if text.startswith("update outbox set attempts"):
            msg_id = params[0]
            row = self.rows.get(msg_id)
            if row and row["delivered_at"] is None:
                row["attempts"] = int(row.get("attempts", 0)) + 1
                return _FakeCursor([(row["attempts"],)])
            return _FakeCursor([])

        if text.startswith("update outbox set delivered_at"):
            msg_id = params[0]
            row = self.rows.get(msg_id)
            if row and row["delivered_at"] is None:
                row["delivered_at"] = datetime.now(timezone.utc)
                return _FakeCursor([(1,)])
            return _FakeCursor([])

        if "count(*) from outbox" in text:
            return _FakeCursor([(len(self.rows),)])

        # bootstrap / ensure_schema / create-table style statements are no-ops.
        return _FakeCursor([])

    def close(self) -> None:  # pragma: no cover - parity with psycopg conn
        pass

    # Test helpers
    def undelivered_count(self) -> int:
        return sum(1 for r in self.rows.values() if r["delivered_at"] is None)

    def topics(self) -> list[str]:
        return [r["topic"] for r in self.rows.values()]

    def attempts_for(self, row_id: str) -> int:
        return int(self.rows[row_id].get("attempts", 0))


@pytest.fixture()
def fake_conn(monkeypatch: pytest.MonkeyPatch) -> FakeOutboxConn:
    conn = FakeOutboxConn()
    # Route every outbox DB call through the single in-memory connection.
    monkeypatch.setattr(outbox_service, "_open_conn", lambda: conn)
    return conn


@pytest.fixture(autouse=True)
def _stub_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the indexer ingest path deterministic without an embedding provider."""
    from app.services import indexer as indexer_module

    monkeypatch.setattr(indexer_module, "llm_embed_text", lambda **_: [0.0] * 8)

    class _Identity:
        provider = "stub"
        model = "stub-model"
        dim = 8
        normalize = False

    class _VectorIndex:
        def purge_vectors(self, *_a, **_k) -> None:
            return None

        def upsert(self, *_a, **_k) -> None:
            return None

    monkeypatch.setattr(indexer_module, "get_embedding_identity", lambda: _Identity())
    monkeypatch.setattr(indexer_module, "get_vector_index", lambda: _VectorIndex())


@pytest.fixture(autouse=True)
def _clear_memory_store():
    object_store_module._MEMORY_STORE.clear()
    outbox_worker._EVENT_DEDUP._seen.clear()
    yield
    object_store_module._MEMORY_STORE.clear()


def _enqueue_ingest(note_path, *, trace_id: str) -> str:
    from app.events.models import new_event

    payload = {
        "vault_path": str(note_path),
        "relative_path": note_path.name,
        "mtime": 1.0,
        "hash": "h",
        "watcher": "registry:ingest",
        "trace_id": trace_id,
    }
    event = new_event(
        event_type=INGEST_VAULT_CHANGED,
        payload=payload,
        trace_id=trace_id,
        source="watcher.registry",
    )
    return write_outbox_event(event)


def _write_note(tmp_path, name: str = "note.md") -> Any:
    vault_root = tmp_path / "vault"
    note_path = vault_root / name
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        "---\ntitle: Repro Note\nuuid: 11111111-1111-1111-1111-111111111111\n---\n\nBody text\n",
        encoding="utf-8",
    )
    return vault_root, note_path


def test_worker_consumes_ingest_vault_changed(
    tmp_path,
    fake_conn: FakeOutboxConn,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Primary AC: an enqueued ``ingest.vault.changed`` is consumed and a
    ``store_objects`` row is written; ``processed_total`` increments."""
    vault_root, note_path = _write_note(tmp_path)
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault_root))

    row_id = _enqueue_ingest(note_path, trace_id="trace-consume")
    assert row_id
    assert fake_conn.undelivered_count() == 1

    monkeypatch.setattr(outbox_worker, "bootstrap", lambda: None)

    processed: list[int] = []

    def capture_heartbeat(**kwargs):
        processed.append(kwargs.get("processed_total", 0))

    monkeypatch.setattr(outbox_worker, "write_worker_heartbeat", capture_heartbeat)
    monkeypatch.setenv("WORKER_HEARTBEAT_INTERVAL", "0")

    outbox_worker.run(
        interval=0.0,
        heartbeat_interval=0,
        log_heartbeat_interval=None,
        stop_after_ticks=3,
    )

    # The enqueued row was consumed (delivered) ...
    assert fake_conn.undelivered_count() == 0
    # ... processed_total incremented past zero ...
    assert processed and max(processed) >= 1
    # ... and a store object was written for the note uuid.
    stored = ObjectStore().get_object("11111111-1111-1111-1111-111111111111")
    assert stored is not None
    assert stored.kind == "note"


def test_worker_does_not_head_of_line_block_on_poison_ingest_row(
    tmp_path,
    fake_conn: FakeOutboxConn,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for #2252: a permanently-failing ingest row must be acked and
    dropped, not crash-loop the worker and block every following row (the
    ``processed_total=0`` stall)."""
    vault_root, good_note = _write_note(tmp_path, name="good.md")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault_root))

    # Poison row first (points at a missing file -> handler raises a permanent error),
    # good row second. With head-of-line blocking, the good row would never run.
    poison_path = vault_root / "missing.md"
    _enqueue_ingest(poison_path, trace_id="trace-poison")
    _enqueue_ingest(good_note, trace_id="trace-good")
    assert fake_conn.undelivered_count() == 2

    # Force a *permanent* failure for the poison note path only.
    real_handler = outbox_worker.handle_ingest_vault_changed

    def flaky_handler(payload, **kwargs):
        if "missing.md" in str(payload.get("vault_path")):
            raise ValueError("permanent: malformed/poison ingest event")
        return real_handler(payload, **kwargs)

    monkeypatch.setattr(outbox_worker, "handle_ingest_vault_changed", flaky_handler)
    monkeypatch.setattr(outbox_worker, "bootstrap", lambda: None)
    monkeypatch.setattr(outbox_worker, "write_worker_heartbeat", lambda **_: None)
    monkeypatch.setenv("WORKER_HEARTBEAT_INTERVAL", "9999")
    # Small attempt budget keeps the test fast; the row dead-letters after this many
    # crash-and-retry cycles instead of blocking the queue forever.
    monkeypatch.setenv("WORKER_MAX_DISPATCH_ATTEMPTS", "3")

    # Model the supervised worker: below the poison threshold the worker crashes and is
    # restarted (each run() call == one supervised lifetime). Once the poison row's
    # attempt budget is exhausted it is dead-lettered + acked, and the loop drains the
    # good row -- proving no permanent head-of-line stall.
    for _ in range(10):
        if fake_conn.undelivered_count() == 0:
            break
        # Fresh in-process dedup set per supervised lifetime (real restarts get one).
        outbox_worker._EVENT_DEDUP._seen.clear()
        try:
            outbox_worker.run(
                interval=0.0,
                heartbeat_interval=9999,
                log_heartbeat_interval=None,
                stop_after_ticks=4,
            )
        except ValueError:
            # Transient (below-threshold) crash: supervisor would restart us.
            continue

    # Both rows are resolved (poison dead-lettered, good consumed) -> no stall.
    assert fake_conn.undelivered_count() == 0
    # The good note still made it into the store.
    stored = ObjectStore().get_object("11111111-1111-1111-1111-111111111111")
    assert stored is not None


def _transient_error_case(kind: str):
    if kind == "psycopg_operational":
        error_type = type(
            "OperationalError",
            (RuntimeError,),
            {"__module__": "psycopg"},
        )

        def build_error() -> Exception:
            return error_type("database temporarily unavailable")

        return error_type, build_error

    if kind == "http_429":
        error_type = type(
            "HTTPStatusError",
            (RuntimeError,),
            {"__module__": "httpx"},
        )

        class _Response:
            status_code = 429

        def build_error() -> Exception:
            exc = error_type("embedding provider throttled")
            exc.response = _Response()
            return exc

        return error_type, build_error

    raise AssertionError(f"unknown transient error kind: {kind}")


@pytest.mark.parametrize("transient_error_kind", ["psycopg_operational", "http_429"])
def test_transient_failures_do_not_dead_letter_legitimate_event(
    tmp_path,
    fake_conn: FakeOutboxConn,
    monkeypatch: pytest.MonkeyPatch,
    transient_error_kind: str,
) -> None:
    """Regression for #2257: infrastructure transients must not consume the
    poison-row dispatch budget and dead-letter a legitimate event."""
    vault_root, note_path = _write_note(tmp_path, name="transient.md")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault_root))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("WORKER_MAX_DISPATCH_ATTEMPTS", "3")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.delenv("STORE_BACKEND", raising=False)

    row_id = _enqueue_ingest(note_path, trace_id="trace-transient")
    assert row_id

    # Mimic optional third-party exceptions without importing them here: the worker
    # classifies by exception MRO module/name so no-psycopg unit environments work.
    transient_error_type, build_transient_error = _transient_error_case(transient_error_kind)
    real_handler = outbox_worker.handle_ingest_vault_changed
    failures_before_recovery = 5
    calls = 0

    def transient_then_recovers(payload, **kwargs):
        nonlocal calls
        calls += 1
        if calls <= failures_before_recovery:
            raise build_transient_error()
        return real_handler(payload, **kwargs)

    monkeypatch.setattr(outbox_worker, "handle_ingest_vault_changed", transient_then_recovers)
    monkeypatch.setattr(outbox_worker, "bootstrap", lambda: None)
    monkeypatch.setattr(outbox_worker, "write_worker_heartbeat", lambda **_: None)
    monkeypatch.setenv("WORKER_HEARTBEAT_INTERVAL", "9999")

    for _ in range(failures_before_recovery + 3):
        if fake_conn.undelivered_count() == 0:
            break
        outbox_worker._EVENT_DEDUP._seen.clear()
        try:
            outbox_worker.run(
                interval=0.0,
                heartbeat_interval=9999,
                log_heartbeat_interval=None,
                stop_after_ticks=4,
            )
        except transient_error_type:
            continue

    assert calls == failures_before_recovery + 1
    assert fake_conn.undelivered_count() == 0
    assert fake_conn.attempts_for(row_id) == 0
    stored = ObjectStore().get_object("11111111-1111-1111-1111-111111111111")
    assert stored is not None
    audit_text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert outbox_worker.OUTBOX_EVENT_DEAD_LETTERED not in audit_text
