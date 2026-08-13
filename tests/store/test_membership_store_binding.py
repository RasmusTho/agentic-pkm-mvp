from __future__ import annotations

import pytest

from app.store.membership_store import save_membership


class _Cursor:
    def __init__(
        self,
        fail: Exception | None = None,
        primary_key=None,
        resolved_set_id: str | None = "resolved-set",
    ) -> None:
        self.sql: list[str] = []
        self.params: list[object] = []
        self.fail = fail
        self.primary_key = primary_key or ["vault_binding_id", "id"]
        self.resolved_set_id = resolved_set_id

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, _params=None):
        self.sql.append(sql)
        self.params.append(_params)
        if self.fail:
            raise self.fail

    def fetchone(self):
        if self.sql[-1] == "SELECT id FROM sets WHERE name = %s":
            return {"id": self.resolved_set_id} if self.resolved_set_id else None
        return {"primary_key": self.primary_key}


class _Conn:
    def __init__(self, cursor):
        self.cursor_value = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return self.cursor_value


def test_membership_writer_mints_fresh_id_and_names_binding(monkeypatch):
    cursor = _Cursor()
    monkeypatch.setattr("app.store.membership_store.conn_rw", lambda: _Conn(cursor))
    save_membership("object", "published")
    assert "vault_binding_id,id,object_id,set_id" in cursor.sql[-1]
    assert cursor.params[-1][3] == "resolved-set"


def test_membership_writer_omits_absent_id_on_retained_lineage(monkeypatch):
    cursor = _Cursor(primary_key=["vault_binding_id", "object_id", "set_id"])
    monkeypatch.setattr("app.store.membership_store.conn_rw", lambda: _Conn(cursor))
    save_membership("object", "published")
    assert "vault_binding_id,object_id,set_id" in cursor.sql[-1]
    assert "vault_binding_id,id" not in cursor.sql[-1]
    assert cursor.params[-1][2] == "resolved-set"


def test_membership_writer_propagates_schema_defect(monkeypatch):
    cursor = _Cursor(RuntimeError("missing membership key"))
    monkeypatch.setattr("app.store.membership_store.conn_rw", lambda: _Conn(cursor))
    with pytest.raises(RuntimeError, match="missing membership key"):
        save_membership("object", "set")


def test_membership_writer_fails_loud_when_named_set_is_missing(monkeypatch):
    cursor = _Cursor(resolved_set_id=None)
    monkeypatch.setattr("app.store.membership_store.conn_rw", lambda: _Conn(cursor))
    with pytest.raises(RuntimeError, match="membership set 'missing' does not exist"):
        save_membership("object", "missing")
