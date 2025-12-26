from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from app.services.indexer import handle_ingest_object_created


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

    identity = SimpleNamespace(provider="test", model="test-model", dim=4)

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
            event["content"],
            provider=identity.provider,
            model=identity.model,
            dim=identity.dim,
        )

    assert calls
    assert events
    assert not failures
    assert any(isinstance(call["object_id"], UUID) for call in calls)


def test_handle_ingest_object_created_emits_failure_event(monkeypatch):
    class FailingIndex:
        def upsert(self, *args, **kwargs):
            raise RuntimeError("boom")

    fired: list[dict] = []
    failure_events: list[dict] = []
    monkeypatch.setattr("app.services.indexer.get_vector_index", lambda: FailingIndex())
    monkeypatch.setattr("app.services.indexer.emit_index_object_embedded", lambda **kwargs: fired.append(kwargs))
    monkeypatch.setattr("app.services.indexer.emit_index_embedding_failed", lambda **kwargs: failure_events.append(kwargs))

    identity = SimpleNamespace(provider="test", model="test-model", dim=4)
    monkeypatch.setattr("app.services.indexer.get_embedding_identity", lambda: identity)

    with patch("app.services.indexer.llm_embed_text") as m_embed:
        m_embed.return_value = [0.0] * identity.dim
        handle_ingest_object_created(_make_event())

    assert not fired
    assert failure_events
    assert failure_events[0].get("error", "")
    assert failure_events[0].get("actual_dim")
    assert failure_events[0].get("expected_dim")
