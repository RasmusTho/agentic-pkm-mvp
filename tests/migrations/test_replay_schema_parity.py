"""Alembic/test-autocreate parity for MVR-05A5 replay projections."""

from __future__ import annotations

import json

import psycopg
import pytest

from app.db.replay_projection_schema import (
    ReplayProjectionSchemaError,
    assert_replay_projection_schema,
)
from tests.migrations.test_multi_vault_ingest_projection_keys import (
    _upgrade,
    scratch_db_factory,  # noqa: F401 - pytest fixture export
)
from tests.migrations.test_multi_vault_replay_projection_backfill import REPLAY_HEAD


pytestmark = pytest.mark.pg
REPLAY_TABLES = (
    "standing_questions",
    "episodes",
    "episode_engine_state",
    "episode_artifact_binding",
    "decisions",
    "decision_outcomes",
)


def _shape(dsn: str) -> dict[str, object]:
    with psycopg.connect(dsn) as conn:
        columns = conn.execute(
            "SELECT table_name,column_name,data_type,is_nullable,coalesce(column_default,'') "
            "FROM information_schema.columns WHERE table_schema='public' AND table_name=ANY(%s) "
            "ORDER BY table_name,ordinal_position",
            (list(REPLAY_TABLES),),
        ).fetchall()
        constraints = conn.execute(
            "SELECT c.conrelid::regclass::text,c.contype,pg_get_constraintdef(c.oid) "
            "FROM pg_constraint c WHERE c.conrelid=ANY(%s::regclass[]) "
            "AND c.contype IN ('p','u','c') ORDER BY 1,2,3",
            ([f"public.{table}" for table in REPLAY_TABLES],),
        ).fetchall()
    return {
        "columns": [tuple(row) for row in columns],
        "constraints": [tuple(row) for row in constraints],
    }


def test_replay_tables_declare_the_binding_column_in_both_shapes(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = request.getfixturevalue("scratch_db_factory")
    migrated, autocreated = factory(), factory()
    _upgrade(migrated, monkeypatch, REPLAY_HEAD)

    from app.db import db
    from app.stores import pg

    monkeypatch.setenv("DATABASE_URL", autocreated)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    monkeypatch.setattr(db, "_SCHEMA_INITIALIZED", False)
    with db.conn_rw():
        pass
    monkeypatch.setattr(pg, "_TABLES_READY", False)
    pg._ensure_tables()
    monkeypatch.setattr(db, "_SCHEMA_INITIALIZED", False)
    monkeypatch.setattr(pg, "_TABLES_READY", False)

    migrated_shape, autocreated_shape = _shape(migrated), _shape(autocreated)
    assert migrated_shape == autocreated_shape, (
        "MVR-05A5 Alembic/autocreate parity diverged:\n"
        f"alembic={json.dumps(migrated_shape, indent=2, default=str)}\n"
        f"autocreate={json.dumps(autocreated_shape, indent=2, default=str)}"
    )


@pytest.mark.parametrize(
    ("table", "binding_constraint", "binding_columns", "global_columns"),
    (
        (
            "standing_questions",
            "standing_questions_binding_source_key",
            "vault_binding_id, source_path",
            "source_path",
        ),
        (
            "decision_outcomes",
            "decision_outcomes_binding_decision_rung_key",
            "vault_binding_id, decision_uuid, rung_index",
            "decision_uuid, rung_index",
        ),
    ),
)
def test_replay_preflight_rejects_missing_binding_unique_and_residual_global_unique(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    table: str,
    binding_constraint: str,
    binding_columns: str,
    global_columns: str,
) -> None:
    """The production guard rejects both partial-conversion uniqueness failures."""
    factory = request.getfixturevalue("scratch_db_factory")
    dsn = factory()
    _upgrade(dsn, monkeypatch, REPLAY_HEAD)
    with psycopg.connect(dsn) as conn:
        assert_replay_projection_schema(conn, table)

        conn.execute(f"ALTER TABLE {table} DROP CONSTRAINT {binding_constraint}")
        with pytest.raises(ReplayProjectionSchemaError, match="binding_and_uniqueness=False"):
            assert_replay_projection_schema(conn, table)

        conn.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {binding_constraint} UNIQUE ({binding_columns})"
        )
        assert_replay_projection_schema(conn, table)

        global_constraint = f"{table}_mvr05a5_forbidden_global_key"
        conn.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {global_constraint} UNIQUE ({global_columns})"
        )
        with pytest.raises(ReplayProjectionSchemaError, match="binding_and_uniqueness=False"):
            assert_replay_projection_schema(conn, table)
