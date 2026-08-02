from __future__ import annotations

from datetime import datetime, timezone

import pytest
from uuid import UUID

from app.services import vault_sync

UUID1 = str(UUID(int=1))
UUID2 = str(UUID(int=2))
UUID3 = str(UUID(int=3))
UUID4 = str(UUID(int=4))


def test_canonical_note_payload_projects_episode_ref_at_top_level() -> None:
    episode_ids = [UUID1, UUID2]

    payload = vault_sync._canonical_note_payload(
        frontmatter={"episode_ref": episode_ids, "review_state": "provisional"},
        title="Bound note",
        review_state="provisional",
        maturity=None,
        content="body",
    )

    assert payload["episode_ref"] == episode_ids
    assert payload["frontmatter"]["episode_ref"] == episode_ids


def _assert_binding_scoped(binding_id: object) -> None:
    """Every file_state statement must carry a real binding id (MVR-05A0, #4543)."""
    assert isinstance(binding_id, str) and binding_id, (
        f"file_state statement executed without a vault binding id: {binding_id!r}"
    )


class _FakeCursor:
    def __init__(self, conn: "_FakeConn") -> None:
        self.conn = conn
        self.rowcount = 0
        self._fetchone = None
        self._fetchall = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql: str, params=None) -> None:  # type: ignore[no-untyped-def]
        normalized = " ".join(sql.split()).lower()
        self.rowcount = 0
        self._fetchone = None
        self._fetchall = []
        if normalized.startswith("select to_regclass(%s) as oid"):
            self._fetchone = (params[0],)
            return
        if "from information_schema.columns" in normalized or "from pg_attribute" in normalized:
            self._fetchall = [(name,) for name in ("dim", "model", "provider", "normalize")]
            return
        if normalized.startswith("update store_vector_index"):
            return
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
        if normalized.startswith("select id::text, count(*) over ()"):
            canonical_alias, uuid_value = params
            self._fetchone = (
                (uuid_value, 1, str(canonical_alias) in self.conn.canonical_source)
                if uuid_value in self.conn.objects_path
                else None
            )
            return
        if normalized.startswith("select exists(select 1 from store_objects"):
            canonical_id, _id_value, uuid_value, expected_source, _canonical_again = params
            canonical_exists = str(canonical_id) in self.conn.canonical_source
            mirror_exists = uuid_value in self.conn.objects_path
            locator_complete = (
                self.conn.canonical_source.get(str(canonical_id)) == expected_source
                if canonical_exists
                else False
            )
            self._fetchone = (canonical_exists, mirror_exists, locator_complete)
            return
        if normalized.startswith(
            "select payload from store_objects where object_id = %s for update"
        ):
            (object_id,) = params
            payload = self.conn.canonical_payload.get(str(object_id))
            self._fetchone = (payload,) if payload is not None else None
            return
        if normalized.startswith("insert into store_objects"):
            object_id, _kind, source_ref, payload = params
            self.conn.canonical_source[str(object_id)] = source_ref
            self.conn.canonical_payload[str(object_id)] = payload
            self.rowcount = 1
            return
        if normalized.startswith("update store_objects"):
            source_ref, object_id = params
            key = str(object_id)
            if key in self.conn.canonical_source:
                self.conn.canonical_source[key] = source_ref
                self.rowcount = 1
            return
        # MVR-05A0 (#4543): every file_state statement now leads with
        # `vault_binding_id`. This fake models a single binding (these tests are
        # about lifecycle ordering, not binding isolation — that is proven
        # against real Postgres in tests/services/test_vault_sync_binding_scope.py),
        # but it asserts the binding parameter is actually supplied, so an
        # unscoped statement reintroduced here fails loudly instead of silently
        # matching a laxer pattern.
        if normalized.startswith("insert into file_state("):
            binding_id, path, uuid_value, fm_hash, body_hash, mtime = params
            _assert_binding_scoped(binding_id)
            self.conn.file_state[path] = {
                "path": path,
                "uuid": uuid_value,
                "fm_hash": fm_hash,
                "body_hash": body_hash,
                "mtime": mtime,
            }
            self.rowcount = 1
            return
        if normalized.startswith(
            "delete from file_state where vault_binding_id = %s and uuid = %s and path <> %s"
        ):
            binding_id, uuid_value, keep_path = params
            _assert_binding_scoped(binding_id)
            before = len(self.conn.file_state)
            self.conn.file_state = {
                path: row
                for path, row in self.conn.file_state.items()
                if not (row.get("uuid") == uuid_value and path != keep_path)
            }
            self.rowcount = before - len(self.conn.file_state)
            return
        if normalized.startswith(
            "select path, uuid, fm_hash, body_hash, mtime from file_state "
            "where vault_binding_id = %s and path = %s"
        ):
            binding_id, path = params
            _assert_binding_scoped(binding_id)
            self._fetchone = self.conn.file_state.get(path)
            return
        if normalized.startswith(
            "select path, uuid, fm_hash, body_hash, mtime from file_state "
            "where vault_binding_id = %s and uuid = %s"
        ):
            binding_id, uuid_value = params
            _assert_binding_scoped(binding_id)
            self._fetchone = next(
                (row for row in self.conn.file_state.values() if row.get("uuid") == uuid_value),
                None,
            )
            return
        if normalized.startswith(
            "delete from file_state where vault_binding_id = %s and path = %s"
        ):
            binding_id, path = params
            _assert_binding_scoped(binding_id)
            self.rowcount = 1 if self.conn.file_state.pop(path, None) else 0
            return
        if normalized.startswith(
            "select count(*) from file_state where vault_binding_id = %s and uuid = %s"
        ):
            binding_id, uuid_value = params
            _assert_binding_scoped(binding_id)
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

    def fetchall(self):  # type: ignore[no-untyped-def]
        return self._fetchall


