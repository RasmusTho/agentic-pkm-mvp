from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

from app.services.indexer import handle_ingest_object_created
from app import objects as object_store_module
from app.index.artifact_metadata import canonicalize_indexable_text, compute_content_hash
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


def test_handle_ingest_object_created_preserves_source_and_indexes_canonical_bytes(monkeypatch):
    object_store_module._MEMORY_STORE.clear()
    calls: list[dict] = []
    embedded_texts: list[str] = []

    class DummyIndex:
        def purge_vectors(self, object_id, *, view):
            return 0

        def upsert(self, object_id, **kwargs):
            calls.append({"object_id": object_id, **kwargs})

    identity = SimpleNamespace(provider="mock", model="mock-embedding", dim=3, normalize=True)
    monkeypatch.setattr("app.services.indexer.get_vector_index", lambda: DummyIndex())
    monkeypatch.setattr("app.services.indexer.get_embedding_identity", lambda: identity)
    monkeypatch.setattr("app.services.indexer.emit_index_object_embedded", lambda **kwargs: None)
    monkeypatch.setattr("app.services.indexer.emit_index_embedding_failed", lambda **kwargs: None)

    def fake_embed(**kwargs):
        embedded_texts.append(kwargs["text"])
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr("app.services.indexer.llm_embed_text", fake_embed)

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
    event = _make_event(source_ref="vault/canonical-indexer.md")
    event["uuid"] = "66666666-6666-6666-6666-666666666666"
    event["content"] = raw

    handle_ingest_object_created(event)

    source = ObjectStore().get_object(event["uuid"])
    assert source is not None
    assert source.payload["content"] == raw
    assert embedded_texts == [canonical]
    vector_payload = calls[-1]["payload"]
    assert vector_payload["content"] == canonical
    assert vector_payload["text"] == canonical
    assert vector_payload["provenance"]["content_hash"] == compute_content_hash(canonical)


def test_handle_ingest_object_created_does_not_recreate_panel_only_vector(monkeypatch):
    object_store_module._MEMORY_STORE.clear()
    purge_calls: list[tuple[UUID, str]] = []

    class DummyIndex:
        def purge_vectors(self, object_id, *, view):
            purge_calls.append((object_id, view))
            return 1

        def upsert(self, object_id, **kwargs):
            raise AssertionError("panel-only source must not be upserted")

    monkeypatch.setattr("app.services.indexer.get_vector_index", lambda: DummyIndex())
    monkeypatch.setattr(
        "app.services.indexer.get_embedding_identity",
        lambda: (_ for _ in ()).throw(
            AssertionError("panel-only source must not resolve an embedding identity")
        ),
    )

    panel_only = "\n%% AI:Start %%\ntransient\n%% AI:End %%\n\n"
    event = _make_event(source_ref="vault/panel-only-indexer.md")
    event["uuid"] = "77777777-7777-7777-7777-777777777777"
    event["content"] = panel_only

    handle_ingest_object_created(event)

    source = ObjectStore().get_object(event["uuid"])
    assert source is not None
    assert source.payload["content"] == panel_only
    assert purge_calls == [(UUID(event["uuid"]), "markdown.semantic")]


def test_handle_ingest_object_created_uses_raw_text_fallback_bytes(monkeypatch):
    object_store_module._MEMORY_STORE.clear()
    embedded_texts: list[str] = []
    vector_payloads: list[dict] = []

    class DummyIndex:
        def purge_vectors(self, object_id, *, view):
            return 0

        def upsert(self, object_id, **kwargs):
            vector_payloads.append(kwargs["payload"])

    identity = SimpleNamespace(provider="mock", model="mock-embedding", dim=3, normalize=True)
    monkeypatch.setattr("app.services.indexer.get_vector_index", lambda: DummyIndex())
    monkeypatch.setattr("app.services.indexer.get_embedding_identity", lambda: identity)
    monkeypatch.setattr("app.services.indexer.emit_index_object_embedded", lambda **kwargs: None)

    def fake_embed(**kwargs):
        embedded_texts.append(kwargs["text"])
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr("app.services.indexer.llm_embed_text", fake_embed)

    event = _make_event(source_ref="vault/raw-text-fallback.md")
    event["uuid"] = "99999999-9999-9999-9999-999999999999"
    event["content"] = ""
    event["payload"] = {"raw_text": "raw fallback bytes"}

    handle_ingest_object_created(event)

    assert embedded_texts == ["raw fallback bytes"]
    assert vector_payloads[-1]["content"] == "raw fallback bytes"
    assert vector_payloads[-1]["text"] == "raw fallback bytes"
    assert vector_payloads[-1]["provenance"]["content_hash"] == compute_content_hash(
        "raw fallback bytes"
    )
