from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from jsonschema import validate

from app.components.embeddings import get_embedding_client
from app.outbox import events
from app.stores import get_vector_index, reset_store_backends
from app.store.object_store import DomainObject, ObjectStore


def _load_schema(name: str) -> dict:
    schema_path = Path("app/events/schemas") / f"{name}.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def test_indexer_runner_consumes_outbox_without_vectors(tmp_path, monkeypatch) -> None:
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

    idx = get_vector_index()
    embedder = get_embedding_client()
    query = embedder.embed_text("payload-0")
    results = idx.search(query, k=2)

    assert results
    assert results[0].payload["text"] == "payload-0"

    # Indexer emitted a schema-aligned index.embedding.created record (no embedding vectors).
    lines = fake_path.read_text(encoding="utf-8").splitlines()
    assert lines
    records = [json.loads(line) for line in lines if line.strip()]
    created = [rec for rec in records if rec.get("event") == "index.embedding.created"]
    assert created, "Expected an index.embedding.created record"

    rec = created[-1]
    assert "embedding" not in rec
    assert "embedding" not in rec.get("payload", {})

    schema = _load_schema("index.embedding.created")
    validate(instance=rec, schema=schema)
