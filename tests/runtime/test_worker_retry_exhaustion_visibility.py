from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app
from app.events.types import INGEST_VAULT_CHANGED
from app.workers import outbox_worker
from tests.helpers.pkm_alpha_helper import reset_memory_stores


DEAD_LETTER_TOPIC = "outbox.event.dead_lettered"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _exhausted_ingest_payload(note_path: Path) -> dict[str, object]:
    return {
        "vault_path": str(note_path),
        "relative_path": "Inbox/missing.md",
        "hash": "test-hash",
        "mtime": 123.0,
        "event_id": "evt-original-1890",
        "_worker_retry_count": 3,
    }


def test_retry_exhaustion_emits_dead_letter_signal(tmp_path: Path, monkeypatch) -> None:
    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)

    outbox_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))

    vault_root = tmp_path / "vault"
    (vault_root / "Inbox").mkdir(parents=True, exist_ok=True)
    note_path = vault_root / "Inbox" / "missing.md"

    summary = outbox_worker.handle_ingest_vault_changed(
        _exhausted_ingest_payload(note_path),
        vault_root=vault_root,
        trace_id="trace-dead-letter-1890",
    )

    assert summary.ingested == 0
    records = _read_jsonl(outbox_path)
    assert len(records) == 1
    record = records[0]
    assert record["event"] == DEAD_LETTER_TOPIC
    assert record["trace_id"] == "trace-dead-letter-1890"
    assert record["source"] == "worker"
    assert record["payload"] == {
        "original_topic": INGEST_VAULT_CHANGED,
        "original_event_id": "evt-original-1890",
        "note_path": str(note_path),
        "reason": "missing_or_unstable_note",
        "retry_count": 3,
    }


def test_dead_letter_signal_visible_in_events_tail(tmp_path: Path, monkeypatch) -> None:
    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)

    outbox_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))

    vault_root = tmp_path / "vault"
    (vault_root / "Inbox").mkdir(parents=True, exist_ok=True)
    note_path = vault_root / "Inbox" / "missing.md"

    outbox_worker.handle_ingest_vault_changed(
        _exhausted_ingest_payload(note_path),
        vault_root=vault_root,
        trace_id="trace-dead-letter-tail-1890",
    )

    client = TestClient(app)
    resp = client.get("/api/events/tail", params={"event_prefix": "outbox.event", "limit": 5})

    assert resp.status_code == 200
    data = resp.json()
    assert data["source_path"] == str(outbox_path)
    assert data["count"] == 1
    [event] = data["events"]
    assert event["event"] == DEAD_LETTER_TOPIC
    assert event["payload"]["original_topic"] == INGEST_VAULT_CHANGED
    assert event["payload"]["original_event_id"] == "evt-original-1890"
    assert event["payload"]["reason"] == "missing_or_unstable_note"
