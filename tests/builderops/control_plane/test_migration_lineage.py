from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from app.builderops.control_plane import PostgresBuilderOpsStore

pytestmark = pytest.mark.pg


def _isolated_schema_dsn(dsn: str, schema: str) -> str:
    parts = urlsplit(dsn)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema},public"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def test_initialize_refuses_newer_schema_and_preserves_runtime_authority_epoch(
    control_plane_store, envelope
) -> None:
    store = control_plane_store
    with store._connect() as conn:
        conn.execute(
            "INSERT INTO builderops_schema_migrations(version, name, checksum) "
            "VALUES (3, '0003_future.sql', 'future')"
        )
        conn.execute(
            "UPDATE builderops_authority_metadata "
            "SET authority_epoch = 2, schema_version = 3 WHERE singleton"
        )

    with pytest.raises(RuntimeError, match="newer or unknown migration version"):
        store.initialize()
    assert store.readiness() == {"authority_epoch": 2, "schema_version": 3}

    with store._connect() as conn:
        conn.execute("DELETE FROM builderops_schema_migrations WHERE version = 3")
        conn.execute(
            "UPDATE builderops_authority_metadata "
            "SET authority_epoch = 2, schema_version = 2 WHERE singleton"
        )
    store.initialize()
    assert store.readiness() == {"authority_epoch": 2, "schema_version": 2}


@pytest.mark.parametrize(
    ("column", "value"),
    (("name", "corrupted.sql"), ("checksum", "corrupted")),
)
def test_initialize_refuses_mismatched_applied_migration_lineage(
    control_plane_store, envelope, column: str, value: str
) -> None:
    store = control_plane_store
    with store._connect() as conn:
        conn.execute(
            f"UPDATE builderops_schema_migrations SET {column} = %s WHERE version = 1",  # noqa: S608
            (value,),
        )
    with pytest.raises(RuntimeError, match="does not match this release lineage"):
        store.initialize()


def test_initialize_is_idempotent_for_exact_current_lineage(control_plane_store, envelope) -> None:
    control_plane_store.initialize()
    assert control_plane_store.readiness() == {"authority_epoch": 1, "schema_version": 2}


@pytest.mark.parametrize(
    "schema_drift",
    (
        "DROP TABLE builderops_outbox",
        "ALTER TABLE builderops_tasks DROP COLUMN payload",
        "DROP INDEX builderops_outbox_pending_idx",
    ),
)
def test_initialize_and_readiness_refuse_live_schema_drift(
    control_plane_store, envelope, schema_drift: str
) -> None:
    with control_plane_store._connect() as conn:
        conn.execute(schema_drift)

    with pytest.raises(RuntimeError, match="live schema does not match"):
        control_plane_store.initialize()
    with pytest.raises(RuntimeError, match="live schema does not match"):
        control_plane_store.readiness()


def test_initialize_refuses_to_recreate_a_missing_applied_migration_receipt(
    control_plane_store, envelope
) -> None:
    store = control_plane_store
    with store._connect() as conn:
        conn.execute("DELETE FROM builderops_schema_migrations WHERE version = 1")

    with pytest.raises(RuntimeError, match="ledger is empty or non-contiguous"):
        store.initialize()

    with store._connect() as conn:
        row = conn.execute("SELECT count(*) AS count FROM builderops_schema_migrations").fetchone()
    assert row is not None
    # Version 2 remains present; initialize must refuse the non-contiguous
    # lineage instead of silently recreating the deleted version 1 receipt.
    assert row["count"] == 1


@pytest.mark.parametrize(
    "partial_ddl",
    (
        "CREATE SEQUENCE builderops_receipt_sequence INCREMENT BY 7 START WITH 42",
        "CREATE FUNCTION builderops_partial() RETURNS boolean "
        "LANGUAGE sql IMMUTABLE AS 'SELECT true'",
        "CREATE TABLE unrelated(id integer); "
        "CREATE INDEX idx_builderops_orphan ON unrelated(id)",
    ),
)
def test_initialize_refuses_partial_non_table_builderops_schema(
    control_plane_store, envelope, partial_ddl: str
) -> None:
    schema = f"builderops_partial_{uuid4().hex}"
    with control_plane_store._connect() as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    store = PostgresBuilderOpsStore(_isolated_schema_dsn(control_plane_store.dsn, schema))
    try:
        with store._connect() as conn:
            conn.execute(partial_ddl)
        with pytest.raises(RuntimeError, match="missing migration or authority metadata"):
            store.initialize()
        with store._connect() as conn:
            assert (
                conn.execute(
                    "SELECT to_regclass(%s) AS relation",
                    (f"{schema}.builderops_schema_migrations",),
                ).fetchone()["relation"]
                is None
            )
    finally:
        with psycopg.connect(control_plane_store.dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
