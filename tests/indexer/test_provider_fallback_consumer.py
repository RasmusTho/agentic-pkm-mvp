from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import app.objects as legacy_object_store
import pytest

from app.components.embeddings import EmbeddingIdentity
from app.index.artifact_metadata import canonicalize_indexable_text, compute_content_hash
from app.llm import fallback_orchestrator
from app.llm.embed_queue import EmbedDeadLetterError
from app.objects import DomainObject, ObjectStore
from app.outbox import events as outbox_events
from app.stores import reset_store_backends


class _SpyVectorIndex:
    def __init__(self) -> None:
        self.upsert_calls: list[dict[str, object]] = []
        self.purge_calls: list[UUID] = []

    def purge_vectors(self, object_id: UUID, *, view: str) -> int:
        del view
        self.purge_calls.append(object_id)
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


def test_process_event_embeds_and_projects_exact_canonical_bytes(monkeypatch) -> None:
    from app.indexer.consumer import process_event

    identity = EmbeddingIdentity(provider="mock", model="mock-embedding", dim=3)
    embedder = _FakeEmbeddingClient(identity, [0.1, 0.2, 0.3])
    spy_index = _SpyVectorIndex()
    monkeypatch.setattr("app.indexer.consumer.get_embeddings_client", lambda intent: embedder)
    monkeypatch.setattr("app.indexer.consumer.get_vector_index", lambda: spy_index)
    monkeypatch.setattr(
        "app.indexer.consumer.outbox_events.emit_index_embedding_created", lambda **kwargs: None
    )

    raw = "\n".join(
        (
            "retained before",
            "%% AI:Start %%",
            "fenced panel",
            "%% AI:End %%",
            "## AI-instruktion",
            "legacy panel",
            "## Retained section",
            "retained after",
        )
    )
    canonical = canonicalize_indexable_text({"content": raw})
    object_id = "44444444-4444-4444-4444-444444444444"
    ObjectStore().save_object(
        DomainObject(
            uuid=object_id,
            kind="note",
            payload={"content": raw, "text": "stale alias"},
            source_ref="vault/canonical-consumer.md",
            created_at=datetime.now(timezone.utc),
        ),
        emit_outbox=False,
    )

    process_event(
        {
            "event": outbox_events.INDEX_EMBEDDING_REQUESTED,
            "payload": {"object_id": object_id},
        }
    )

    assert embedder.calls == [canonical]
    payload = spy_index.upsert_calls[-1]["payload"]
    assert payload["content"] == canonical
    assert payload["text"] == canonical
    assert payload["provenance"]["content_hash"] == compute_content_hash(canonical)


def test_process_event_does_not_recreate_panel_only_vector(monkeypatch) -> None:
    from app.indexer.consumer import process_event

    identity = EmbeddingIdentity(provider="mock", model="mock-embedding", dim=3)
    embedder = _FakeEmbeddingClient(identity, [0.1, 0.2, 0.3])
    spy_index = _SpyVectorIndex()
    monkeypatch.setattr("app.indexer.consumer.get_embeddings_client", lambda intent: embedder)
    monkeypatch.setattr("app.indexer.consumer.get_vector_index", lambda: spy_index)

    object_id = "55555555-5555-5555-5555-555555555555"
    ObjectStore().save_object(
        DomainObject(
            uuid=object_id,
            kind="note",
            payload={"content": "\n%% AI:Start %%\ntransient\n%% AI:End %%\n\n"},
            source_ref="vault/panel-only-consumer.md",
            created_at=datetime.now(timezone.utc),
        ),
        emit_outbox=False,
    )

    process_event(
        {
            "event": outbox_events.INDEX_EMBEDDING_REQUESTED,
            "payload": {"object_id": object_id},
        }
    )

    assert embedder.calls == []
    assert spy_index.upsert_calls == []
    assert spy_index.purge_calls == [UUID(object_id)]


def test_process_event_retries_when_panel_only_purge_fails(monkeypatch) -> None:
    from app.indexer.consumer import process_event

    class FailingPurgeIndex(_SpyVectorIndex):
        def purge_vectors(self, object_id: UUID, *, view: str) -> int:
            raise ConnectionError("postgres unavailable")

    monkeypatch.setattr(
        "app.indexer.consumer.get_vector_index", lambda: FailingPurgeIndex()
    )
    object_id = "56565656-5656-5656-5656-565656565656"
    ObjectStore().save_object(
        DomainObject(
            uuid=object_id,
            kind="note",
            payload={"content": "%% AI:Start %%\ntransient\n%% AI:End %%"},
            source_ref="vault/panel-only-retry.md",
            created_at=datetime.now(timezone.utc),
        ),
        emit_outbox=False,
    )

    with pytest.raises(ConnectionError, match="postgres unavailable"):
        process_event(
            {
                "event": outbox_events.INDEX_EMBEDDING_REQUESTED,
                "payload": {"object_id": object_id},
            }
        )


def test_legacy_precomputed_event_rejects_noncanonical_source_bytes(monkeypatch) -> None:
    from app.indexer.consumer import process_event

    spy_index = _SpyVectorIndex()
    monkeypatch.setattr("app.indexer.consumer.get_vector_index", lambda: spy_index)

    object_id = "88888888-8888-8888-8888-888888888888"
    process_event(
        {
            "object_id": object_id,
            "kind": "note",
            "source_ref": "vault/legacy-precomputed-panel.md",
            "payload": {
                "content": "retained\n%% AI:Start %%\ntransient\n%% AI:End %%"
            },
            "embedding": [0.1, 0.2, 0.3],
            "model": "legacy-model",
        }
    )

    assert spy_index.upsert_calls == []
    assert spy_index.purge_calls == [UUID(object_id)]


def test_legacy_precomputed_rejection_retries_when_purge_fails(monkeypatch) -> None:
    from app.indexer.consumer import process_event

    class FailingPurgeIndex(_SpyVectorIndex):
        def purge_vectors(self, object_id: UUID, *, view: str) -> int:
            raise ConnectionError("postgres unavailable")

    monkeypatch.setattr(
        "app.indexer.consumer.get_vector_index", lambda: FailingPurgeIndex()
    )

    with pytest.raises(ConnectionError, match="postgres unavailable"):
        process_event(
            {
                "object_id": "89898989-8989-8989-8989-898989898989",
                "kind": "note",
                "source_ref": "vault/legacy-precomputed-panel-retry.md",
                "payload": {
                    "content": "retained\n%% AI:Start %%\ntransient\n%% AI:End %%"
                },
                "embedding": [0.1, 0.2, 0.3],
                "model": "legacy-model",
            }
        )
