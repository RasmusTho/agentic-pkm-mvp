from __future__ import annotations

from typing import Any

import psycopg
from psycopg import sql


ExceptionRow = tuple | dict[str, Any]


def _extract_single_value(row: ExceptionRow) -> Any | None:
    if row is None:
        return None
    if isinstance(row, dict):
        if not row:
            return None
        return next(iter(row.values()))
    return row[0]


def table_exists(conn: psycopg.Connection, table_name: str) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass(%s)", (table_name,))
            row = cur.fetchone()
        return bool(_extract_single_value(row))
    except Exception:
        return False


def table_count(conn: psycopg.Connection, table_name: str) -> int:
    try:
        with conn.cursor() as cur:
            stmt = sql.SQL("SELECT count(*) FROM {}")
            stmt = stmt.format(sql.Identifier(table_name))
            cur.execute(stmt)
            row = cur.fetchone()
        value = _extract_single_value(row)
        if value is None:
            return 0
        return int(value)
    except Exception:
        return 0


def choose_object_table(conn: psycopg.Connection) -> str:
    if table_exists(conn, "store_objects"):
        store_count = table_count(conn, "store_objects")
        objects_exists = table_exists(conn, "objects")
        objects_count = table_count(conn, "objects") if objects_exists else 0
        if store_count == 0 and objects_count > 0:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO store_objects (object_id, kind, source_ref, payload, created_at, updated_at)
                        SELECT id, kind, source_ref, payload, created_at, now()
                        FROM objects
                        ON CONFLICT (object_id) DO NOTHING
                        """
                    )
            except Exception:
                # Best-effort migration for legacy tables; keep runtime read path stable.
                pass
        return "store_objects"
    return "objects"


def __getattr__(name: str):
    if name in {"engine", "SessionLocal", "Base", "conn_ro", "conn_rw", "ensure_schema"}:
        from . import sqlalchemy as _sa

        return getattr(_sa, name)
    if name in {"resolve_dsn"}:
        from .dsn import resolve_dsn

        return resolve_dsn
    raise AttributeError(name)


__all__ = (
    "engine",
    "SessionLocal",
    "Base",
    "conn_ro",
    "conn_rw",
    "ensure_schema",
    "resolve_dsn",
    "table_exists",
    "table_count",
    "choose_object_table",
)
