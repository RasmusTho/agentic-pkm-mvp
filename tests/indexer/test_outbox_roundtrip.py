from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.outbox import events


def test_emit_index_embedding_requested_writes_db_outbox_and_audit(tmp_path, monkeypatch) -> None:
    fake_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr(events, "INDEX_OUTBOX_PATH", fake_path, raising=False)
    db_writes: list[object] = []
    monkeypatch.setattr(events, "write_outbox_event", lambda evt, idempotency_key=None: db_writes.append((evt, idempotency_key)) or "1")

    events.emit_index_embedding_requested({"object_id": uuid4(), "trace_id": "trace-db-audit", "source": "test"})

    assert db_writes
    assert fake_path.exists()


def test_emit_index_embedding_requested_raises_when_db_outbox_write_fails(tmp_path, monkeypatch) -> None:
    fake_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr(events, "INDEX_OUTBOX_PATH", fake_path, raising=False)
    monkeypatch.setattr(events, "write_outbox_event", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db down")))

    with pytest.raises(RuntimeError, match="db down"):
        events.emit_index_embedding_requested({"object_id": uuid4(), "trace_id": "trace-db-fail", "source": "test"})

    assert not fake_path.exists()


def test_emit_index_embedding_requested_tolerates_audit_append_failure(tmp_path, monkeypatch) -> None:
    fake_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr(events, "INDEX_OUTBOX_PATH", fake_path, raising=False)
    db_writes: list[object] = []
    monkeypatch.setattr(events, "write_outbox_event", lambda evt, idempotency_key=None: db_writes.append((evt, idempotency_key)) or "1")
    monkeypatch.setattr(events, "_append_record", lambda record: (_ for _ in ()).throw(OSError("disk full")))

    events.emit_index_embedding_requested({"object_id": uuid4(), "trace_id": "trace-db-audit-fail", "source": "test"})

    assert db_writes


def test_emit_index_embedding_created_tolerates_audit_append_failure(monkeypatch) -> None:
    monkeypatch.setattr(events, "_append_record", lambda record: (_ for _ in ()).throw(OSError("audit sink unavailable")))
    events.emit_index_embedding_created(object_id=UUID("11111111-1111-1111-1111-111111111111"), trace_id="trace-created")


