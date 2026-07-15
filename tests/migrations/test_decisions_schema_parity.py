"""Alembic owns the complete decisions schema after #3488."""

from __future__ import annotations

import psycopg
import pytest

from tests.migrations.decisions_schema_helpers import migrated_decisions_db


pytestmark = pytest.mark.pg


def test_decisions_schema_matches_migration(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fresh Alembic upgrade produces the decisions writer's required shape."""
    with migrated_decisions_db(monkeypatch) as dsn:
        with psycopg.connect(dsn) as conn:
            columns = {
                row[0]: (row[1], row[2], row[3] or "")
                for row in conn.execute(
                    """
                    SELECT column_name, data_type, is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'decisions'
                    """
                )
            }

    assert columns["id"][0:2] == ("uuid", "NO")
    assert "gen_random_uuid" in columns["id"][2]
    assert columns["object_id"][0:2] == ("uuid", "YES")
    assert columns["agent"][0] == "text"
    assert columns["kind"][0] == "text"
    assert columns["key"][0:2] == ("text", "NO")
    assert columns["value"][0:2] == ("jsonb", "NO")
    assert columns["created_at"][0:2] == ("timestamp with time zone", "NO")
