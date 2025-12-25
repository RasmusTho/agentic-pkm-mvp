from __future__ import annotations

from datetime import datetime, timezone
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
            })

    events: list[dict] = []
    monkeypatch.setattr("app.services.indexer.get_vector_index", lambda: DummyIndex())
    monkeypatch.setattr("app.services.indexer.emit_index_object_embedded", lambda event: events.append(event))

    handle_ingest_object_created(_make_event())

    assert calls
    assert any(isinstance(call["object_id"], UUID) for call in calls)
    assert events


def test_handle_ingest_object_created_logs_on_failure(monkeypatch):
    class FailingDummy:
        def upsert(self, *args, **kwargs):
            raise RuntimeError("boom")

    logged: list[str] = []
    class DummyLogger:
        def exception(self, msg, oid):
            logged.append(f"{msg} {oid}")

    monkeypatch.setattr("app.services.indexer.get_vector_index", lambda: FailingDummy())
    monkeypatch.setattr("app.services.indexer.emit_index_object_embedded", lambda event: None)
    monkeypatch.setattr("app.services.indexer.logger", DummyLogger())

    handle_ingest_object_created(_make_event())

    assert logged
