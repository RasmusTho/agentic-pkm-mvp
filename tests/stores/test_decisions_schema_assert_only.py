"""Runtime decisions writes must not create or alter database schema (#3488)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def test_pg_decisions_missing_schema_fails_with_migration_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing table is a migration failure, never a runtime DDL opportunity."""
    from app.stores import postgres

    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (None,)
    monkeypatch.setattr(postgres.psycopg, "connect", lambda _dsn: conn)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/app")

    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        postgres.PgDecisions().put(
            object_id="00000000-0000-0000-0000-000000000001",
            agent="test",
            kind="classification",
            key="type",
            value={"type": "note"},
        )

    statements = [str(call.args[0]).lower() for call in cur.execute.call_args_list]
    assert len(statements) == 1
    assert "to_regclass" in statements[0]
    assert all("create table" not in sql and "alter table" not in sql for sql in statements)


def test_pg_decisions_stale_schema_fails_with_migration_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The old nullable/FK/default posture is not accepted as migration-complete."""
    from app.stores import postgres

    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect = [("decisions",), ("NO", None, "CASCADE")]
    cur.fetchall.return_value = [
        ("id",),
        ("object_id",),
        ("agent",),
        ("kind",),
        ("key",),
        ("value",),
        ("created_at",),
    ]
    monkeypatch.setattr(postgres.psycopg, "connect", lambda _dsn: conn)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/app")

    with pytest.raises(RuntimeError, match="Schema shape is stale"):
        postgres.PgDecisions().put(
            object_id="00000000-0000-0000-0000-000000000001",
            agent="test",
            kind="classification",
            key="type",
            value={"type": "note"},
        )

    statements = [str(call.args[0]).lower() for call in cur.execute.call_args_list]
    assert all("create table" not in sql and "alter table" not in sql for sql in statements)
