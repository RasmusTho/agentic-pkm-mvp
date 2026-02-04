from __future__ import annotations

from pathlib import Path

import pytest

from app.events.types import INGEST_VAULT_CHANGED
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
