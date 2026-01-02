from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.store.object_store import DomainObject, ObjectStore


class FakeCursor:
    def __init__(self, single=None, multi=None):
        self.single = single
        self.multi = multi or []
        self.last_query = ""
        self._mode = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params=None):
        self.last_query = str(query)
        self._mode = "one" if "LIMIT 1" in self.last_query else "all"

    def fetchone(self):
        return self.single if self._mode == "one" else None

    def fetchall(self):
        return list(self.multi) if self._mode == "all" else []


class FakeConn:
    def __init__(self, cursor: FakeCursor):
        self.cursor_obj = cursor

    def cursor(self):
        return self.cursor_obj

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


@pytest.fixture(autouse=True)
def fake_pg(monkeypatch):
    monkeypatch.setattr("app.store.object_store._pg_available", lambda: True)
    yield


def _domain_row(object_id: str) -> dict:
    return {
        "object_id": object_id,
        "uuid": object_id,
        "kind": "capture_note",
        "payload": {"plane": "vault"},
        "source_ref": "vault://Inbox/note.md",
        "created_at": datetime.now(timezone.utc),
    }


def test_get_object_prefers_store_objects(monkeypatch):
    cursor = FakeCursor(single=_domain_row("store-1"))
    monkeypatch.setattr("app.store.object_store._conn_rw", lambda: FakeConn(cursor))
    monkeypatch.setattr("app.store.object_store.choose_object_table", lambda conn: "store_objects")

    store = ObjectStore()
    obj = store.get_object("store-1")

    assert obj is not None
    assert obj.uuid == "store-1"
    assert "store_objects" in cursor.last_query


def test_list_objects_prefers_store_objects(monkeypatch):
    rows = [_domain_row("store-2"), _domain_row("store-3")]
    cursor = FakeCursor(multi=rows)
    monkeypatch.setattr("app.store.object_store._conn_rw", lambda: FakeConn(cursor))
    monkeypatch.setattr("app.store.object_store.choose_object_table", lambda conn: "store_objects")

    store = ObjectStore()
    listed = store.list_objects(limit=5)

    assert len(listed) == 2
    assert listed[0].kind == "capture_note"
    assert "store_objects" in cursor.last_query


def test_list_objects_falls_back_to_objects(monkeypatch):
    rows = [_domain_row("obj-1")]
    cursor = FakeCursor(multi=rows)
    monkeypatch.setattr("app.store.object_store._conn_rw", lambda: FakeConn(cursor))
    monkeypatch.setattr("app.store.object_store.choose_object_table", lambda conn: "objects")

    store = ObjectStore()
    listed = store.list_objects()

    assert len(listed) == 1
    assert listed[0].uuid == "obj-1"
    assert "objects" in cursor.last_query
