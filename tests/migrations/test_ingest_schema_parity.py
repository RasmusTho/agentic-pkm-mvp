"""Alembic/test-autocreate parity for MVR-05A4 ingest projections."""

from __future__ import annotations

import json
import uuid

import psycopg
import pytest

from tests.migrations.test_multi_vault_ingest_projection_keys import (
    INGEST_HEAD,
    _fk,
    _pk,
    _prepare_retained_historical_lineage,
    _upgrade,
    scratch_db_factory,  # noqa: F401 - pytest fixture export
)


pytestmark = pytest.mark.pg
INGEST_TABLES = ("chunks", "embeddings", "relations", "sets", "membership")
INGEST_VIEWS = ("view_chunks_missing_embeddings", "view_objects_ready_for_projection")


def _shape(dsn: str, tables: tuple[str, ...] = INGEST_TABLES) -> dict[str, object]:
    with psycopg.connect(dsn) as conn:
        columns = conn.execute(
            "SELECT table_name,column_name,data_type,is_nullable,coalesce(column_default,'') "
            "FROM information_schema.columns WHERE table_schema='public' "
            "AND table_name=ANY(%s) ORDER BY table_name,ordinal_position",
            (list(tables),),
        ).fetchall()
        constraints = conn.execute(
            "SELECT c.conrelid::regclass::text,c.contype,pg_get_constraintdef(c.oid) "
            "FROM pg_constraint c WHERE c.conrelid=ANY(%s::regclass[]) "
            "AND c.contype IN ('p','f','u') ORDER BY 1,2,3",
            ([f"public.{table}" for table in tables],),
        ).fetchall()
        binding_indexes = conn.execute(
            "SELECT t.relname,array_agg(a.attname ORDER BY k.ordinality) "
            "FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid "
            "JOIN unnest(i.indkey::smallint[]) WITH ORDINALITY k(attnum,ordinality) ON true "
            "JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum "
            "WHERE i.indrelid=ANY(%s::regclass[]) GROUP BY t.relname,i.indexrelid "
            "HAVING 'vault_binding_id'=ANY(array_agg(a.attname)) ORDER BY 1,2",
            ([f"public.{table}" for table in tables],),
        ).fetchall()
        views = conn.execute(
            "SELECT v.table_name,array_agg(v.column_name ORDER BY v.ordinal_position),"
            "pg_get_viewdef((quote_ident(v.table_schema)||'.'||quote_ident(v.table_name))::regclass,true) "
            "FROM information_schema.columns v WHERE v.table_schema='public' "
            "AND v.table_name=ANY(%s) GROUP BY v.table_schema,v.table_name ORDER BY v.table_name",
            (list(INGEST_VIEWS),),
        ).fetchall()
    return {
        "columns": [tuple(row) for row in columns],
        "constraints": [tuple(row) for row in constraints],
        "binding_indexes": [(row[0], list(row[1])) for row in binding_indexes],
        "views": [(row[0], list(row[1]), " ".join(row[2].split())) for row in views],
    }


def _autocreate(dsn: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.stores import pg

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    monkeypatch.setattr(pg, "_TABLES_READY", False)
    pg._ensure_tables()
    monkeypatch.setattr(pg, "_TABLES_READY", False)


def test_ingest_tables_match_migration_and_autocreate(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = request.getfixturevalue("scratch_db_factory")
    migrated, autocreated, retained = factory(), factory(), factory()
    _upgrade(migrated, monkeypatch, INGEST_HEAD)
    _autocreate(autocreated, monkeypatch)
    _prepare_retained_historical_lineage(retained, monkeypatch)
    _upgrade(retained, monkeypatch, INGEST_HEAD)
    migrated_shape, autocreated_shape = _shape(migrated), _shape(autocreated)
    assert migrated_shape == autocreated_shape, (
        "MVR-05A4 Alembic/autocreate schema or retained-view parity diverged:\n"
        f"alembic={json.dumps(migrated_shape,indent=2,default=str)}\n"
        f"autocreate={json.dumps(autocreated_shape,indent=2,default=str)}"
    )
    shared_tables = ("chunks", "embeddings", "relations", "sets")
    assert _shape(retained, shared_tables) == _shape(migrated, shared_tables)
    with psycopg.connect(retained) as conn:
        assert _pk(conn, "membership") == ["vault_binding_id", "object_id", "set_id"]
        assert _fk(conn, "membership", "object_id")[:3] == (
            ["vault_binding_id", "object_id"],
            "store_objects",
            ["vault_binding_id", "object_id"],
        )
        assert _fk(conn, "membership", "set_id")[:3] == (
            ["vault_binding_id", "set_id"],
            "store_objects",
            ["vault_binding_id", "object_id"],
        )
        assert conn.execute(
            "SELECT column_name,data_type,is_nullable FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='membership' ORDER BY ordinal_position"
        ).fetchall() == [
            ("set_id", "uuid", "NO"),
            ("object_id", "uuid", "NO"),
            ("created_at", "timestamp with time zone", "NO"),
            ("vault_binding_id", "text", "NO"),
        ]


def test_ingest_views_and_reset_keep_duplicate_uuid_bindings_isolated(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = request.getfixturevalue("scratch_db_factory")
    dsn = factory()
    _upgrade(dsn, monkeypatch, INGEST_HEAD)
    object_id = uuid.uuid4()
    set_id = uuid.uuid4()
    with psycopg.connect(dsn) as conn:
        conn.execute("INSERT INTO sets(id,name) VALUES (%s,'shared')", (set_id,))
        for binding in ("binding-a", "binding-b"):
            conn.execute(
                "INSERT INTO store_objects(vault_binding_id,object_id,kind,payload) "
                "VALUES (%s,%s,'note','{}'::jsonb)",
                (binding, object_id),
            )
            chunk_id = uuid.uuid4()
            conn.execute(
                "INSERT INTO chunks(id,vault_binding_id,object_id,idx,offset_start,offset_end,text) "
                "VALUES (%s,%s,%s,0,0,1,'x')",
                (chunk_id, binding, object_id),
            )
            if binding == "binding-a":
                conn.execute(
                    "INSERT INTO embeddings(id,vault_binding_id,object_id,chunk_id,dim) "
                    "VALUES (%s,%s,%s,%s,3)",
                    (uuid.uuid4(), binding, object_id, chunk_id),
                )
            conn.execute(
                "INSERT INTO decisions(vault_binding_id,object_id,key,value) "
                "VALUES (%s,%s,'classification','{\"type\":\"note\"}'::jsonb)",
                (binding, object_id),
            )
            if binding == "binding-a":
                conn.execute(
                    "INSERT INTO membership(id,vault_binding_id,object_id,set_id) "
                    "VALUES (%s,%s,%s,%s)",
                    (uuid.uuid4(), binding, object_id, set_id),
                )
        missing = conn.execute(
            "SELECT vault_binding_id FROM view_chunks_missing_embeddings ORDER BY 1"
        ).fetchall()
        ready = conn.execute(
            "SELECT vault_binding_id FROM view_objects_ready_for_projection ORDER BY 1"
        ).fetchall()
    assert missing == [("binding-b",)]
    assert ready == [("binding-b",)]
