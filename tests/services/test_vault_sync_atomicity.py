"""KERNEL-01 atomicity (#2864): objects + file_state + outbox in ONE transaction.

``upsert_object_from_note`` and ``delete_note`` used to ``conn.commit()`` the
store write and only THEN call ``_enqueue`` — on a separate connection, outside
the ``with _conn()`` block. A crash between the commit and the enqueue changed
durable state with the event lost (silent projection drift). This is the exact
class KERNEL-01 (#2763, PR #2812) already closed for ``sync_markdown`` /
``handle_rename``; this issue extends the fix to the two remaining producers.

The not-pg tests below are the real old-vs-new discriminators without a database:

* the enqueue is invoked on the SAME connection as the store write
  (``conn=`` is the caller's connection, i.e. one transaction), and
* it happens BEFORE the post-write ``commit`` — so a fault injected at the
  enqueue leaves NO commit after the store write, meaning a real transactional
  connection rolls the whole thing back (either nothing or all three).

``test_...rolls_back`` fails against the pre-fix code, where the store write is
committed *before* the enqueue runs — so a fault leaves a committed object with
the event lost.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from app.services import vault_sync

pytestmark = pytest.mark.not_pg

OBJECT_UUID = str(UUID(int=1))
DELETE_UUID = str(UUID(int=2))


# --- Recording fake connection: logs the ORDER of store writes vs commits -----


class _RecCursor:
    def __init__(self, conn: "_RecConn") -> None:
        self.conn = conn
        self.rowcount = 0
        self._fetch: object | None = None

    def __enter__(self) -> "_RecCursor":
        return self

    def __exit__(self, *_a) -> bool:
        return False

    def execute(self, sql: str, params=None) -> None:  # type: ignore[no-untyped-def]
        norm = " ".join(sql.split()).lower()
        self.rowcount = 0
        self._fetch = None
        if norm.startswith("insert into objects"):
            self.conn.log.append("objects_write")
            self.rowcount = 1
            return
        if norm.startswith("insert into store_objects"):
            self.conn.log.append("canonical_object_write")
            self.rowcount = 1
            return
        if norm.startswith("update store_objects"):
            self.conn.log.append("canonical_source_update")
            self.rowcount = 1
            return
        if norm.startswith("insert into file_state"):
            self.conn.log.append("file_state_write")
            self.rowcount = 1
            return
        if norm.startswith("delete from file_state where path"):
            self.conn.log.append("file_state_delete")
            self.rowcount = 1 if self.conn.has_file_state else 0
            return
        if norm.startswith(
            "select path, uuid, fm_hash, body_hash, mtime from file_state where path"
        ):
            self._fetch = (
                {"path": params[0], "uuid": "00000000-0000-0000-0000-000000000002", "mtime": "test"}
                if self.conn.has_file_state
                else None
            )
            return
        if norm.startswith("select count(*) from file_state where uuid"):
            # Zero remaining paths for the uuid → delete_note emits the event.
            self._fetch = (0,)
            return
        if norm.startswith("update objects set path = null"):
            self.conn.log.append("objects_pathnull")
            self.rowcount = 1
            return
        # State lookups (_get_state_by_path / _get_state_by_uuid): no prior row.
        return

    def fetchone(self):
        return self._fetch

    def fetchall(self):
        return []


class _RecConn:
    def __init__(self, *, has_file_state: bool = True) -> None:
        self.log: list[str] = []
        self.has_file_state = has_file_state

    def __enter__(self) -> "_RecConn":
        return self

    def __exit__(self, *_a) -> bool:
        return False

    def cursor(self) -> _RecCursor:
        return _RecCursor(self)

    def commit(self) -> None:
        self.log.append("commit")

    def rollback(self) -> None:
        self.log.append("rollback")


def _install(monkeypatch: pytest.MonkeyPatch, conn: _RecConn, enqueue) -> dict:
    captured: dict = {}

    def _spy(payload, topic, trace_id=None, *, conn=None, observation=None):  # type: ignore[no-untyped-def]
        captured["conn"] = conn
        captured["topic"] = topic
        return enqueue(payload, topic, trace_id, conn=conn, observation=observation)

    monkeypatch.setattr(vault_sync, "_conn", lambda: conn)
    monkeypatch.setattr(vault_sync, "ensure_schema", lambda *_a, **_k: None)
    monkeypatch.setattr(vault_sync, "insert_object_and_outbox", _spy)
    return captured


def _tail_after(log: list[str], marker: str) -> list[str]:
    return log[log.index(marker) :]


# --- upsert_object_from_note --------------------------------------------------


def test_upsert_enqueues_within_transaction_before_commit(tmp_path, monkeypatch) -> None:
    conn = _RecConn()

    def _ok(payload, topic, trace_id=None, *, conn=None, observation=None):  # type: ignore[no-untyped-def]
        conn.log.append("enqueue")

    captured = _install(monkeypatch, conn, _ok)

    vault_sync.upsert_object_from_note(
        str(tmp_path / "new.md"),
        {"uuid": OBJECT_UUID, "title": "T"},
        "body",
        fm_changed=False,
        body_changed=False,
    )

    # New note (no prior state) → CREATED → emits.
    assert captured["topic"] == "ingest.object.created"
    # Same connection as the store write → one transaction, not a second conn.
    assert captured["conn"] is conn
    # The enqueue precedes the post-write commit (single atomic transaction).
    tail = _tail_after(conn.log, "objects_write")
    assert "canonical_object_write" in tail
    assert "enqueue" in tail
    assert tail.index("canonical_object_write") < tail.index("enqueue")
    assert tail.index("enqueue") < tail.index("commit")


def test_upsert_fault_between_store_and_enqueue_rolls_back(tmp_path, monkeypatch) -> None:
    conn = _RecConn()

    def _boom(payload, topic, trace_id=None, *, conn=None, observation=None):  # type: ignore[no-untyped-def]
        conn.log.append("enqueue_attempt")
        raise RuntimeError("enqueue crash")

    _install(monkeypatch, conn, _boom)

    with pytest.raises(RuntimeError, match="enqueue crash"):
        vault_sync.upsert_object_from_note(
            str(tmp_path / "new.md"),
            {"uuid": OBJECT_UUID, "title": "T"},
            "body",
            fm_changed=False,
            body_changed=False,
        )

    # No commit after the store write → a real transaction rolls the object
    # back with the lost event. (Pre-fix code commits before the enqueue, so
    # "commit" WOULD appear here.)
    tail = _tail_after(conn.log, "objects_write")
    assert "canonical_object_write" in tail
    assert "enqueue_attempt" in tail
    assert "commit" not in tail


# --- delete_note --------------------------------------------------------------


def test_delete_enqueues_within_transaction_before_commit(monkeypatch) -> None:
    conn = _RecConn(has_file_state=True)

    def _ok(payload, topic, trace_id=None, *, conn=None, observation=None):  # type: ignore[no-untyped-def]
        conn.log.append("enqueue")

    captured = _install(monkeypatch, conn, _ok)

    vault_sync.delete_note("/vault/gone.md", uuid_value=DELETE_UUID)

    assert captured["topic"] == "ingest.object.deleted"
    assert captured["conn"] is conn
    tail = _tail_after(conn.log, "file_state_delete")
    assert "enqueue" in tail
    assert tail.index("enqueue") < tail.index("commit")


def test_delete_fault_between_store_and_enqueue_rolls_back(monkeypatch) -> None:
    conn = _RecConn(has_file_state=True)

    def _boom(payload, topic, trace_id=None, *, conn=None, observation=None):  # type: ignore[no-untyped-def]
        conn.log.append("enqueue_attempt")
        raise RuntimeError("enqueue crash")

    _install(monkeypatch, conn, _boom)

    with pytest.raises(RuntimeError, match="enqueue crash"):
        vault_sync.delete_note("/vault/gone.md", uuid_value=DELETE_UUID)

    tail = _tail_after(conn.log, "file_state_delete")
    assert "enqueue_attempt" in tail
    assert "commit" not in tail
