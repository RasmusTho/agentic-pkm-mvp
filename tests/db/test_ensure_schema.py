from __future__ import annotations

from pathlib import Path

import pytest
from psycopg.errors import DependentObjectsStillExist, DuplicateObject

from app.db import db as db_module

pytestmark = pytest.mark.not_pg


class _FakeCursor:
    def __init__(self, conn: "_FakeConn") -> None:
        self._conn = conn

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, statement: str) -> None:
        self._conn.executed.append(statement)
        if "id_primary_key" in statement:
            self._fetchone = {"id_primary_key": self._conn.id_primary_key}
            return
        outcome = self._conn.outcomes.pop(0) if self._conn.outcomes else None
        if isinstance(outcome, BaseException):
            raise outcome

    def fetchone(self):
        return self._fetchone


class _FakeConn:
    def __init__(self, outcomes: list[BaseException | None], *, id_primary_key: bool = False) -> None:
        self.outcomes = outcomes
        self.id_primary_key = id_primary_key
        self.executed: list[str] = []
        self.rollback_calls = 0

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def rollback(self) -> None:
        self.rollback_calls += 1


def test_ensure_schema_runs_legacy_objects_pk_rewrite_until_known_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    migration_path = tmp_path / "migrations_obsidian.sql"
    migration_path.write_text(
        "\n".join(
            [
                "ALTER TABLE public.objects DROP CONSTRAINT IF EXISTS objects_pkey;",
                "ALTER TABLE public.objects ADD CONSTRAINT objects_pkey PRIMARY KEY (id);",
                "SELECT 1;",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(db_module, "_MIGRATION_SQL_PATH", migration_path)

    conn = _FakeConn(
        outcomes=[
            DependentObjectsStillExist("dependent fk still exists"),
            DuplicateObject("objects_pkey already exists"),
            None,
        ]
    )

    db_module.ensure_schema(conn)  # type: ignore[arg-type]

    assert "id_primary_key" in conn.executed[0]
    assert conn.executed[1:] == [
        "ALTER TABLE public.objects DROP CONSTRAINT IF EXISTS objects_pkey",
        "ALTER TABLE public.objects ADD CONSTRAINT objects_pkey PRIMARY KEY (id)",
        "SELECT 1",
    ]
    assert conn.rollback_calls == 2


def test_ensure_schema_preserves_existing_objects_id_primary_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    migration_path = tmp_path / "migrations_obsidian.sql"
    migration_path.write_text(
        "ALTER TABLE public.objects DROP CONSTRAINT IF EXISTS objects_pkey;\n"
        "ALTER TABLE public.objects ADD CONSTRAINT objects_pkey PRIMARY KEY (id);\n"
        "SELECT 1;\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(db_module, "_MIGRATION_SQL_PATH", migration_path)
    conn = _FakeConn([None], id_primary_key=True)

    db_module.ensure_schema(conn)  # type: ignore[arg-type]

    assert len(conn.executed) == 2
    assert "id_primary_key" in conn.executed[0]
    assert conn.executed[1] == "SELECT 1"
    assert conn.rollback_calls == 0
