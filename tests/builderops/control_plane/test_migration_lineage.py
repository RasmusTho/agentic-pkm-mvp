from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from app.builderops.control_plane import PostgresBuilderOpsStore
from app.builderops.control_plane.migrations import (
    AUTHORITY_EPOCH,
    MIGRATIONS,
    SCHEMA_VERSION,
)

pytestmark = pytest.mark.pg


def _isolated_schema_dsn(dsn: str, schema: str) -> str:
    parts = urlsplit(dsn)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema},public"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _initialize_schema_at_version(
    store: PostgresBuilderOpsStore, version: int
) -> None:
    with store._connect() as conn:
        for migration_version, path in enumerate(MIGRATIONS[:version], start=1):
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO builderops_schema_migrations(version, name, checksum) "
                "VALUES (%s, %s, %s)",
                (
                    migration_version,
                    path.name,
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                ),
            )
        conn.execute(
            "INSERT INTO builderops_authority_metadata("
            "singleton, authority_epoch, schema_version, schema_fingerprint) "
            "VALUES (true, %s, %s, %s)",
            (AUTHORITY_EPOCH, version, store._schema_fingerprint(conn)),
        )


def test_initialize_refuses_newer_schema_and_preserves_runtime_authority_epoch(
    control_plane_store, envelope
) -> None:
    store = control_plane_store
    seeded_epoch = store.readiness()["authority_epoch"]
    assert seeded_epoch > 1
    future_version = SCHEMA_VERSION + 1
    with store._connect() as conn:
        conn.execute(
            "INSERT INTO builderops_schema_migrations(version, name, checksum) "
            "VALUES (%s, %s, 'future')",
            (future_version, f"{future_version:04d}_future.sql"),
        )
        conn.execute(
            "UPDATE builderops_authority_metadata "
            "SET authority_epoch = %s, schema_version = %s WHERE singleton",
            (seeded_epoch, future_version),
        )

    with pytest.raises(RuntimeError, match="newer or unknown migration version"):
        store.initialize()
    assert store.readiness() == {
        "authority_epoch": seeded_epoch,
        "schema_version": future_version,
    }

    with store._connect() as conn:
        conn.execute(
            "DELETE FROM builderops_schema_migrations WHERE version = %s",
            (future_version,),
        )
        conn.execute(
            "UPDATE builderops_authority_metadata "
            "SET authority_epoch = %s, schema_version = %s WHERE singleton",
            (seeded_epoch, SCHEMA_VERSION),
        )
    store.initialize()
    assert store.readiness() == {
        "authority_epoch": seeded_epoch,
        "schema_version": SCHEMA_VERSION,
    }


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
    seeded_epoch = control_plane_store.readiness()["authority_epoch"]
    assert seeded_epoch > 1
    control_plane_store.initialize()
    assert control_plane_store.readiness() == {
        "authority_epoch": seeded_epoch,
        "schema_version": SCHEMA_VERSION,
    }


def test_row_derived_post_effect_migration_is_backward_compatible(
    control_plane_store, envelope
) -> None:
    schema = f"builderops_row_derived_{uuid4().hex}"
    with control_plane_store._connect() as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    store = PostgresBuilderOpsStore(_isolated_schema_dsn(control_plane_store.dsn, schema))
    try:
        _initialize_schema_at_version(store, SCHEMA_VERSION - 1)
        store.initialize()
        with store._connect() as conn:
            row = conn.execute(
                "SELECT post_effect_phase, post_effect_claim_lsn::text AS claim_lsn "
                "FROM builderops_outbox LIMIT 1"
            ).fetchone()
        assert row is None
    finally:
        with psycopg.connect(control_plane_store.dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


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
    # Every version after 1 remains present; initialize must refuse the non-contiguous
    # lineage instead of silently recreating the deleted version 1 receipt.
    assert row["count"] == SCHEMA_VERSION - 1


def test_initialize_upgrades_v2_preserving_data_and_replacing_reconciliation_constraint(
    control_plane_store, envelope
) -> None:
    schema = f"builderops_upgrade_{uuid4().hex}"
    with control_plane_store._connect() as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    store = PostgresBuilderOpsStore(
        _isolated_schema_dsn(control_plane_store.dsn, schema)
    )
    try:
        _initialize_schema_at_version(store, 2)
        # Seed the actual v2 table shape. The current writer requires v5
        # admission and must never be used as an old-version writer fixture.
        operation_key = "v2-preserved-effect"
        authority = Jsonb(envelope.as_json())
        with store._connect() as conn:
            conn.execute(
                "INSERT INTO builderops_tasks(repository, task_id, state, authority_envelope) "
                "VALUES (%s, 'v2-preserved-task', 'effect_pending', %s)",
                (envelope.repository, authority),
            )
            conn.execute(
                "INSERT INTO builderops_outbox(repository, operation_key, task_id, effect_type, "
                "payload, status, intent_receipt_sequence, intent_lsn, worker_id, "
                "claim_fencing_token, claim_receipt_sequence, claim_lsn, authority_envelope) "
                "VALUES (%s, %s, 'v2-preserved-task', 'github.comment', '{}', 'pending', "
                "1, '0/1', 'v2-outbox-worker', 1, 2, '0/2', %s)",
                (envelope.repository, operation_key, authority),
            )
            conn.execute(
                "INSERT INTO builderops_outbox_reconciliations(repository, operation_key, "
                "task_id, worker_id, claim_fencing_token, claim_receipt_sequence, claim_lsn, "
                "observed_applied, evidence, request_hash, status, receipt_sequence, "
                "recovery_lsn, authority_envelope) VALUES (%s, %s, 'v2-preserved-task', "
                "'v2-outbox-worker', 1, 2, '0/2', false, %s, 'v2-request', 'pending', 3, '0/3', %s)",
                (envelope.repository, operation_key, Jsonb({"readback": "not-found"}), authority),
            )

        store.initialize()

        assert store.readiness()["authority_epoch"] > AUTHORITY_EPOCH
        assert store.readiness()["schema_version"] == SCHEMA_VERSION
        assert store.bootstrap_status()["writers_enabled"] is False
        assert store.get_task(envelope.repository, "v2-preserved-task")["state"] == "effect_pending"
        assert store.outbox_status(envelope.repository, operation_key) == "unknown"
        with store._connect() as conn:
            reconciliation = conn.execute(
                "SELECT status, evidence FROM builderops_outbox_reconciliations "
                "WHERE repository = %s AND operation_key = %s",
                (envelope.repository, operation_key),
            ).fetchone()
            versions = [int(row["version"]) for row in conn.execute(
                "SELECT version FROM builderops_schema_migrations ORDER BY version").fetchall()]
            assert reconciliation == {"status": "pending", "evidence": {"readback": "not-found"}}
            assert versions == list(range(1, SCHEMA_VERSION + 1))
            # The v3 constraint upgrade remains usable by recovery while the
            # v5 fence correctly keeps all ordinary writers disabled.
            store._assert_reconciliation_admitted(conn)
            conn.execute(
                "UPDATE builderops_outbox_reconciliations SET status='dead_letter' "
                "WHERE repository=%s AND operation_key=%s", (envelope.repository, operation_key))
            assert conn.execute(
                "SELECT status FROM builderops_outbox_reconciliations "
                "WHERE repository=%s AND operation_key=%s", (envelope.repository, operation_key)
            ).fetchone()["status"] == "dead_letter"
    finally:
        with psycopg.connect(control_plane_store.dsn, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


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
