from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.objects import (
    DomainObject,
    ObjectStore,
    save_object_in_transaction,
    update_object_source_ref_in_transaction,
)


class FakeCanonicalStore:
    def __init__(self, record: dict | None = None, rows: list[dict] | None = None):
        self.record = record
        self.rows = rows or []

    def get(self, object_id):
        return self.record

    def put(self, object_id, *, kind: str, source_ref: str, payload: dict) -> None:
        self.record = {
            "object_id": object_id,
            "kind": kind,
            "source_ref": source_ref,
            "payload": payload,
            "created_at": datetime.now(timezone.utc),
        }

    def list_objects(self, kind: str | None = None, *, limit: int = 100):
        rows = list(self.rows)
        if kind is not None:
            rows = [row for row in rows if row.get("kind") == kind]
        return rows[:limit]

    def count_objects(self, kind: str | None = None) -> int:
        if kind is None:
            return len(self.rows)
        return sum(1 for row in self.rows if row.get("kind") == kind)


def test_get_object_uses_explicit_memory_backend(monkeypatch):
    obj = DomainObject(
        uuid="mem-1",
        kind="capture_note",
        payload={"plane": "vault"},
        source_ref="vault://Inbox/note.md",
        created_at=datetime.now(timezone.utc),
    )
    from app import objects as legacy

    legacy._MEMORY_STORE.clear()
    legacy._MEMORY_STORE[obj.uuid] = obj
    monkeypatch.setattr(
        "app.objects.resolve_object_store_port",
        lambda: _fake_binding("memory", FakeCanonicalStore()),
    )

    got = ObjectStore().get_object("mem-1")
    assert got is not None
    assert got.uuid == "mem-1"


def test_save_object_raises_when_port_resolution_fails(monkeypatch):
    """Fail-loud (KERNEL-03 / I-S4): no silent in-memory fallback on store errors."""
    import pytest

    from app import objects as legacy

    legacy._MEMORY_STORE.clear()
    monkeypatch.setattr(
        "app.objects.resolve_object_store_port",
        lambda: (_ for _ in ()).throw(RuntimeError("missing dsn")),
    )
    obj = DomainObject(
        uuid="fallback-1",
        kind="capture_note",
        payload={"plane": "vault"},
        source_ref="vault://Inbox/fallback.md",
        created_at=datetime.now(timezone.utc),
    )

    with pytest.raises(RuntimeError, match="missing dsn"):
        ObjectStore().save_object(obj, emit_outbox=False, trace_id="test")

    assert "fallback-1" not in legacy._MEMORY_STORE


def test_transactional_writes_evict_explicit_memory_entries(monkeypatch):
    from app import objects as legacy

    object_id = str(uuid4())
    cached = DomainObject(
        uuid=object_id,
        kind="note",
        payload={"version": "stale"},
        source_ref="old.md",
        created_at=datetime.now(timezone.utc),
    )
    legacy._MEMORY_STORE[object_id] = cached
    monkeypatch.setattr("app.stores.pg.put_object_with_connection", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "app.stores.pg.update_object_source_ref_with_connection", lambda *_a, **_k: None
    )

    save_object_in_transaction(object(), cached)
    assert object_id not in legacy._MEMORY_STORE

    legacy._MEMORY_STORE[object_id] = cached
    update_object_source_ref_in_transaction(object(), object_id=object_id, source_ref="new.md")
    assert object_id not in legacy._MEMORY_STORE


def test_postgres_reads_ignore_stale_process_memory(monkeypatch):
    from app import objects as legacy

    oid = uuid4()
    legacy._MEMORY_STORE[str(oid)] = DomainObject(
        uuid=str(oid),
        kind="note",
        payload={"version": "stale"},
        source_ref="old.md",
        created_at=datetime.now(timezone.utc),
    )
    durable = {
        "object_id": oid,
        "kind": "note",
        "payload": {"version": "committed"},
        "source_ref": "new.md",
        "created_at": datetime.now(timezone.utc),
    }
    monkeypatch.setattr(
        "app.objects.resolve_object_store_port",
        lambda: _fake_binding("pg", FakeCanonicalStore(record=durable)),
    )

    got = ObjectStore().get_object(str(oid))

    assert got is not None
    assert got.payload == {"version": "committed"}
    assert got.source_ref == "new.md"
    assert legacy._MEMORY_STORE[str(oid)].payload == {"version": "stale"}


def _fake_binding(backend: str, store: FakeCanonicalStore):
    return SimpleNamespace(
        name="object_store",
        backend=backend,
        store=store,
        classification="rebuildable",
        rebuild_source="test fixture",
        owner_subsystem="PDM",
        contract="StorePort",
    )


def test_get_object_delegates_to_canonical_store(monkeypatch):
    oid = uuid4()
    row = {
        "object_id": oid,
        "kind": "capture_note",
        "payload": {"plane": "vault"},
        "source_ref": "vault://Inbox/note.md",
        "created_at": datetime.now(timezone.utc),
    }
    store = FakeCanonicalStore(record=row)
    monkeypatch.setattr("app.objects.resolve_object_store_port", lambda: _fake_binding("pg", store))

    obj = ObjectStore().get_object(str(oid))
    assert obj is not None
    assert obj.uuid == str(oid)
    assert obj.kind == "capture_note"


def test_list_objects_delegates_to_canonical_store(monkeypatch):
    rows = [
        {
            "object_id": uuid4(),
            "kind": "capture_note",
            "payload": {"n": 1},
            "source_ref": "vault://a.md",
            "created_at": datetime.now(timezone.utc),
        },
        {
            "object_id": uuid4(),
            "kind": "capture_note",
            "payload": {"n": 2},
            "source_ref": "vault://b.md",
            "created_at": datetime.now(timezone.utc),
        },
    ]
    store = FakeCanonicalStore(rows=rows)
    monkeypatch.setattr("app.objects.resolve_object_store_port", lambda: _fake_binding("pg", store))

    listed = ObjectStore().list_objects(limit=5)
    assert len(listed) == 2
    assert listed[0].kind == "capture_note"


def test_count_objects_delegates_to_canonical_store(monkeypatch):
    rows = [
        {
            "object_id": uuid4(),
            "kind": "capture_note",
            "payload": {},
            "source_ref": "vault://a.md",
            "created_at": datetime.now(timezone.utc),
        }
    ]
    store = FakeCanonicalStore(rows=rows)
    monkeypatch.setattr("app.objects.resolve_object_store_port", lambda: _fake_binding("pg", store))

    assert ObjectStore().count_objects() == 1