class _FakeConn:
    def __init__(self) -> None:
        self.file_state: dict[str, dict[str, object]] = {}
        self.objects_path: dict[str, str | None] = {}
        self.canonical_source: dict[str, str | None] = {}
        self.canonical_payload: dict[str, object] = {}

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
        binding_id=vault_sync._binding_id(),
    )

    assert conn.objects_path[UUID1] == "/vault/new.md"
    assert conn.canonical_source[UUID1] == "/vault/new.md"
    paths_for_uuid = sorted(
        path for path, row in conn.file_state.items() if row.get("uuid") == UUID1
    )
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


def test_deferred_first_rename_keeps_file_state_without_materializing_parent(monkeypatch) -> None:
    conn = _FakeConn()
    conn.file_state["/vault/old.md"] = {
        "path": "/vault/old.md",
        "uuid": UUID1,
        "fm_hash": "x",
        "body_hash": "y",
        "mtime": datetime.now(timezone.utc),
    }
    monkeypatch.setattr(vault_sync, "_conn", lambda: conn)
    monkeypatch.setattr(vault_sync, "ensure_schema", lambda *_a, **_k: None)

    vault_sync.update_path(UUID1, "/vault/new.md")

    assert "/vault/new.md" in conn.file_state
    assert conn.canonical_source == {}
    assert conn.objects_path == {}


def test_deferred_first_delete_emits_tombstone_without_parent(monkeypatch) -> None:
    conn = _FakeConn()
    conn.file_state["/vault/gone.md"] = {
        "path": "/vault/gone.md",
        "uuid": UUID1,
        "fm_hash": "x",
        "body_hash": "y",
        "mtime": datetime.now(timezone.utc),
    }
    emitted = []
    monkeypatch.setattr(vault_sync, "_conn", lambda: conn)
    monkeypatch.setattr(vault_sync, "ensure_schema", lambda *_a, **_k: None)
    monkeypatch.setattr(
        vault_sync,
        "insert_object_and_outbox",
        lambda payload, topic, trace_id, **kwargs: emitted.append((payload, topic)),
    )

    assert vault_sync.delete_note("/vault/gone.md", uuid_value=UUID1)
    assert emitted and emitted[0][0]["uuid"] == UUID1
    assert conn.canonical_source == {}


@pytest.mark.parametrize("canonical, mirror", [(True, False), (False, True)])
def test_one_sided_materialization_remains_fail_loud(canonical, mirror) -> None:
    conn = _FakeConn()
    if canonical:
        conn.canonical_source[UUID1] = "/vault/note.md"
    if mirror:
        conn.objects_path[UUID1] = "/vault/note.md"

    with pytest.raises(RuntimeError, match="inconsistent vault object materialization"):
        vault_sync._update_materialized_source_ref(
            conn,
            canonical_object_id=UUID1,
            uuid_value=UUID1,
            source_ref="/vault/note.md",
        )


def test_unknown_no_parent_state_remains_fail_loud() -> None:
    with pytest.raises(RuntimeError, match="missing vault object materialization"):
        vault_sync._update_materialized_source_ref(
            _FakeConn(),
            canonical_object_id=UUID1,
            uuid_value=UUID1,
            source_ref=None,
        )


def test_delete_note_does_not_emit_deleted_event_when_uuid_still_has_other_paths(
    monkeypatch,
) -> None:
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
