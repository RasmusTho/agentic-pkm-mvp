from __future__ import annotations

import pytest

from app.store.membership_store import save_membership


class _Cursor:
    def __init__(self, fail: Exception | None = None) -> None:
        self.sql = ""
        self.fail = fail
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def execute(self, sql, _params):
        self.sql = sql
        if self.fail: raise self.fail


class _Conn:
    def __init__(self, cursor): self.cursor_value = cursor
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def cursor(self): return self.cursor_value


def test_membership_writer_mints_fresh_id_and_names_binding(monkeypatch):
    cursor = _Cursor()
    monkeypatch.setattr("app.store.membership_store.conn_rw", lambda: _Conn(cursor))
    save_membership("object", "set")
    assert "vault_binding_id, id, object_id, set_id" in cursor.sql


def test_membership_writer_propagates_schema_defect(monkeypatch):
    cursor = _Cursor(RuntimeError("missing membership key"))
    monkeypatch.setattr("app.store.membership_store.conn_rw", lambda: _Conn(cursor))
    with pytest.raises(RuntimeError, match="missing membership key"):
        save_membership("object", "set")
