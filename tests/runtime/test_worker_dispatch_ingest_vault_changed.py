from __future__ import annotations

from pathlib import Path

import pytest

from app.events.types import INGEST_OBJECT_DELETED, INGEST_VAULT_CHANGED, PANEL_SCAN_REQUESTED
from app.outbox.events import INDEX_EMBEDDING_REQUESTED
from app.workers import outbox_worker

pytestmark = pytest.mark.not_pg


def test_worker_run_dispatches_ingest_vault_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[dict] = []

    def fake_handle(payload, *, vault_root=None, trace_id=None):
        called.append({"payload": dict(payload), "trace_id": trace_id})
        return outbox_worker.WorkerIngestSummary(ingested=0)

    monkeypatch.setattr(outbox_worker, "handle_ingest_vault_changed", fake_handle)
    monkeypatch.setattr(outbox_worker, "bootstrap", lambda: None)
    monkeypatch.setattr(outbox_worker, "ack_outbox", lambda _msg_id: True)
    monkeypatch.setattr(outbox_worker, "write_worker_heartbeat", lambda **_: None)

    vault_root = tmp_path / "vault"
    note_path = vault_root / "Inbox" / "note.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text("---\ntitle: note\n---\n\nBody\n", encoding="utf-8")

    messages = [
        {
            "id": "1",
            "topic": INGEST_VAULT_CHANGED,
            "payload": {
                "vault_path": str(note_path),
                "relative_path": "Inbox/note.md",
                "event_id": "evt-1",
                "trace_id": "trace-1",
            },
        }
    ]

    def fake_poll():
        if messages:
            return messages.pop(0)
        return None

    monkeypatch.setattr(outbox_worker, "poll_outbox_one", fake_poll)
    monkeypatch.setenv("WORKER_HEARTBEAT_INTERVAL", "9999")

    outbox_worker.run(interval=0.0, heartbeat_interval=9999, log_heartbeat_interval=None, stop_after_ticks=2)

    assert called == [
        {
            "payload": {
                "vault_path": str(note_path),
                "relative_path": "Inbox/note.md",
                "event_id": "evt-1",
                "trace_id": "trace-1",
            },
            "trace_id": "trace-1",
        }
    ]


def test_worker_run_dispatches_ingest_object_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[dict] = []
    acked: list[str] = []

    def fake_handle_deleted(payload):
        called.append(dict(payload))

    monkeypatch.setattr(outbox_worker, "handle_ingest_object_deleted", fake_handle_deleted)
    monkeypatch.setattr(outbox_worker, "bootstrap", lambda: None)
    monkeypatch.setattr(outbox_worker, "ack_outbox", lambda msg_id: acked.append(str(msg_id)) or True)
    monkeypatch.setattr(outbox_worker, "write_worker_heartbeat", lambda **_: None)

    messages = [
        {
            "id": "del-1",
            "topic": INGEST_OBJECT_DELETED,
            "payload": {
                "uuid": "u-del-1",
                "path": "/tmp/vault/Inbox/deleted.md",
                "deleted": True,
                "event_id": "evt-del-1",
                "trace_id": "trace-del-1",
            },
        }
    ]

    def fake_poll():
        if messages:
            return messages.pop(0)
        return None

    monkeypatch.setattr(outbox_worker, "poll_outbox_one", fake_poll)
    monkeypatch.setenv("WORKER_HEARTBEAT_INTERVAL", "9999")

    outbox_worker.run(interval=0.0, heartbeat_interval=9999, log_heartbeat_interval=None, stop_after_ticks=2)

    assert called == [{"uuid": "u-del-1", "path": "/tmp/vault/Inbox/deleted.md", "deleted": True, "event_id": "evt-del-1", "trace_id": "trace-del-1"}]
    assert acked == ["del-1"]


def test_worker_run_dispatches_panel_scan_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[dict] = []
    acked: list[str] = []

    def fake_handle(payload, *, vault_root=None, trace_id=None, scan_requested_ts=None):
        called.append(dict(payload))
        return outbox_worker.WorkerPanelSummary(emitted=0, deferred=False)

    monkeypatch.setattr(outbox_worker, "handle_panel_scan_requested", fake_handle)
    monkeypatch.setattr(outbox_worker, "bootstrap", lambda: None)
    monkeypatch.setattr(outbox_worker, "ack_outbox", lambda msg_id: acked.append(str(msg_id)) or True)
    monkeypatch.setattr(outbox_worker, "write_worker_heartbeat", lambda **_: None)

    messages = [
        {
            "id": "panel-1",
            "topic": PANEL_SCAN_REQUESTED,
            "payload": {
                "vault_path": "/tmp/vault/Inbox/panel.md",
                "relative_path": "Inbox/panel.md",
                "event_id": "evt-panel-1",
                "trace_id": "trace-panel-1",
            },
        }
    ]

    def fake_poll():
        if messages:
            return messages.pop(0)
        return None

    monkeypatch.setattr(outbox_worker, "poll_outbox_one", fake_poll)
    monkeypatch.setenv("WORKER_HEARTBEAT_INTERVAL", "9999")

    outbox_worker.run(interval=0.0, heartbeat_interval=9999, log_heartbeat_interval=None, stop_after_ticks=2)

    assert called == [{"vault_path": "/tmp/vault/Inbox/panel.md", "relative_path": "Inbox/panel.md", "event_id": "evt-panel-1", "trace_id": "trace-panel-1"}]
    assert acked == ["panel-1"]


