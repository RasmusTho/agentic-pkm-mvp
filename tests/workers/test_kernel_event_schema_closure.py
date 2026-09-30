"""Worker dispatch + retry compatibility for the closed kernel topic schemas (#5704).

Drives the production ``outbox_worker.run_once`` tick end to end — real
``poll_outbox_one``, ``_dispatch_topic`` validation, ``_queue_transient_retry``,
``write_outbox_event`` and ``ack_outbox`` — over an in-memory ``outbox`` table
standing in for the database connection. Only the file-stability probe and,
where a test needs to observe dispatch, the topic handler are replaced.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest

from app.events.models import new_event
from app.events.types import INGEST_VAULT_CHANGED, PANEL_SCAN_REQUESTED
from app.services import outbox as outbox_service
from app.services.outbox import write_outbox_event
from app.workers import outbox_worker

pytestmark = pytest.mark.not_pg

_RETRY_KEYS = ("_worker_retry_count", "_worker_retry_reason", "_worker_retry_enqueued_at")


class _OutboxTable:
    """Autocommit in-memory ``outbox`` table for the statements the worker tick issues."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    # connection protocol -------------------------------------------------
    def cursor(self) -> "_OutboxTable":
        return self

    def execute(self, sql: str, params: tuple = ()) -> "_OutboxTable":
        text = " ".join(sql.lower().split())
        self._result: list[tuple] = []
        if text.startswith("insert into outbox"):
            row_id, topic, payload, _created, attempts, _legacy, binding, *_ = params
            if not any(r["id"] == row_id for r in self.rows):
                self.rows.append(
                    {
                        "id": row_id,
                        "topic": topic,
                        "payload": payload,
                        "attempts": attempts,
                        "vault_binding_id": binding,
                        "delivered_at": None,
                    }
                )
                self._result = [(row_id,)]
        elif text.startswith("select id, topic, payload, vault_binding_id from outbox"):
            pending = [r for r in self.rows if r["delivered_at"] is None]
            if pending:
                r = pending[0]
                self._result = [(r["id"], r["topic"], r["payload"], r["vault_binding_id"])]
        elif text.startswith("update outbox set delivered_at"):
            for r in self.rows:
                if r["id"] == params[0] and r["delivered_at"] is None:
                    r["delivered_at"] = "acked"
                    self._result = [(1,)]
        elif text.startswith("update outbox set attempts"):
            for r in self.rows:
                if r["id"] == params[0]:
                    r["attempts"] += 1
                    self._result = [(r["attempts"],)]
        return self

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)

    def transaction(self):
        return nullcontext()

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass

    # helpers -------------------------------------------------------------
    def seed(self, row_id: str, topic: str, payload: dict[str, Any], meta: dict[str, Any] | None) -> None:
        event = new_event(event_type=topic, payload=payload, meta=meta)
        self.execute(
            "insert into outbox",
            (row_id, topic, event.model_dump_json(), "t0", 0, row_id, "compatibility", row_id),
        )

    def stored(self, row: dict[str, Any]) -> dict[str, Any]:
        return json.loads(row["payload"])

    def pending(self, topic: str) -> list[dict[str, Any]]:
        return [r for r in self.rows if r["topic"] == topic and r["delivered_at"] is None]


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _OutboxTable:
    vault = tmp_path / "vault"
    (vault / "inbox").mkdir(parents=True)
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.delenv("WATCHER_VAULT_PATH", raising=False)
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused-in-test")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "index-outbox.jsonl"))
    conn = _OutboxTable()
    monkeypatch.setattr(outbox_service, "_open_conn", lambda: conn)
    monkeypatch.setattr(outbox_worker, "open_outbox_txn_conn", lambda: None)
    monkeypatch.setattr(outbox_worker, "_draft_schema_violation_case", lambda **_: None)
    monkeypatch.setattr(outbox_worker, "resolve_scalar_binding_runtime", lambda **_: None)
    outbox_worker._EVENT_DEDUP._seen.clear()
    return conn


def _watch_payload(vault: Path, **extra: Any) -> dict[str, Any]:
    return {
        "vault_path": str(vault / "inbox" / "n.md"),
        "relative_path": "inbox/n.md",
        "mtime": 1727740800.5,
        "hash": "abc",
        "watcher": "inbox",
        **extra,
    }


def _tick() -> None:
    result = outbox_worker.run_once(vault_root=None)
    assert result.state == "processed", result


def _daemon_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    """One tick of the production ``run()`` loop (which copies event_id into the payload)."""
    monkeypatch.setattr(outbox_worker, "bootstrap", lambda: None)
    monkeypatch.setattr(outbox_worker, "write_worker_heartbeat", lambda **_: None)
    outbox_worker.run(
        interval=0.0,
        heartbeat_interval=9999,
        log_heartbeat_interval=None,
        stop_after_ticks=1,
    )


def _vault() -> Path:
    import os

    return Path(os.environ["VAULT_ROOT"])


def _record_dispatch(monkeypatch: pytest.MonkeyPatch, name: str) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    def _record(payload, **kwargs):  # type: ignore[no-untyped-def]
        seen.append({"payload": dict(payload), "payload_schema": kwargs.get("payload_schema")})

    monkeypatch.setattr(outbox_worker, name, _record)
    return seen


