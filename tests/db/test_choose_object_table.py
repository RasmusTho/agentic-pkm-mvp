from __future__ import annotations

import pytest
from psycopg import Connection

from app.db import choose_object_table, table_count, table_exists


class FakeCursor:
    def __init__(self, exists_map: dict[str, bool], counts: dict[str, int]) -> None:
        self.exists_map = exists_map
        self.counts = counts
        self._rows: list[tuple[int]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        q = str(query)
        if "to_regclass" in q:
            table = params[0] if params else ""
            exists = self.exists_map.get(table, False)
            self._rows = [(1 if exists else None,)]
        elif "count" in q.lower():
            for table, count in self.counts.items():
                if table in q:
                    self._rows = [(count,)]
                    return
            self._rows = [(0,)]
        else:
            self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return []


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.cursor_obj = cursor

    def cursor(self):
        return self.cursor_obj

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_table_exists_true():
    cursor = FakeCursor({"store_objects": True}, {})
    conn = FakeConnection(cursor)
    assert table_exists(conn, "store_objects")


def test_table_exists_false():
    cursor = FakeCursor({"store_objects": False}, {})
    conn = FakeConnection(cursor)
    assert not table_exists(conn, "store_objects")


def test_table_count_returns_zero_when_missing():
    cursor = FakeCursor({}, {})
    conn = FakeConnection(cursor)
    assert table_count(conn, "objects") == 0


def test_table_count_returns_value():
    cursor = FakeCursor({}, {"store_objects": 3})
    conn = FakeConnection(cursor)
    assert table_count(conn, "store_objects") == 3


def test_choose_object_table_prefers_store_objects():
    cursor = FakeCursor({"store_objects": True, "objects": True}, {"store_objects": 1, "objects": 10})
    conn = FakeConnection(cursor)
    assert choose_object_table(conn) == "store_objects"


def test_choose_object_table_falls_back_to_objects():
    cursor = FakeCursor({"store_objects": False, "objects": True}, {"objects": 2})
    conn = FakeConnection(cursor)
    assert choose_object_table(conn) == "objects"
