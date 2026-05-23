from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from app.components.embeddings import get_embedding_client
from app.outbox import events
from app.stores import get_vector_index, reset_store_backends
from app.objects import DomainObject, ObjectStore


def test_emit_index_embedding_requested_writes_db_outbox_and_audit(tmp_path, monkeypatch) -> None:
    fake_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr(events, "INDEX_OUTBOX_PATH", fake_path, raising=False)
    db_writes: list[object] = []
    monkeypatch.setattr(events, "write_outbox_event", lambda evt, idempotency_key=None: db_writes.append((evt, idempotency_key)) or "1")

    events.emit_index_embedding_requested({"object_id": uuid4(), "trace_id": "trace-db-audit", "source": "test"})

    assert db_writes
    assert fake_path.exists()


def test_emit_index_embedding_requested_raises_when_db_outbox_write_fails(tmp_path, monkeypatch) -> None:
    fake_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr(events, "INDEX_OUTBOX_PATH", fake_path, raising=False)
    monkeypatch.setattr(events, "write_outbox_event", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db down")))

    with pytest.raises(RuntimeError, match="db down"):
        events.emit_index_embedding_requested({"object_id": uuid4(), "trace_id": "trace-db-fail", "source": "test"})

    assert not fake_path.exists()


def test_emit_index_embedding_requested_tolerates_audit_append_failure(tmp_path, monkeypatch) -> None:
    fake_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr(events, "INDEX_OUTBOX_PATH", fake_path, raising=False)
    db_writes: list[object] = []
    monkeypatch.setattr(events, "write_outbox_event", lambda evt, idempotency_key=None: db_writes.append((evt, idempotency_key)) or "1")
    monkeypatch.setattr(events, "_append_record", lambda record: (_ for _ in ()).throw(OSError("disk full")))

    events.emit_index_embedding_requested({"object_id": uuid4(), "trace_id": "trace-db-audit-fail", "source": "test"})

    assert db_writes


def test_emit_index_embedding_created_tolerates_audit_append_failure(monkeypatch) -> None:
    monkeypatch.setattr(events, "_append_record", lambda record: (_ for _ in ()).throw(OSError("audit sink unavailable")))
    events.emit_index_embedding_created(object_id=UUID("11111111-1111-1111-1111-111111111111"), trace_id="trace-created")


def test_indexer_runner_does_not_consume_jsonl_outbox_queue(tmp_path, monkeypatch, capsys) -> None:
    reset_store_backends()

    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    fake_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr(events, "INDEX_OUTBOX_PATH", fake_path, raising=False)
    monkeypatch.setattr(events, "write_outbox_event", lambda evt, idempotency_key=None: "1")

    import app.store.object_store as legacy_object_store

    legacy_object_store._MEMORY_STORE.clear()

    import app.indexer.runner as runner

    importlib.reload(runner)

    store = ObjectStore()
    ids = []
    for idx in range(2):
        oid = uuid4()
        ids.append(oid)
        store.save_object(
            DomainObject(
                uuid=str(oid),
                kind="note",
                payload={
                    "text": f"payload-{idx}",
                    "content": f"payload-{idx}",
                    "object_type": "note",
                    "system_intent": "learn",
                    "emergent_tags": [],
                },
                source_ref=f"unit-test:{idx}",
                created_at=datetime.now(timezone.utc),
            ),
            emit_outbox=False,
            trace_id="trace-123",
        )

        events.emit_index_embedding_requested({"object_id": oid, "trace_id": "trace-123", "source": "test"})

    runner.main()
    output = capsys.readouterr().out
    assert "JSONL queue consumption disabled" in output

    idx = get_vector_index()
    embedder = get_embedding_client()
    query = embedder.embed_text("payload-0")
    results = idx.search(query, k=2)

    assert not results
    lines = fake_path.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines if line.strip()]
    requested = [rec for rec in records if rec.get("event") == "index.embedding.requested"]
    created = [rec for rec in records if rec.get("event") == "index.embedding.created"]
    assert requested, "Expected request records in JSONL audit log"
    assert not created, "Runner must not process JSONL request records into created events"