def test_strict_payload_violation_dead_letters_before_handler(
    table: _OutboxTable, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _must_not_run(*_a: Any, **_k: Any) -> None:  # pragma: no cover - must never run
        raise AssertionError("handler or retry must not run on a strict schema violation")

    monkeypatch.setattr(outbox_worker, "handle_panel_scan_requested", _must_not_run)
    monkeypatch.setattr(outbox_worker, "_queue_transient_retry", _must_not_run)
    bump_calls: list[Any] = []
    monkeypatch.setattr(outbox_worker, "bump_outbox_attempts", lambda *a, **k: bump_calls.append(a) or 1)

    # Undeclared top-level field on a row tagged with the closed v2 contract.
    table.seed(
        "row-strict",
        PANEL_SCAN_REQUESTED,
        _watch_payload(_vault(), surprise="undeclared"),
        {"payload_schema": "panel.scan.requested.v2"},
    )

    _tick()

    source = next(r for r in table.rows if r["id"] == "row-strict")
    assert source["delivered_at"] == "acked"
    assert source["attempts"] == 0 and bump_calls == []  # no retry budget consumed
    assert table.pending(PANEL_SCAN_REQUESTED) == []  # no transient retry row
    (dead_letter,) = [r for r in table.rows if r["topic"] == outbox_worker.OUTBOX_EVENT_DEAD_LETTERED]
    stored = table.stored(dead_letter)["payload"]
    assert stored["reason"] == "schema_violation"
    assert stored["outbox_id"] == "row-strict"
    assert "panel.scan.requested.v2" in stored["error"]


@pytest.mark.parametrize("topic", [PANEL_SCAN_REQUESTED, INGEST_VAULT_CHANGED])
def test_worker_retry_round_trip_preserves_schema_compatibility(
    table: _OutboxTable, monkeypatch: pytest.MonkeyPatch, topic: str
) -> None:
    # A new, valid producer write lands as a strict v2 row through the real seam.
    write_outbox_event(new_event(event_type=topic, payload=_watch_payload(_vault())), idempotency_key="src")
    (source,) = table.rows
    assert table.stored(source)["meta"]["payload_schema"] == f"{topic}.v2"

    # First tick (daemon loop): the real handler finds the note unstable and
    # re-emits it, including the event_id run() copied into the payload.
    monkeypatch.setattr(outbox_worker, "_stabilized_note_text", lambda *_a, **_k: None)
    _daemon_tick(monkeypatch)
    assert source["delivered_at"] == "acked"
    (retry_row,) = table.pending(topic)
    retry = table.stored(retry_row)
    assert retry["meta"]["payload_schema"] == f"{topic}.v2"
    assert retry["payload"]["_worker_retry_count"] == 1
    assert isinstance(retry["payload"]["_worker_retry_reason"], str)
    assert isinstance(retry["payload"]["_worker_retry_enqueued_at"], str)
    assert retry["payload"]["event_id"] == table.stored(source)["event_id"]

    # Second tick: the retry row passes strict dispatch validation and reaches the handler.
    handler = "handle_panel_scan_requested" if topic == PANEL_SCAN_REQUESTED else "handle_ingest_vault_changed"
    seen = _record_dispatch(monkeypatch, handler)
    _daemon_tick(monkeypatch)
    assert [s["payload_schema"] for s in seen] == [f"{topic}.v2"]
    assert all(key in seen[0]["payload"] for key in _RETRY_KEYS)
    assert [r for r in table.rows if r["topic"] == outbox_worker.OUTBOX_EVENT_DEAD_LETTERED] == []


@pytest.mark.parametrize(
    ("meta", "expected_tag"),
    [
        ({"payload_schema": "panel.scan.requested.v1"}, "panel.scan.requested.v1"),
        ({"schema_version": "panel.scan.requested.v1"}, "panel.scan.requested.v1"),
        (None, None),  # untagged pre-registry v0 row
    ],
)
def test_legacy_versions_and_v0_keep_dispatch_semantics(
    table: _OutboxTable, monkeypatch: pytest.MonkeyPatch, meta: dict[str, Any] | None, expected_tag: str | None
) -> None:
    # Valid under the open v1 contract, invalid under closed v2 (undeclared field).
    legacy_payload = _watch_payload(_vault(), legacy_extra="kept")
    table.seed("row-legacy", PANEL_SCAN_REQUESTED, legacy_payload, meta)

    monkeypatch.setattr(outbox_worker, "_stabilized_note_text", lambda *_a, **_k: None)
    _tick()

    # Not dead-lettered: the real handler ran and queued a transient retry.
    assert [r for r in table.rows if r["topic"] == outbox_worker.OUTBOX_EVENT_DEAD_LETTERED] == []
    (retry_row,) = table.pending(PANEL_SCAN_REQUESTED)
    retry = table.stored(retry_row)
    assert retry["payload"]["legacy_extra"] == "kept"
    assert retry["payload"]["_worker_retry_count"] == 1
    # The retry keeps the source row's version: v1 stays v1, v0 stays untagged.
    assert (retry.get("meta") or {}).get("payload_schema") == expected_tag

    seen = _record_dispatch(monkeypatch, "handle_panel_scan_requested")
    _tick()
    assert len(seen) == 1
    assert seen[0]["payload"]["legacy_extra"] == "kept"
    assert seen[0]["payload_schema"] == (expected_tag or "v0")
    assert [r for r in table.rows if r["topic"] == outbox_worker.OUTBOX_EVENT_DEAD_LETTERED] == []

    # A legacy-tagged row still hard-fails on a violation of its OWN (v1) contract,
    # while the same violation on an untagged v0 row stays log-only.
    table.seed("row-legacy-bad", PANEL_SCAN_REQUESTED, {"hash": "no-path"}, meta)
    _tick()
    dead = [r for r in table.rows if r["topic"] == outbox_worker.OUTBOX_EVENT_DEAD_LETTERED]
    if expected_tag is None:
        assert dead == [] and len(seen) == 2
    else:
        assert len(dead) == 1 and len(seen) == 1
        assert "panel.scan.requested.v1" in table.stored(dead[0])["payload"]["error"]
