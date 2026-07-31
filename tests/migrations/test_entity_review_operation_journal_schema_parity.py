"""Entity-review operation journal schema parity (EROJ-01, #4350).

The `entity_review_operations` table is migration-owned (Alembic revision
`e7a2b9c4d1f8`) with assert-only runtime preflight, following the
KERNEL-04/KERNEL-05 pattern (`tests/migrations/test_store_schema_parity.py`,
`tests/migrations/test_outbox_schema_parity.py`). This module asserts
INV-EROJ-8's producer set stays coherent:

- `test_entity_review_operation_journal_schema_matches_head` — a fresh
  `alembic upgrade head` produces exactly the audited shape the module's
  test-only autocreate producer (`STORE_SCHEMA_AUTOCREATE=1`) creates,
  including the state CHECK constraint and the partial unique
  active-entry index.
- `test_upgrade_idempotent_on_existing` — re-running migrations over an
  environment that already carries the autocreated table is a no-op and
  moves no data.
- `test_missing_schema_fails_with_migration_guidance` — the runtime
  assertion fails loud with `alembic upgrade head` guidance when the table
  is absent and autocreate is off (stale-schema posture outside tests).

Spec: docs/ENTITY_REVIEW_OPERATION_JOURNAL/COMMIT_OPERATION_AND_OUTBOX_VISIBILITY.md
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[2]

# The head revision immediately before the journal table became owned.
PRE_JOURNAL_HEAD = "d0f5b2c7e4a6"

# The EROJ-01 journal-schema-owning revision. Pinned explicitly (not "head")
# so later migrations adding DDL on top don't turn this into a moving target.
JOURNAL_SCHEMA_HEAD = "e7a2b9c4d1f8"

TABLE = "entity_review_operations"


def _admin_dsn() -> str:
    from app.db.dsn import resolve_dsn

    dsn = resolve_dsn()
    if not dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    return dsn


def _scratch_dsn(admin_dsn: str, dbname: str) -> str:
    base, _, _ = admin_dsn.rpartition("/")
    return f"{base}/{dbname}"


@pytest.fixture
def scratch_db_factory(monkeypatch: pytest.MonkeyPatch):
    """Create throwaway databases on the configured Postgres; drop them after."""
    admin_dsn = _admin_dsn()
    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=2)
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")
    probe.close()

    created: list[str] = []

    def _create() -> str:
        name = f"scratch_eroj01_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{name}"')
        created.append(name)
        dsn = _scratch_dsn(admin_dsn, name)
        # An earlier migration declares `embedding VECTOR` unconditionally, so
        # the extension must exist before `alembic upgrade` (mirrors
        # tests/migrations/test_outbox_schema_parity.py).
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        return dsn

    yield _create

    for name in created:
        try:
            with psycopg.connect(admin_dsn, autocommit=True) as conn:
                conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        except Exception:  # pragma: no cover - cleanup best effort
            pass


def _alembic_upgrade(dsn: str, monkeypatch: pytest.MonkeyPatch, revision: str = "head") -> None:
    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    command.upgrade(cfg, revision)


def _run_module_autocreate(dsn: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The module's test-only create-on-demand producer (STORE_SCHEMA_AUTOCREATE)."""
    from app.heimdal import entity_review_operation_journal as journal_module

    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    with psycopg.connect(dsn) as conn:
        journal_module.ensure_journal_schema(conn)


