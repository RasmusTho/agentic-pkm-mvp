from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from app.components.embeddings import get_embedding_client
from app.outbox import events
from app.stores import get_vector_index, reset_store_backends
from app.store.object_store import DomainObject, ObjectStore


def test_indexer_runner_does_not_consume_jsonl_outbox_queue(tmp_path, monkeypatch, capsys) -> None:
    reset_store_backends()

    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    fake_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr(events, "INDEX_OUTBOX_PATH", fake_path, raising=False)

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
