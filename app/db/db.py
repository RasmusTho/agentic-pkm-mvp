from __future__ import annotations

import logging
import os
from pathlib import Path

import psycopg
from psycopg import Error
from psycopg.errors import DependentObjectsStillExist, DuplicateObject, InsufficientPrivilege
from psycopg.errors import UndefinedColumn
from psycopg.errors import InvalidTableDefinition
from psycopg.rows import dict_row

from app.config.database import resolve_runtime_database_url
from app.db.dsn import connect as _connect, resolve_dsn
from app.settings import settings

_MIGRATION_SQL_PATH = Path(__file__).resolve().parent / "migrations_obsidian.sql"
_LOGGER = logging.getLogger(__name__)
_SCHEMA_INITIALIZED = False

# MVR-05A0 (#4543): the stable binding id every `file_state` row is attributed to
# until MVR-05A (#3859) ships the compatibility ingress translator that derives
# the real authorized `vault_binding_id`
# (``app/instance/vault_registry.py::VaultRegistration.vault_binding_id``).
#
# It is deliberately an explicit sentinel and not a registry-shaped
# ``binding-<uuid4>`` value: a pre-MVR-05 database is single-binding by
# construction, so attributing its rows to one named legacy binding is provable
# rather than a guess, and MVR-05A's backfill can tell "not yet attributed"
# from "attributed to binding X" without inspecting the registry.
#
# Kept in sync with the same literal in Alembic revision ``c7f4b1a83d29`` by
# ``tests/migrations/test_file_state_adoption.py``.
FILE_STATE_COMPATIBILITY_BINDING_ID = "legacy-compatibility-binding"

# Test-fixture create-on-demand for the migration-owned `file_state` table,
# mirroring the KERNEL-04 (#2766) / KERNEL-05 (#2850) contract for `store_*` and
# `outbox`. Production DDL authority is Alembic revision `c7f4b1a83d29`; scratch
# databases opt in through STORE_SCHEMA_AUTOCREATE=1 (tests/conftest.py). Shape
# parity with the revision is asserted by
# tests/migrations/test_file_state_adoption.py.
_FILE_STATE_AUTOCREATE_SQL = (
    f"""
    CREATE TABLE IF NOT EXISTS public.file_state (
        path text NOT NULL,
        uuid text,
        fm_hash text,
        body_hash text,
        mtime timestamptz,
        last_seen timestamptz DEFAULT now(),
        vault_binding_id text NOT NULL DEFAULT '{FILE_STATE_COMPATIBILITY_BINDING_ID}',
        CONSTRAINT file_state_pkey PRIMARY KEY (vault_binding_id, path)
    )
    """,
    "CREATE INDEX IF NOT EXISTS file_state_uuid_idx ON public.file_state(uuid)",
    # `objects.path` moved to the same revision for the same reason; a scratch
    # database that never ran Alembic needs it for the watcher continuity mirror.
    "ALTER TABLE IF EXISTS public.objects ADD COLUMN IF NOT EXISTS path text",
)


def _schema_autocreate_enabled() -> bool:
    """Whether test fixtures opted into create-on-demand schema (KERNEL-04)."""
    return (os.getenv("STORE_SCHEMA_AUTOCREATE") or "").strip().lower() in {"1", "true", "yes"}


class FileStateSchemaMissingError(RuntimeError):
    """Raised when the migration-owned `file_state` schema is absent or stale."""


