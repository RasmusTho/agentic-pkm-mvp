from __future__ import annotations

from pathlib import Path

import pytest

from app.events.types import INGEST_OBJECT_DELETED, INGEST_VAULT_CHANGED
from app.workers import outbox_worker

pytestmark = pytest.mark.not_pg


def test_worker_run_dispatches_ingest_vault_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[dict] = []

    def fake_handle(payload, *, vault_root=None):
        called.append(dict(payload))
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

    assert called


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
