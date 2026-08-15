from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

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
    future_version = SCHEMA_VERSION + 1
    with store._connect() as conn:
        conn.execute(
            "INSERT INTO builderops_schema_migrations(version, name, checksum) "
            "VALUES (%s, %s, 'future')",
            (future_version, f"{future_version:04d}_future.sql"),
        )
        conn.execute(
            "UPDATE builderops_authority_metadata "
            "SET authority_epoch = 2, schema_version = %s WHERE singleton",
            (future_version,),
        )

    with pytest.raises(RuntimeError, match="newer or unknown migration version"):
        store.initialize()
    assert store.readiness() == {
        "authority_epoch": 2,
        "schema_version": future_version,
    }

    with store._connect() as conn:
        conn.execute(
            "DELETE FROM builderops_schema_migrations WHERE version = %s",
            (future_version,),
        )
        conn.execute(
            "UPDATE builderops_authority_metadata "
            "SET authority_epoch = 2, schema_version = %s WHERE singleton",
            (SCHEMA_VERSION,),
        )
    store.initialize()
    assert store.readiness() == {
        "authority_epoch": 2,
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
    control_plane_store.initialize()
    assert control_plane_store.readiness() == {
        "authority_epoch": 1,
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
        store.commit_transition(
            envelope=envelope,
            task_id="v2-preserved-task",
            to_state="ready",
            idempotency_key="v2-preserved-create",
            request={"command": "create"},
        )
        _, lease = store.claim_task(
            envelope=envelope,
            task_id="v2-preserved-task",
            holder="v2-executor",
            idempotency_key="v2-preserved-claim",
            request={"command": "claim"},
        )
        pending = store.commit_transition(
            envelope=envelope,
            task_id="v2-preserved-task",
            to_state="effect_pending",
            idempotency_key="v2-preserved-effect",
            request={"command": "schedule-effect"},
            outbox={
                "effect_type": "github.comment",
                "payload": {"issue": 3603},
            },
            lease=lease,
        )
        pending_claim = store.claim_outbox(
            envelope=envelope,
            operation_key=pending.operation_key,
            worker_id="v2-outbox-worker",
        )
        store.mark_effect_unknown(pending_claim, detail="v2 readback required")
        store.reconcile_outbox(
            pending_claim,
            observed_applied=False,
            evidence={"readback": "not-found"},
        )
        assert store.readiness() == {
            "authority_epoch": AUTHORITY_EPOCH,
            "schema_version": 2,
        }

        store.initialize()

        assert store.readiness() == {
            "authority_epoch": AUTHORITY_EPOCH,
            "schema_version": SCHEMA_VERSION,
        }
        assert store.get_task(
            envelope.repository, "v2-preserved-task"
        )["state"] == "effect_pending"
        with store._connect() as conn:
            reconciliation = conn.execute(
                "SELECT status FROM builderops_outbox_reconciliations "
                "WHERE repository = %s AND operation_key = %s",
                (envelope.repository, pending.operation_key),
            ).fetchone()
            versions = [
                int(row["version"])
                for row in conn.execute(
                    "SELECT version FROM builderops_schema_migrations ORDER BY version"
                ).fetchall()
            ]
        assert reconciliation is not None
        assert reconciliation["status"] == "pending"
        assert versions == list(range(1, SCHEMA_VERSION + 1))

        store.commit_transition(
            envelope=envelope,
            task_id="v3-dead-letter-task",
            to_state="ready",
            idempotency_key="v3-dead-letter-create",
            request={"command": "create"},
        )
        _, dead_letter_lease = store.claim_task(
            envelope=envelope,
            task_id="v3-dead-letter-task",
            holder="v3-executor",
            idempotency_key="v3-dead-letter-claim",
            request={"command": "claim"},
        )
        dead_letter = store.commit_transition(
            envelope=envelope,
            task_id="v3-dead-letter-task",
            to_state="effect_pending",
            idempotency_key="v3-dead-letter-effect",
            request={
                "contract_version": "builderops_verification_run.v1",
                "run": {
                    "coordinator_session_id": None,
                    "context_pack": None,
                },
            },
            outbox={
                "effect_type": "model.verification_coordinator",
                "payload": {"head_sha": "a" * 40},
            },
            lease=dead_letter_lease,
        )
        dead_letter_claim = store.claim_outbox(
            envelope=envelope,
            operation_key=dead_letter.operation_key,
            worker_id="v3-verification-host",
        )
        store.mark_effect_unknown(
            dead_letter_claim,
            detail="provider session identity was not durably observed",
        )
        terminal = store.reconcile_outbox(
            dead_letter_claim,
            observed_applied=False,
            terminal_unknown=True,
            evidence={
                "head_sha": "a" * 40,
                "outcome": "indeterminate_pre_session_model_effect",
                "provider_session_id": None,
                "relaunch_performed": False,
            },
        )
        assert terminal.status == "dead_letter"
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
