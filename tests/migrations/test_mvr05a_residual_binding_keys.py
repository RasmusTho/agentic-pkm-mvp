"""MVR-05A residual binding-key migration and fail-loud proof (#4942)."""

from __future__ import annotations

import uuid

import psycopg
import pytest
from sqlalchemy.exc import DBAPIError

from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from tests.migrations.test_multi_vault_ingest_projection_keys import (
    _fk,
    _pk,
    _upgrade,
    scratch_db_factory,  # noqa: F401 - pytest fixture export
)


pytestmark = pytest.mark.pg
PRE_RESIDUAL_HEAD = "f7a05a4b0001"
RESIDUAL_HEAD = "f8a05a9b0001"


def test_residual_binding_tables_migrate_or_fail_loud(
    scratch_db_factory,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrated = scratch_db_factory()
    _upgrade(migrated, monkeypatch, PRE_RESIDUAL_HEAD)
    memory_id = uuid.uuid4()
    with psycopg.connect(migrated) as conn:
        conn.execute(
            "INSERT INTO agent_memories (id, layer, payload) "
            "VALUES (%s, 'short_term', '{\"legacy\":true}'::jsonb)",
            (memory_id,),
        )
        conn.execute(
            "INSERT INTO heimdal_meeting_finalization_receipt "
            "(session_id,state_sha256,complete) VALUES ('session','state',true)"
        )
        conn.execute("CREATE UNIQUE INDEX residual_sets_name_unique ON sets(name)")

    _upgrade(migrated, monkeypatch, RESIDUAL_HEAD)
    with psycopg.connect(migrated) as conn:
        assert _pk(conn, "agent_memories") == ["vault_binding_id", "id"]
        assert _pk(conn, "heimdal_meeting_finalization_receipt") == [
            "vault_binding_id",
            "session_id",
            "state_sha256",
        ]
        assert _pk(conn, "sets") == ["vault_binding_id", "id"]
        assert _fk(conn, "membership", "set_id")[:3] == (
            ["vault_binding_id", "set_id"],
            "sets",
            ["vault_binding_id", "id"],
        )
        assert conn.execute(
            "SELECT vault_binding_id FROM agent_memories WHERE id=%s", (memory_id,)
        ).fetchone() == (COMPATIBILITY_BINDING_ID,)
        assert conn.execute(
            "SELECT vault_binding_id FROM heimdal_meeting_finalization_receipt "
            "WHERE session_id='session'"
        ).fetchone() == (COMPATIBILITY_BINDING_ID,)
        assert conn.execute(
            "SELECT count(*) FROM sets WHERE vault_binding_id=%s AND name='published'",
            (COMPATIBILITY_BINDING_ID,),
        ).fetchone() == (1,)
        conn.execute(
            "INSERT INTO sets(vault_binding_id,id,name) VALUES "
            "('binding-a',%s,'same-name'),('binding-b',%s,'same-name')",
            (uuid.uuid4(), uuid.uuid4()),
        )
        assert conn.execute(
            "SELECT count(*) FROM pg_index i "
            "WHERE i.indrelid='sets'::regclass AND i.indisunique "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM unnest(i.indkey::smallint[]) key(attnum) "
            "  JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=key.attnum "
            "  WHERE a.attname='vault_binding_id'"
            ")"
        ).fetchone() == (0,)
        assert conn.execute("SELECT to_regclass('public.objects_embeddings')").fetchone() == (
            None,
        )
        outbox_columns = {
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='outbox'"
            )
        }
        assert {"vault_binding_id", "legacy_key"} <= outbox_columns

    malformed = scratch_db_factory()
    _upgrade(malformed, monkeypatch, PRE_RESIDUAL_HEAD)
    with psycopg.connect(malformed) as conn:
        conn.execute("ALTER TABLE agent_memories ADD COLUMN vault_binding_id text")

    with pytest.raises(DBAPIError, match="partially binding-keyed agent_memories"):
        _upgrade(malformed, monkeypatch, RESIDUAL_HEAD)
    with psycopg.connect(malformed) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
            PRE_RESIDUAL_HEAD,
        )
        assert conn.execute("SELECT to_regclass('public.objects_embeddings')").fetchone() != (
            None,
        )

    unknown_unique = scratch_db_factory()
    _upgrade(unknown_unique, monkeypatch, PRE_RESIDUAL_HEAD)
    with psycopg.connect(unknown_unique) as conn:
        conn.execute(
            "ALTER TABLE sets ADD COLUMN vault_binding_id text NOT NULL "
            f"DEFAULT '{COMPATIBILITY_BINDING_ID}'"
        )
        conn.execute(
            "CREATE UNIQUE INDEX sets_partial_binding_name_unique "
            "ON sets(vault_binding_id,name) WHERE name <> ''"
        )

    with pytest.raises(DBAPIError, match="unsupported partial or expression unique index"):
        _upgrade(unknown_unique, monkeypatch, RESIDUAL_HEAD)
    with psycopg.connect(unknown_unique) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
            PRE_RESIDUAL_HEAD,
        )
        assert conn.execute("SELECT to_regclass('public.objects_embeddings')").fetchone() != (
            None,
        )
        conn.execute("DROP INDEX sets_partial_binding_name_unique")
    _upgrade(unknown_unique, monkeypatch, RESIDUAL_HEAD)
    with psycopg.connect(unknown_unique) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
            RESIDUAL_HEAD,
        )