def assert_file_state_schema(conn: psycopg.Connection) -> None:
    """Fail loudly when the database predates Alembic revision `c7f4b1a83d29`.

    The `Invariant -> producers` rule in `AGENTS.md :: Required rules` pairs a
    runtime precondition with a fail-loud preflight, matching what KERNEL-04
    (#2766) and KERNEL-05 (#2850) do for `store_*` and `outbox`. Without it a
    stale database returns cleanly from `ensure_schema`, `conn_rw` latches
    `_SCHEMA_INITIALIZED`, and the operator learns about it only when the first
    vault-sync write raises an opaque invalid-conflict-target error part-way
    through a watcher tick.

    This is deliberately **not** called from `ensure_schema`. That function is a
    shared seam — `app/services/outbox.py::bootstrap` calls it too — and the
    `file_state` key is no concern of the outbox path. The one caller is the
    vault-sync seam in `app/services/vault_sync.py`, the sole consumer of the
    table.

    Checks the two things the rekey actually depends on: that the table exists,
    and that its primary key is `(vault_binding_id, path)`.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              to_regclass('public.file_state') IS NOT NULL AS table_exists,
              COALESCE((
                SELECT array_agg(att.attname ORDER BY key.ordinality)
                  FROM pg_constraint con
                  JOIN LATERAL unnest(con.conkey) WITH ORDINALITY key(attnum, ordinality)
                    ON true
                  JOIN pg_attribute att
                    ON att.attrelid = con.conrelid AND att.attnum = key.attnum
                 WHERE con.conrelid = to_regclass('public.file_state')
                   AND con.contype = 'p'
              ), ARRAY[]::text[]) AS primary_key
            """
        )
        row = cur.fetchone()
    if isinstance(row, dict):
        table_exists, primary_key = row["table_exists"], row["primary_key"]
    else:
        table_exists, primary_key = (row[0], row[1]) if row else (False, [])

    if not table_exists:
        raise FileStateSchemaMissingError(
            "public.file_state is missing. It is owned by Alembic revision "
            "c7f4b1a83d29 (MVR-05A0, #4543), not by the runtime bootstrap SQL. "
            "Run `alembic upgrade head` (scripts/run_migrations.sh) before "
            "starting a vault-sync producer."
        )
    if list(primary_key or []) != ["vault_binding_id", "path"]:
        raise FileStateSchemaMissingError(
            "public.file_state has primary key "
            f"{list(primary_key or [])!r}, expected ['vault_binding_id', 'path']. "
            "This database predates Alembic revision c7f4b1a83d29 (MVR-05A0, "
            "#4543); run `alembic upgrade head` (scripts/run_migrations.sh) "
            "before starting a vault-sync producer."
        )


def _autocreate_file_state(conn: psycopg.Connection) -> None:
    """Create the migration-owned `file_state`/`objects.path` shape for test scratch DBs.

    Inert outside tests: production DDL authority is Alembic revision
    `c7f4b1a83d29`. The matching fail-loud preflight for a database that never
    ran it is `assert_file_state_schema`, called from the vault-sync seam.
    """
    if not _schema_autocreate_enabled():
        return
    for statement in _FILE_STATE_AUTOCREATE_SQL:
        with conn.cursor() as cur:
            cur.execute(statement)


def _objects_id_primary_key_exists(conn: psycopg.Connection) -> bool:
    """Return whether ``objects`` already has exactly ``id`` as its primary key."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(
                bool_and(att.attname = 'id') AND count(*) = 1,
                false
            ) AS id_primary_key
            FROM pg_constraint constraint_row
            JOIN LATERAL unnest(constraint_row.conkey) WITH ORDINALITY key(attnum, position)
              ON true
            JOIN pg_attribute att
              ON att.attrelid = constraint_row.conrelid
             AND att.attnum = key.attnum
            WHERE constraint_row.conrelid = to_regclass('public.objects')
              AND constraint_row.contype = 'p'
            """
        )
        row = cur.fetchone()
    if not row:
        return False
    value = row.get("id_primary_key") if isinstance(row, dict) else row[0]
    return bool(value)


def _psycopg_dsn() -> str:
    """Allow DATABASE_URL overrides while keeping Pydantic defaults."""
    url = resolve_runtime_database_url(os.environ)
    return resolve_dsn(url or settings.db_dsn)


def conn_ro():
    """Return a read-only psycopg connection configured for dict-row results."""
    return _connect(_psycopg_dsn(), autocommit=True, row_factory=dict_row)


def conn_rw(*, connect_timeout: int | None = None):
    """Return a read/write psycopg connection configured for dict-row results.

    Pass ``connect_timeout`` (seconds) to bound the underlying socket connect for
    best-effort callers that must not stall when the DB host is unreachable.
    """
    kwargs: dict[str, object] = {"row_factory": dict_row}
    if connect_timeout is not None:
        kwargs["connect_timeout"] = connect_timeout
    conn = _connect(_psycopg_dsn(), **kwargs)
    global _SCHEMA_INITIALIZED
    if not _SCHEMA_INITIALIZED:
        ensure_schema(conn)
        conn.commit()
        _SCHEMA_INITIALIZED = True
    return conn


