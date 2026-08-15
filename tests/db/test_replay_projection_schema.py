"""Fail-loud MVR-05A5 replay schema preflight."""

from __future__ import annotations

from typing import Any

import pytest

from app.db.replay_projection_schema import (
    ReplayProjectionSchemaError,
    assert_replay_projection_schema,
)


pytestmark = pytest.mark.not_pg


class _Cursor:
    def __init__(self, row: tuple[Any, ...]) -> None:
        self.row = row
        self.params: tuple[Any, ...] = ()
        self.sql = ""

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.sql = sql
        self.params = params

    def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, row: tuple[Any, ...]) -> None:
        self.cursor_instance = _Cursor(row)

    def cursor(self):
        return self.cursor_instance


@pytest.mark.parametrize(
    ("table", "primary_key", "required_unique", "prohibited_unique"),
    (
        (
            "standing_questions",
            ["vault_binding_id", "question_id"],
            ["vault_binding_id", "source_path"],
            ["source_path"],
        ),
        (
            "decision_outcomes",
            ["id"],
            ["vault_binding_id", "decision_uuid", "rung_index"],
            ["decision_uuid", "rung_index"],
        ),
    ),
)
def test_preflight_rejects_missing_binding_unique_or_residual_global_unique(
    table: str,
    primary_key: list[str],
    required_unique: list[str],
    prohibited_unique: list[str],
) -> None:
    connection = _Connection((True, False, primary_key))
    with pytest.raises(ReplayProjectionSchemaError, match="binding_and_uniqueness=False"):
        assert_replay_projection_schema(connection, table)

    assert "pg_constraint" in connection.cursor_instance.sql
    assert required_unique in connection.cursor_instance.params
    assert prohibited_unique in connection.cursor_instance.params