def test_worker_run_dispatches_index_embedding_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[dict] = []
    acked: list[str] = []

    def fake_process(evt):
        called.append(dict(evt))

    monkeypatch.setattr(outbox_worker, "process_indexer_event", fake_process)
    monkeypatch.setattr(outbox_worker, "bootstrap", lambda: None)
    monkeypatch.setattr(outbox_worker, "ack_outbox", lambda msg_id: acked.append(str(msg_id)) or True)
    monkeypatch.setattr(outbox_worker, "write_worker_heartbeat", lambda **_: None)

    messages = [
        {
            "id": "embed-1",
            "topic": INDEX_EMBEDDING_REQUESTED,
            "payload": {"object_id": "11111111-1111-1111-1111-111111111111", "trace_id": "trace-embed-1"},
        }
    ]

    def fake_poll():
        if messages:
            return messages.pop(0)
        return None

    monkeypatch.setattr(outbox_worker, "poll_outbox_one", fake_poll)
    monkeypatch.setenv("WORKER_HEARTBEAT_INTERVAL", "9999")

    outbox_worker.run(interval=0.0, heartbeat_interval=9999, log_heartbeat_interval=None, stop_after_ticks=2)

    assert called == [
        {
            "event": INDEX_EMBEDDING_REQUESTED,
            "payload": {"object_id": "11111111-1111-1111-1111-111111111111", "trace_id": "trace-embed-1"},
            "trace_id": "trace-embed-1",
        }
    ]
    assert acked == ["embed-1"]


def test_worker_run_preserves_trace_id_from_db_event_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[dict] = []

    def fake_process(evt):
        called.append(dict(evt))

    monkeypatch.setattr(outbox_worker, "process_indexer_event", fake_process)
    monkeypatch.setattr(outbox_worker, "bootstrap", lambda: None)
    monkeypatch.setattr(outbox_worker, "ack_outbox", lambda _msg_id: True)
    monkeypatch.setattr(outbox_worker, "write_worker_heartbeat", lambda **_: None)

    messages = [
        {
            "id": "embed-2",
            "topic": INDEX_EMBEDDING_REQUESTED,
            "payload": {"object_id": "22222222-2222-2222-2222-222222222222"},
            "event": {"trace_id": "trace-from-envelope"},
        }
    ]

    def fake_poll():
        if messages:
            return messages.pop(0)
        return None

    monkeypatch.setattr(outbox_worker, "poll_outbox_one", fake_poll)
    monkeypatch.setenv("WORKER_HEARTBEAT_INTERVAL", "9999")

    outbox_worker.run(interval=0.0, heartbeat_interval=9999, log_heartbeat_interval=None, stop_after_ticks=2)

    assert called == [
        {
            "event": INDEX_EMBEDDING_REQUESTED,
            "payload": {"object_id": "22222222-2222-2222-2222-222222222222"},
            "trace_id": "trace-from-envelope",
        }
    ]


def test_worker_run_preserves_trace_id_from_db_event_model(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[dict] = []

    class EventEnvelope:
        trace_id = "trace-from-model"

    def fake_process(evt):
        called.append(dict(evt))

    monkeypatch.setattr(outbox_worker, "process_indexer_event", fake_process)
    monkeypatch.setattr(outbox_worker, "bootstrap", lambda: None)
    monkeypatch.setattr(outbox_worker, "ack_outbox", lambda _msg_id: True)
    monkeypatch.setattr(outbox_worker, "write_worker_heartbeat", lambda **_: None)

    messages = [
        {
            "id": "embed-3",
            "topic": INDEX_EMBEDDING_REQUESTED,
            "payload": {"object_id": "33333333-3333-3333-3333-333333333333"},
            "event": EventEnvelope(),
        }
    ]

    def fake_poll():
        if messages:
            return messages.pop(0)
        return None

    monkeypatch.setattr(outbox_worker, "poll_outbox_one", fake_poll)
    monkeypatch.setenv("WORKER_HEARTBEAT_INTERVAL", "9999")

    outbox_worker.run(interval=0.0, heartbeat_interval=9999, log_heartbeat_interval=None, stop_after_ticks=2)

    assert called == [
        {
            "event": INDEX_EMBEDDING_REQUESTED,
            "payload": {"object_id": "33333333-3333-3333-3333-333333333333"},
            "trace_id": "trace-from-model",
        }
    ]
