"""Decisions history must survive deletion of its canonical source object (#3488)."""

from __future__ import annotations

import uuid

import psycopg
import pytest

from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from tests.migrations.decisions_schema_helpers import migrated_decisions_db


pytestmark = pytest.mark.pg


def test_decisions_fk_set_null(monkeypatch: pytest.MonkeyPatch) -> None:
    """The migration leaves a nullable object_id through ON DELETE SET NULL."""
    object_id = uuid.uuid4()
    decision_id = uuid.uuid4()
    with migrated_decisions_db(monkeypatch) as dsn:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO store_objects (vault_binding_id, object_id, kind, payload) "
                "VALUES (%s, %s, %s, %s::jsonb)",
                (COMPATIBILITY_BINDING_ID, object_id, "note", "{}"),
            )
            conn.execute(
                """
                INSERT INTO decisions (id, vault_binding_id, object_id, agent, kind, key, value)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    decision_id,
                    COMPATIBILITY_BINDING_ID,
                    object_id,
                    "test",
                    "classification",
                    "type",
                    "{}",
                ),
            )
            conn.execute(
                "DELETE FROM store_objects WHERE vault_binding_id = %s AND object_id = %s",
                (COMPATIBILITY_BINDING_ID, object_id),
            )
            row = conn.execute(
                "SELECT object_id FROM decisions WHERE id = %s", (decision_id,)
            ).fetchone()

    assert row == (None,)
