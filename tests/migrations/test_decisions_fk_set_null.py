"""Decisions history must survive deletion of its source object (#3488)."""

from __future__ import annotations

import uuid

import psycopg
import pytest

from tests.migrations.decisions_schema_helpers import migrated_decisions_db


pytestmark = pytest.mark.pg


def test_decisions_fk_set_null(monkeypatch: pytest.MonkeyPatch) -> None:
    """The migration leaves a nullable object_id through ON DELETE SET NULL."""
    object_id = uuid.uuid4()
    decision_id = uuid.uuid4()
    with migrated_decisions_db(monkeypatch) as dsn:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO objects (id, kind, payload) VALUES (%s, %s, %s::jsonb)",
                (object_id, "note", "{}"),
            )
            conn.execute(
                """
                INSERT INTO decisions (id, object_id, agent, kind, key, value)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                """,
                (decision_id, object_id, "test", "classification", "type", "{}"),
            )
            conn.execute("DELETE FROM objects WHERE id = %s", (object_id,))
            row = conn.execute(
                "SELECT object_id FROM decisions WHERE id = %s", (decision_id,)
            ).fetchone()

    assert row == (None,)
