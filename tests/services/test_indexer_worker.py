from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

from app.services.indexer import handle_ingest_object_created
from app.store import object_store as object_store_module
from app.objects import ObjectStore


def _make_event(source_ref: str = "vault/path", trace_id: str | None = None) -> dict:
    return {
        "uuid": str(UUID(int=0)),
        "kind": "note",
        "source_ref": source_ref,
        "content": "hello world",
        "payload": {"raw_text": "hello"},
        "title": "Test",
        "review_state": "processed",
        "trace_id": trace_id,
    }


def test_handle_ingest_object_created_uses_shared_vector_index(monkeypatch):
    object_store_module._MEMORY_STORE.clear()
    calls: list[dict] = []

    class DummyIndex:
        def upsert(self, object_id, *, kind, source_ref, payload, embedding, model, identity):
            calls.append({
                "object_id": object_id,
                "kind": kind,
                "source_ref": source_ref,
                "payload": payload,
                "model": model,
                "identity": identity,
            })

        def purge_vectors(self, object_id, *, view):
            return 0

    identity = SimpleNamespace(
        provider="ollama",
        model="nomic-embed-text:latest",
        dim=768,
        normalize=True,
    )

    events: list[dict] = []
    failures: list[dict] = []
    monkeypatch.setattr("app.services.indexer.get_vector_index", lambda: DummyIndex())
    monkeypatch.setattr("app.services.indexer.emit_index_object_embedded", lambda **kwargs: events.append(kwargs))
    monkeypatch.setattr("app.services.indexer.emit_index_embedding_failed", lambda **kwargs: failures.append(kwargs))
    monkeypatch.setattr("app.services.indexer.get_embedding_identity", lambda: identity)

    event = _make_event()
    with patch("app.services.indexer.llm_embed_text") as m_embed:
        m_embed.return_value = [0.0] * identity.dim
        handle_ingest_object_created(event)
        m_embed.assert_called_once_with(
            text=event["content"],
            provider=identity.provider,
            model=identity.model,
            dim=identity.dim,
            normalize=identity.normalize,
        )

    assert calls
    assert events
    assert not failures
    assert any(isinstance(call["object_id"], UUID) for call in calls)
    stored = ObjectStore().get_object(event["uuid"])
    assert stored is not None
    assert stored.payload["artifact_id"] == event["uuid"]
    assert stored.payload["stable_id"] == event["uuid"]
    assert stored.payload["path"] == event["source_ref"]
    assert stored.payload["source_ref"] == event["source_ref"]
    assert stored.payload["language"] == "und"
    assert stored.payload["source_role"] == "note"
    assert stored.payload["trust"] == "unreviewed"
    assert stored.payload["review_state"] == event["review_state"]
    assert "embedding_identity" not in stored.payload


def test_handle_ingest_object_created_emits_failure_event(monkeypatch):
    emitted: list[dict] = []
    failures: list[dict] = []

    vector_index = MagicMock()
    monkeypatch.setattr("app.services.indexer.get_vector_index", lambda: vector_index)
    vector_index.purge_vectors.return_value = 0
    monkeypatch.setattr("app.services.indexer.emit_index_object_embedded", lambda **kwargs: emitted.append(kwargs))
    monkeypatch.setattr("app.services.indexer.emit_index_embedding_failed", lambda **kwargs: failures.append(kwargs))

    identity = SimpleNamespace(
        provider="ollama",
        model="nomic-embed-text:latest",
        dim=768,
        normalize=True,
    )
    monkeypatch.setattr("app.services.indexer.get_embedding_identity", lambda: identity)

    with patch("app.services.indexer.llm_embed_text", side_effect=ValueError("expected 768 got 1536")):
        handle_ingest_object_created(_make_event())

    assert not emitted
    assert vector_index.upsert.call_count == 0
    assert failures
    assert failures[0].get("expected_dim") == identity.dim
    assert failures[0].get("actual_dim") == 1536
    assert failures[0].get("provider") == identity.provider
    assert failures[0].get("error")


def test_handle_ingest_object_created_replaces_vectors_on_update(monkeypatch):
    from types import SimpleNamespace
    from uuid import UUID

    from app.stores import get_vector_index, reset_store_backends
    from app.stores.memory import MemoryVectorIndex

    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("EMBED_DIM", "4")
    reset_store_backends()
    identity = SimpleNamespace(provider="test", model="test-model", dim=4, normalize=True)
    monkeypatch.setattr("app.services.indexer.get_embedding_identity", lambda: identity)

    embed_vectors = [[1, 0, 0, 0], [0, 1, 0, 0]]

    def fake_embed(**kwargs):
        return embed_vectors.pop(0)

    monkeypatch.setattr("app.services.indexer.llm_embed_text", fake_embed)
    monkeypatch.setattr("app.services.indexer.emit_index_object_embedded", lambda **_: None)
    monkeypatch.setattr("app.services.indexer.emit_index_embedding_failed", lambda **_: None)

    purge_calls: list[tuple[UUID, str, int]] = []
    original_purge = MemoryVectorIndex.purge_vectors

    def track_purge(self, object_id: UUID, *, view: str) -> int:
        result = original_purge(self, object_id, view=view)
        purge_calls.append((object_id, view, result))
        return result

    monkeypatch.setattr(MemoryVectorIndex, "purge_vectors", track_purge)

    note_uuid = str(UUID(int=1))
    event = _make_event()
    event["uuid"] = note_uuid
    handle_ingest_object_created(event)

    updated_event = _make_event()
    updated_event["uuid"] = note_uuid
    updated_event["content"] = "updated content"
    handle_ingest_object_created(updated_event)

    assert len(purge_calls) == 2
    assert purge_calls[0][2] == 0
    assert purge_calls[1][2] == 1
    store = get_vector_index()
    assert len(store._entries) == 1
