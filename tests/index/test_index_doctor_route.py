from __future__ import annotations

import os
from uuid import uuid4

import pytest

from app.index.doctor import diagnose_index, reset_diagnose_cache
from app.settings.models import SettingsBundle


def _pg_available() -> bool:
    import psycopg

    from app.db.dsn import resolve_dsn

    url = resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")
    try:
        conn = psycopg.connect(url, connect_timeout=1)
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _isolate_llm_routing_settings(monkeypatch) -> None:
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: SettingsBundle())


def test_index_doctor_expected_identity_uses_router(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_MODEL", "embed-test")
    monkeypatch.setenv("EMBED_DIM", "12")

    result = diagnose_index()
    expected = result.get("expected_identity") or {}

    assert expected.get("provider") == "mock"
    assert expected.get("model") == "mock-embedding"
    assert expected.get("dim") == 12


def test_index_doctor_reports_rebuild_fields(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_MODEL", "embed-test")
    monkeypatch.setenv("EMBED_DIM", "12")

    result = diagnose_index()

    assert "rebuild_required" in result
    assert "compatible_identity" in result
    assert "empty_index" in result


@pytest.mark.pg
def test_doctor_reports_indexed(tmp_path, monkeypatch) -> None:
    """Gate-0 AC2: after a seeded embedded vault, doctor reports a healthy index.

    Drives the durable spine (save -> request -> consumer embed/upsert into the
    Postgres ``store_vector_index``) and asserts ``diagnose_index()`` reports
    ``rebuild_required=False`` and ``empty_index=False`` for the seeded,
    identity-compatible index.
    """
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    from datetime import datetime, timezone

    from app.db.dsn import resolve_dsn
    from app.indexer.consumer import process_event as process_indexer_event
    from app.objects import DomainObject, ObjectStore
    from app.outbox import events
    from app.outbox.events import INDEX_EMBEDDING_REQUESTED
    from app.services.outbox import ack_outbox, poll_outbox_one
    from app.stores import reset_store_backends

    dsn = resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")
    reset_store_backends()
    reset_diagnose_cache()
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_MODEL", "embed-test")
    monkeypatch.setenv("EMBED_DIM", "8")

    fake_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr(events, "INDEX_OUTBOX_PATH", fake_path, raising=False)

    import app.store.object_store as legacy_object_store

    legacy_object_store._MEMORY_STORE.clear()

    store = ObjectStore()
    oid = uuid4()
    store.save_object(
        DomainObject(
            uuid=str(oid),
            kind="note",
            payload={"text": "doctor seed payload", "content": "doctor seed payload"},
            source_ref="unit-test:doctor-indexed",
            created_at=datetime.now(timezone.utc),
        ),
        emit_outbox=False,
        trace_id="trace-doctor-indexed",
    )
    events.emit_index_embedding_requested(
        {"object_id": oid, "trace_id": "trace-doctor-indexed", "source": "test"}
    )

    legacy_object_store._MEMORY_STORE.clear()

    # Drain through the same dispatch path the worker uses.
    for _ in range(50):
        message = poll_outbox_one()
        if not message:
            break
        if message.get("topic") == INDEX_EMBEDDING_REQUESTED:
            process_indexer_event(
                {
                    "event": INDEX_EMBEDDING_REQUESTED,
                    "payload": dict(message.get("payload") or {}),
                    "trace_id": "trace-doctor-indexed",
                }
            )
        ack_outbox(message["id"])

    reset_diagnose_cache()
    result = diagnose_index()

    assert result["empty_index"] is False
    assert result["rebuild_required"] is False

    reset_store_backends()
