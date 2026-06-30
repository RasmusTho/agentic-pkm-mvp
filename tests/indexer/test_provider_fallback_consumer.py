from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import app.store.object_store as legacy_object_store
import pytest

from app.components.embeddings import EmbeddingIdentity
from app.llm import fallback_orchestrator
from app.llm.embed_queue import EmbedDeadLetterError
from app.objects import DomainObject, ObjectStore
from app.outbox import events as outbox_events
from app.stores import reset_store_backends


class _SpyVectorIndex:
    def __init__(self) -> None:
        self.upsert_calls: list[dict[str, object]] = []

    def purge_vectors(self, object_id: UUID, *, view: str) -> int:
        del object_id, view
        return 0

    def upsert(self, object_id: UUID, **kwargs) -> None:
        call = dict(kwargs)
        call["object_id"] = object_id
        self.upsert_calls.append(call)


class _FakeEmbeddingClient:
    def __init__(self, identity: EmbeddingIdentity, vector: list[float]) -> None:
        self.identity = identity
        self._vector = vector
        self.calls: list[str] = []

    def embed_text(self, text: str) -> list[float]:
        self.calls.append(text)
        return list(self._vector)


@pytest.fixture(autouse=True)
def _reset_consumer_state() -> None:
    reset_store_backends()
    legacy_object_store._MEMORY_STORE.clear()
    yield
    reset_store_backends()
    legacy_object_store._MEMORY_STORE.clear()


def test_fallback_invoked_from_process_event(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.indexer.consumer import process_event

    monkeypatch.setenv("EMBED_FALLBACK_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    primary_identity = EmbeddingIdentity(provider="ollama", model="nomic-embed-text", dim=768)
    fallback_identity = EmbeddingIdentity(provider="gemini", model="gemini-embedding-001", dim=768)
    primary_embedder = _FakeEmbeddingClient(primary_identity, [0.0] * primary_identity.dim)
    fallback_client = _FakeEmbeddingClient(fallback_identity, [0.75] * fallback_identity.dim)
    spy_index = _SpyVectorIndex()
    created_events: list[dict[str, object]] = []

    attempts = {"count": 0}

    def fake_embed_with_retry(*args, embed_callable=None, **kwargs):
        del args, kwargs
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise EmbedDeadLetterError("primary exhausted")
        assert embed_callable is not None
        return list(embed_callable())

    monkeypatch.setattr(fallback_orchestrator, "embed_with_retry", fake_embed_with_retry)
    monkeypatch.setattr(fallback_orchestrator, "_resolve_fallback_identity", lambda provider: fallback_identity)
    monkeypatch.setattr(fallback_orchestrator, "get_embedding_client", lambda **kwargs: fallback_client)
    monkeypatch.setattr("app.indexer.consumer.get_embeddings_client", lambda intent: primary_embedder)
    monkeypatch.setattr("app.indexer.consumer.get_vector_index", lambda: spy_index)
    monkeypatch.setattr(
        "app.indexer.consumer.outbox_events.emit_index_embedding_created",
        lambda **kwargs: created_events.append(kwargs),
    )

    object_id = "33333333-3333-3333-3333-333333333333"
    ObjectStore().save_object(
        DomainObject(
            uuid=object_id,
            kind="note",
            payload={"content": "consumer fallback"},
            source_ref="vault/consumer.md",
            created_at=datetime.now(timezone.utc),
        ),
        emit_outbox=False,
        trace_id="trace-consumer-fallback",
    )

    process_event(
        {
            "event": outbox_events.INDEX_EMBEDDING_REQUESTED,
            "payload": {"object_id": object_id},
            "trace_id": "trace-consumer-fallback",
        }
    )

    assert fallback_client.calls == ["consumer fallback"]
    assert len(spy_index.upsert_calls) == 1
    assert spy_index.upsert_calls[0]["identity"].provider == "gemini"
    assert spy_index.upsert_calls[0]["model"] == fallback_identity.model
    assert spy_index.upsert_calls[0]["reconcilable_fallback"] is True
    assert len(created_events) == 1
    assert created_events[0]["provider"] == "gemini"
    assert created_events[0]["meta"]["fallback_used"] is True
