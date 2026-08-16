"""MVR-05A1 (#4560): `ensure_schema` is a test-fixture seam, not a DDL owner.

Until this slice, `ensure_schema` replayed `app/db/migrations_obsidian.sql` on
the first `conn_rw()` of every process, including an unconditional
`DROP CONSTRAINT objects_pkey` / `ADD CONSTRAINT objects_pkey PRIMARY KEY (id)`
pair that silently reverted any binding-keyed primary key a migration had
installed. Both tables that file owned are now on the Alembic chain and the file
is gone.

The architectural guard that no durable DDL executes outside the revision chain
lives in `tests/architecture/test_durable_table_ownership.py`. These are the
unit-level counterparts on the remaining seam itself.
"""

from __future__ import annotations

import pytest

from app.db import db as db_module

pytestmark = pytest.mark.not_pg


class _FakeCursor:
    def __init__(self, conn: "_FakeConn") -> None:
        self._conn = conn

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, statement: str, *args, **kwargs) -> None:
        self._conn.executed.append(statement)

    def fetchone(self):
        return {
            "present": self._conn.tables_present,
            "table_exists": True,
            "primary_key": ["vault_binding_id", "path"],
            "path_only_unique": [],
        }


class _FakeConn:
    def __init__(self, *, tables_present: bool = False) -> None:
        self.executed: list[str] = []
        self.tables_present = tables_present

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def rollback(self) -> None:  # pragma: no cover - defensive
        raise AssertionError("ensure_schema must not need a rollback")


def test_ensure_schema_issues_nothing_without_the_fixture_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production posture: the connection is not touched at all."""
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
    conn = _FakeConn()

    db_module.ensure_schema(conn)  # type: ignore[arg-type]

    assert conn.executed == []


def test_ensure_schema_creates_the_migration_owned_shape_for_scratch_databases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the KERNEL-04 opt-in it creates every migration-owned table, additively.

    The statements are asserted rather than just counted: the previous
    mechanism's defect was not that it ran too many statements, it was that two
    of them rewrote a constraint another owner had installed.
    """
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    conn = _FakeConn()

    db_module.ensure_schema(conn)  # type: ignore[arg-type]

    ddl = [
        " ".join(statement.split())
        for statement in conn.executed
        if not statement.strip().upper().startswith("SELECT")
    ]
    assert ddl, "the fixture path created nothing"
    for statement in ddl:
        assert statement.upper().startswith("CREATE "), statement

    created = " | ".join(ddl)
    for table in ("public.file_state", "public.objects", "public.agent_memories"):
        assert f"CREATE TABLE {table}" in created, table
    assert (
        "CREATE UNIQUE INDEX objects_uuid_idx "
        "ON public.objects (vault_binding_id, uuid)" in created
    ), created

    # The compatibility sentinel is one namespace shared with `file_state`, not
    # a second binding-identity scheme.
    assert db_module.COMPATIBILITY_BINDING_ID == db_module.FILE_STATE_COMPATIBILITY_BINDING_ID
    assert created.count(f"'{db_module.COMPATIBILITY_BINDING_ID}'") == 3


def test_ensure_schema_leaves_an_existing_table_completely_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A table that already exists is owned by whichever revision created it.

    `CREATE TABLE IF NOT EXISTS` no-ops on an older shape while every statement
    after it still runs against that shape — which both fails on a column the
    revision has not added yet and, worse, would make this fixture a second
    owner able to reshape a migration-owned table.
    """
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    conn = _FakeConn(tables_present=True)

    db_module.ensure_schema(conn)  # type: ignore[arg-type]

    assert [
        statement
        for statement in conn.executed
        if not statement.strip().upper().startswith("SELECT")
    ] == []
