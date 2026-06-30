from __future__ import annotations

from uuid import UUID

import app.store.object_store as legacy_object_store
import pytest

from app.components.embeddings import EmbeddingIdentity
from app.llm import fallback_orchestrator
from app.llm.embed_queue import EmbedDeadLetterError
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
def _reset_indexer_state() -> None:
    reset_store_backends()
    legacy_object_store._MEMORY_STORE.clear()
    yield
    reset_store_backends()
    legacy_object_store._MEMORY_STORE.clear()


def _patch_fallback(monkeypatch: pytest.MonkeyPatch, fallback_identity: EmbeddingIdentity, vector: list[float]) -> _FakeEmbeddingClient:
    fallback_client = _FakeEmbeddingClient(fallback_identity, vector)

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
    return fallback_client


def test_fallback_invoked_from_handle_ingest_object_created(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.indexer import handle_ingest_object_created

    monkeypatch.setenv("EMBED_FALLBACK_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    primary_identity = EmbeddingIdentity(provider="ollama", model="nomic-embed-text", dim=768)
    fallback_identity = EmbeddingIdentity(provider="gemini", model="gemini-embedding-001", dim=768)
    fallback_client = _patch_fallback(monkeypatch, fallback_identity, [0.25] * fallback_identity.dim)
    spy_index = _SpyVectorIndex()

    monkeypatch.setattr("app.services.indexer.get_embedding_identity", lambda: primary_identity)
    monkeypatch.setattr("app.services.indexer.get_vector_index", lambda: spy_index)
    monkeypatch.setattr("app.services.indexer.emit_index_object_embedded", lambda **kwargs: None)

    handle_ingest_object_created(
        {
            "uuid": "11111111-1111-1111-1111-111111111111",
            "content": "fallback me",
            "title": "Fallback",
            "kind": "note",
            "source_ref": "vault/fallback.md",
            "trace_id": "trace-fallback-indexer",
            "payload": {},
        }
    )

    assert fallback_client.calls == ["fallback me"]
    assert len(spy_index.upsert_calls) == 1
    assert spy_index.upsert_calls[0]["identity"].provider == "gemini"
    assert spy_index.upsert_calls[0]["model"] == fallback_identity.model
    assert spy_index.upsert_calls[0]["reconcilable_fallback"] is True


def test_fallback_emits_egress_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.indexer import handle_ingest_object_created

    monkeypatch.setenv("EMBED_FALLBACK_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    primary_identity = EmbeddingIdentity(provider="ollama", model="nomic-embed-text", dim=768)
    fallback_identity = EmbeddingIdentity(provider="gemini", model="gemini-embedding-001", dim=768)
    _patch_fallback(monkeypatch, fallback_identity, [0.5] * fallback_identity.dim)
    spy_index = _SpyVectorIndex()
    emitted: list[dict[str, object]] = []

    monkeypatch.setattr("app.services.indexer.get_embedding_identity", lambda: primary_identity)
    monkeypatch.setattr("app.services.indexer.get_vector_index", lambda: spy_index)
    monkeypatch.setattr("app.services.indexer.emit_index_object_embedded", lambda **kwargs: emitted.append(kwargs))

    handle_ingest_object_created(
        {
            "uuid": "22222222-2222-2222-2222-222222222222",
            "content": "emit provenance",
            "title": "Fallback",
            "kind": "note",
            "source_ref": "vault/fallback.md",
            "trace_id": "trace-fallback-egress",
            "payload": {},
        }
    )

    assert len(emitted) == 1
    assert emitted[0]["provider"] == "gemini"
    assert emitted[0]["model"] == "gemini-embedding-001"
    assert emitted[0]["meta"]["fallback_used"] is True
    assert emitted[0]["meta"]["primary_provider"] == "ollama"
