from __future__ import annotations

import logging
import os
from pathlib import Path

import psycopg
from psycopg import Error
from psycopg.errors import InsufficientPrivilege
from psycopg.rows import dict_row

from app.db.dsn import connect as _connect, resolve_dsn
from app.settings import settings

_MIGRATION_SQL_PATH = Path(__file__).resolve().parent / "migrations_obsidian.sql"
_LOGGER = logging.getLogger(__name__)
_SCHEMA_INITIALIZED = False


def _psycopg_dsn() -> str:
    """Allow DATABASE_URL overrides while keeping Pydantic defaults."""
    url = os.getenv("DATABASE_URL")
    return resolve_dsn(url or settings.db_dsn)


def conn_ro():
    """Return a read-only psycopg connection configured for dict-row results."""
    return _connect(_psycopg_dsn(), autocommit=True, row_factory=dict_row)


def conn_rw():
    """Return a read/write psycopg connection configured for dict-row results."""
    conn = _connect(_psycopg_dsn(), row_factory=dict_row)
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
        except Error:
            conn.rollback()
            raise
