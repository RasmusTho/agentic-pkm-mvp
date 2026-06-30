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
    """Apply lightweight migrations stored alongside the db module."""
    if not _MIGRATION_SQL_PATH.exists():
        return
    statements = [
        stmt.strip()
        for stmt in _MIGRATION_SQL_PATH.read_text(encoding="utf-8").split(";")
        if stmt.strip()
    ]
    if not statements:
        return
    for statement in statements:
        try:
            with conn.cursor() as cur:
                cur.execute(statement)
        except InsufficientPrivilege:
            conn.rollback()
            _LOGGER.warning(
                "Skipping migration statement due to insufficient privileges",
                extra={"statement": statement},
            )
        except DependentObjectsStillExist:
            conn.rollback()
            upper_stmt = statement.upper()
            if "ALTER TABLE PUBLIC.OBJECTS DROP CONSTRAINT IF EXISTS OBJECTS_PKEY" in upper_stmt:
                _LOGGER.warning("Skipping legacy objects_pkey drop; dependent FKs exist")
                continue
            raise
        except DuplicateObject:
            conn.rollback()
            upper_stmt = statement.upper()
            if "ALTER TABLE PUBLIC.OBJECTS ADD CONSTRAINT OBJECTS_PKEY PRIMARY KEY (ID)" in upper_stmt:
                _LOGGER.info("objects_pkey already present; skipping duplicate ADD CONSTRAINT")
                continue
            raise
        except InvalidTableDefinition as exc:
            conn.rollback()
            upper_stmt = statement.upper()
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
            upper_stmt = statement.upper()
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
