from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.store.object_store import DomainObject, ObjectStore


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


def test_get_object_uses_memory_cache(monkeypatch):
    obj = DomainObject(
        uuid="mem-1",
        kind="capture_note",
        payload={"plane": "vault"},
        source_ref="vault://Inbox/note.md",
        created_at=datetime.now(timezone.utc),
    )
    from app.store import object_store as legacy

    legacy._MEMORY_STORE.clear()
    legacy._MEMORY_STORE[obj.uuid] = obj
    monkeypatch.setattr("app.store.object_store.resolve_store_backend", lambda: "memory")

    got = ObjectStore().get_object("mem-1")
    assert got is not None
    assert got.uuid == "mem-1"


def test_get_object_delegates_to_canonical_store(monkeypatch):
    oid = uuid4()
    row = {
        "object_id": oid,
        "kind": "capture_note",
        "payload": {"plane": "vault"},
        "source_ref": "vault://Inbox/note.md",
        "created_at": datetime.now(timezone.utc),
    }
    monkeypatch.setattr("app.store.object_store.resolve_store_backend", lambda: "pg")
    monkeypatch.setattr("app.store.object_store.get_object_store", lambda: FakeCanonicalStore(record=row))

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
    monkeypatch.setattr("app.store.object_store.resolve_store_backend", lambda: "pg")
    monkeypatch.setattr("app.store.object_store.get_object_store", lambda: FakeCanonicalStore(rows=rows))

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
    monkeypatch.setattr("app.store.object_store.resolve_store_backend", lambda: "pg")
    monkeypatch.setattr("app.store.object_store.get_object_store", lambda: FakeCanonicalStore(rows=rows))

    assert ObjectStore().count_objects() == 1
