"""Alembic/test-autocreate parity for MVR-05A5 replay projections."""

from __future__ import annotations

import json

import psycopg
import pytest

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