def ensure_schema(conn: psycopg.Connection) -> None:
    """Apply lightweight migrations stored alongside the db module.

    `file_state` and `objects.path` are no longer created here (MVR-05A0,
    #4543): Alembic revision `c7f4b1a83d29` owns both, so the revision chain can
    reach the vault-sync table its own verification lane runs against. Test
    scratch databases keep create-on-demand through the explicit
    STORE_SCHEMA_AUTOCREATE opt-in, applied after the bootstrap SQL because
    `ALTER TABLE IF EXISTS public.objects ADD COLUMN ... path` silently no-ops on
    a database where the bootstrap has not created `objects` yet. Outside tests
    that step is inert; the matching fail-loud preflight is
    `assert_file_state_schema`, called from the vault-sync seam rather than here,
    because this function is shared with the outbox bootstrap.
    """
    _apply_legacy_bootstrap_sql(conn)
    _autocreate_file_state(conn)


def _apply_legacy_bootstrap_sql(conn: psycopg.Connection) -> None:
    """Execute the remaining legacy compatibility DDL in `migrations_obsidian.sql`."""
    if not _MIGRATION_SQL_PATH.exists():
        return
    statements = [
        stmt.strip()
        for stmt in _MIGRATION_SQL_PATH.read_text(encoding="utf-8").split(";")
        if stmt.strip()
    ]
    if not statements:
        return
    objects_id_primary_key_ready: bool | None = None
    for statement in statements:
        upper_stmt = statement.upper()
        rewrites_objects_primary_key = (
            "ALTER TABLE PUBLIC.OBJECTS DROP CONSTRAINT IF EXISTS OBJECTS_PKEY" in upper_stmt
            or "ALTER TABLE PUBLIC.OBJECTS ADD CONSTRAINT OBJECTS_PKEY PRIMARY KEY (ID)" in upper_stmt
        )
        if rewrites_objects_primary_key:
            if objects_id_primary_key_ready is None:
                objects_id_primary_key_ready = _objects_id_primary_key_exists(conn)
            if objects_id_primary_key_ready:
                continue
        try:
            with conn.cursor() as cur:
                cur.execute(statement)
            if "ALTER TABLE PUBLIC.OBJECTS ADD CONSTRAINT OBJECTS_PKEY PRIMARY KEY (ID)" in upper_stmt:
                objects_id_primary_key_ready = True
        except InsufficientPrivilege:
            conn.rollback()
            _LOGGER.warning(
                "Skipping migration statement due to insufficient privileges",
                extra={"statement": statement},
            )
        except DependentObjectsStillExist:
            conn.rollback()
            if "ALTER TABLE PUBLIC.OBJECTS DROP CONSTRAINT IF EXISTS OBJECTS_PKEY" in upper_stmt:
                _LOGGER.warning("Skipping legacy objects_pkey drop; dependent FKs exist")
                continue
            raise
        except DuplicateObject:
            conn.rollback()
            if "ALTER TABLE PUBLIC.OBJECTS ADD CONSTRAINT OBJECTS_PKEY PRIMARY KEY (ID)" in upper_stmt:
                _LOGGER.info("objects_pkey already present; skipping duplicate ADD CONSTRAINT")
                continue
            raise
        except InvalidTableDefinition as exc:
            conn.rollback()
            if (
                "ALTER TABLE PUBLIC.OBJECTS ADD CONSTRAINT OBJECTS_PKEY PRIMARY KEY (ID)" in upper_stmt
                and "MULTIPLE PRIMARY KEYS FOR TABLE" in str(exc).upper()
            ):
                _LOGGER.warning(
                    "objects table already has a primary key; skipping add-constraint statement"
                )
                continue
            raise
        except UndefinedColumn as exc:
            conn.rollback()
            if (
                "CREATE INDEX" in upper_stmt
                and "OBJECTS_SOURCE_REF_IDX" in upper_stmt
                and "SOURCE_REF" in str(exc).upper()
            ):
                _LOGGER.warning("objects.source_ref missing; skipping objects_source_ref_idx")
                continue
            raise
        except Error:
            conn.rollback()
            raise
