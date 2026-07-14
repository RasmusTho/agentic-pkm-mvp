from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from app.services import vault_sync

UUID1 = str(UUID(int=1))
UUID2 = str(UUID(int=2))
UUID3 = str(UUID(int=3))
UUID4 = str(UUID(int=4))


class _FakeCursor:
    def __init__(self, conn: "_FakeConn") -> None:
        self.conn = conn
        self.rowcount = 0
        self._fetchone = None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql: str, params=None) -> None:  # type: ignore[no-untyped-def]
        normalized = " ".join(sql.split()).lower()
        self.rowcount = 0
        self._fetchone = None
        if normalized.startswith("update objects set path=%s where uuid=%s"):
            new_path, uuid_value = params
            if uuid_value in self.conn.objects_path:
                self.conn.objects_path[uuid_value] = new_path
                self.rowcount = 1
            return
        if normalized.startswith("update objects set path=%s where id=%s"):
            new_path, uuid_value = params
            if uuid_value in self.conn.objects_path:
                self.conn.objects_path[uuid_value] = new_path
                self.rowcount = 1
            return
        if normalized.startswith("insert into store_objects"):
            object_id, _kind, source_ref, _payload = params
            self.conn.canonical_source[str(object_id)] = source_ref
            self.rowcount = 1
            return
        if normalized.startswith("update store_objects"):
            source_ref, object_id = params
            key = str(object_id)
            if key in self.conn.canonical_source:
                self.conn.canonical_source[key] = source_ref
                self.rowcount = 1
            return
        if normalized.startswith("insert into file_state(path, uuid, fm_hash, body_hash, mtime, last_seen)"):
            path, uuid_value, fm_hash, body_hash, mtime = params
            self.conn.file_state[path] = {
                "path": path,
                "uuid": uuid_value,
                "fm_hash": fm_hash,
                "body_hash": body_hash,
                "mtime": mtime,
            }
            self.rowcount = 1
            return
        if normalized.startswith("delete from file_state where uuid = %s and path <> %s"):
            uuid_value, keep_path = params
            before = len(self.conn.file_state)
            self.conn.file_state = {
                path: row for path, row in self.conn.file_state.items() if not (row.get("uuid") == uuid_value and path != keep_path)
            }
            self.rowcount = before - len(self.conn.file_state)
            return
        if normalized.startswith("select path, uuid, fm_hash, body_hash, mtime from file_state where path = %s"):
            (path,) = params
            self._fetchone = self.conn.file_state.get(path)
            return
        if normalized.startswith("delete from file_state where path = %s"):
            (path,) = params
            self.rowcount = 1 if self.conn.file_state.pop(path, None) else 0
            return
        if normalized.startswith("select count(*) from file_state where uuid = %s"):
            (uuid_value,) = params
            count = sum(1 for row in self.conn.file_state.values() if row.get("uuid") == uuid_value)
            self._fetchone = (count,)
            return
        if normalized.startswith("update objects set path = null where uuid = %s"):
            (uuid_value,) = params
            if uuid_value in self.conn.objects_path:
                self.conn.objects_path[uuid_value] = None
                self.rowcount = 1
            return
        if normalized.startswith("update objects set path = null where id = %s"):
            (uuid_value,) = params
            if uuid_value in self.conn.objects_path:
                self.conn.objects_path[uuid_value] = None
                self.rowcount = 1
            return
        raise AssertionError(f"Unhandled SQL in test fake: {normalized}")

    def fetchone(self):  # type: ignore[no-untyped-def]
        return self._fetchone