def _schema_snapshot(dsn: str) -> dict:
    """Column/PK/index/check shape of the journal table, normalized."""
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name, data_type, is_nullable,
                       COALESCE(column_default, '') AS column_default
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY column_name
                """,
                (TABLE,),
            )
            columns = [tuple(row) for row in cur.fetchall()]
            cur.execute(
                """
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = 'public'
                  AND tc.table_name = %s
                  AND tc.constraint_type = 'PRIMARY KEY'
                ORDER BY kcu.ordinal_position
                """,
                (TABLE,),
            )
            pk = [row[0] for row in cur.fetchall()]
            cur.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'public' AND tablename = %s
                ORDER BY indexname
                """,
                (TABLE,),
            )
            indexes = [tuple(row) for row in cur.fetchall()]
            # Auto-generated NOT NULL check rows carry per-database OIDs in
            # their names (`2200_<oid>_<n>_not_null`) and can never compare
            # across databases; nullability is already covered by the columns
            # snapshot, so keep only explicitly named CHECK constraints.
            cur.execute(
                """
                SELECT cc.constraint_name, cc.check_clause
                FROM information_schema.check_constraints cc
                JOIN information_schema.table_constraints tc
                  ON cc.constraint_name = tc.constraint_name
                 AND cc.constraint_schema = tc.table_schema
                WHERE tc.table_schema = 'public'
                  AND tc.table_name = %s
                  AND tc.constraint_type = 'CHECK'
                  AND cc.constraint_name NOT LIKE '%%\\_not\\_null' ESCAPE '\\'
                ORDER BY cc.constraint_name
                """,
                (TABLE,),
            )
            checks = [tuple(row) for row in cur.fetchall()]
    return {"columns": columns, "pk": pk, "indexes": indexes, "checks": checks}


def test_entity_review_operation_journal_schema_matches_head(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fresh-DB `alembic upgrade head` == the module's audited autocreate shape."""
    migrated = scratch_db_factory()
    autocreated = scratch_db_factory()

    _alembic_upgrade(migrated, monkeypatch, "head")
    _run_module_autocreate(autocreated, monkeypatch)

    migrated_shape = _schema_snapshot(migrated)
    autocreated_shape = _schema_snapshot(autocreated)

    assert migrated_shape == autocreated_shape, (
        "Alembic-produced entity_review_operations schema diverges from the module's "
        "autocreate shape:\n"
        f"alembic: {json.dumps(migrated_shape, indent=2, default=str)}\n"
        f"autocreate: {json.dumps(autocreated_shape, indent=2, default=str)}"
    )
    assert migrated_shape["columns"], "journal table missing after alembic upgrade head"
    assert any(
        "state <> 'cleared'" in indexdef for _, indexdef in migrated_shape["indexes"]
    ), "the partial unique active-entry index is missing"
    assert migrated_shape["checks"], "the state CHECK constraint is missing"


def test_upgrade_idempotent_on_existing(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing environments (pre-EROJ head + autocreated table) no-op with data kept."""
    dsn = scratch_db_factory()

    _alembic_upgrade(dsn, monkeypatch, PRE_JOURNAL_HEAD)
    _run_module_autocreate(dsn, monkeypatch)

    operation_id = uuid.uuid4()
    with psycopg.connect(dsn) as conn:
        conn.execute(
            f"INSERT INTO {TABLE} (operation_id, vault_identity, queue_entry_id, "
            "decision_position, decision_digest, from_id, into_id, state, outbox_event_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                operation_id,
                "/vault",
                "review:mention:x",
                0,
                "d" * 64,
                "ent:a",
                "ent:b",
                "claimed",
                uuid.uuid4(),
            ),
        )
        conn.commit()

    before = _schema_snapshot(dsn)
    _alembic_upgrade(dsn, monkeypatch, JOURNAL_SCHEMA_HEAD)
    after = _schema_snapshot(dsn)

    assert before == after, "Migration changed an existing environment's journal schema"
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            f"SELECT count(*) FROM {TABLE} WHERE operation_id = %s", (operation_id,)
        ).fetchone()
    assert row == (1,), "Migration moved/destroyed existing journal data"


def test_missing_schema_fails_with_migration_guidance(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Assert-only outside tests: stale schema directs to `alembic upgrade head`."""
    from app.heimdal.entity_review_operation_journal import (
        EntityReviewOperationJournal,
        EntityReviewOperationSchemaMissingError,
    )

    dsn = scratch_db_factory()  # no journal table installed
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "0")
    journal = EntityReviewOperationJournal(
        connection_factory=lambda: psycopg.connect(dsn)
    )
    with pytest.raises(EntityReviewOperationSchemaMissingError, match="alembic upgrade head"):
        journal.claim_operation(
            vault_identity="/vault",
            queue_entry_id="review:mention:x",
            decision_position=0,
            decision_digest="d" * 64,
            from_id="ent:a",
            into_id="ent:b",
        )