class _FakeConn:
    def __init__(self) -> None:
        self.file_state: dict[str, dict[str, object]] = {}
        self.objects_path: dict[str, str | None] = {}
        self.canonical_source: dict[str, str | None] = {}

    def __enter__(self) -> "_FakeConn":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def test_update_path_only_keeps_single_active_file_state_path() -> None:
    conn = _FakeConn()
    conn.objects_path[UUID1] = "/vault/old.md"
    conn.canonical_source[UUID1] = "/vault/old.md"
    conn.file_state["/vault/old.md"] = {"path": "/vault/old.md", "uuid": UUID1}
    conn.file_state["/vault/legacy.md"] = {"path": "/vault/legacy.md", "uuid": UUID1}

    vault_sync._update_path_only(
        conn,
        old_path="/vault/old.md",
        new_path="/vault/new.md",
        uuid_value=UUID1,
        payload={},
        fm_hash="fm",
        body_hash="body",
        mtime=datetime.now(timezone.utc),
    )

    assert conn.objects_path[UUID1] == "/vault/new.md"
    assert conn.canonical_source[UUID1] == "/vault/new.md"
    paths_for_uuid = sorted(path for path, row in conn.file_state.items() if row.get("uuid") == UUID1)
    assert paths_for_uuid == ["/vault/new.md"]


def test_delete_note_clears_file_state_and_object_path(monkeypatch) -> None:
    conn = _FakeConn()
    conn.objects_path[UUID2] = "/vault/note.md"
    conn.canonical_source[UUID2] = "/vault/note.md"
    conn.file_state["/vault/note.md"] = {
        "path": "/vault/note.md",
        "uuid": UUID2,
        "fm_hash": "x",
        "body_hash": "y",
        "mtime": datetime.now(timezone.utc),
    }
    monkeypatch.setattr(vault_sync, "_conn", lambda: conn)
    monkeypatch.setattr(vault_sync, "ensure_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(vault_sync, "insert_object_and_outbox", lambda *args, **kwargs: None)

    vault_sync.delete_note("/vault/note.md", uuid_value=UUID2)

    assert "/vault/note.md" not in conn.file_state
    assert conn.objects_path[UUID2] is None
    assert conn.canonical_source[UUID2] is None


def test_delete_note_emits_outbox_event_on_real_delete(monkeypatch) -> None:
    conn = _FakeConn()
    conn.objects_path[UUID3] = "/vault/gone.md"
    conn.canonical_source[UUID3] = "/vault/gone.md"
    conn.file_state["/vault/gone.md"] = {
        "path": "/vault/gone.md",
        "uuid": UUID3,
        "fm_hash": "x",
        "body_hash": "y",
        "mtime": datetime.now(timezone.utc),
    }
    emitted: list[tuple[dict[str, object], str, str | None]] = []

    monkeypatch.setattr(vault_sync, "_conn", lambda: conn)
    monkeypatch.setattr(vault_sync, "ensure_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        vault_sync,
        "insert_object_and_outbox",
        lambda payload, topic, trace_id, **kwargs: emitted.append((payload, topic, trace_id)),
    )

    vault_sync.delete_note("/vault/gone.md", uuid_value=UUID3)

    assert emitted
    payload, topic, trace_id = emitted[-1]
    assert topic == "ingest.object.deleted"
    assert trace_id
    assert payload["uuid"] == UUID3
    assert payload["path"] == "/vault/gone.md"
    assert payload["deleted"] is True


def test_delete_note_does_not_emit_deleted_event_when_uuid_still_has_other_paths(monkeypatch) -> None:
    conn = _FakeConn()
    conn.objects_path[UUID4] = "/vault/keep.md"
    conn.canonical_source[UUID4] = "/vault/keep.md"
    conn.file_state["/vault/remove.md"] = {
        "path": "/vault/remove.md",
        "uuid": UUID4,
        "fm_hash": "x",
        "body_hash": "y",
        "mtime": datetime.now(timezone.utc),
    }
    conn.file_state["/vault/keep.md"] = {
        "path": "/vault/keep.md",
        "uuid": UUID4,
        "fm_hash": "x2",
        "body_hash": "y2",
        "mtime": datetime.now(timezone.utc),
    }
    emitted: list[tuple[dict[str, object], str, str | None]] = []

    monkeypatch.setattr(vault_sync, "_conn", lambda: conn)
    monkeypatch.setattr(vault_sync, "ensure_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        vault_sync,
        "insert_object_and_outbox",
        lambda payload, topic, trace_id, **kwargs: emitted.append((payload, topic, trace_id)),
    )

    vault_sync.delete_note("/vault/remove.md", uuid_value=UUID4)

    assert "/vault/remove.md" not in conn.file_state
    assert conn.objects_path[UUID4] == "/vault/keep.md"
    assert emitted == []
