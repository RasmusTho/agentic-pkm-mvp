"""Fail-loud preflight for the migration-owned ``decisions`` projection.

This is a database contract, not a legacy-store adapter concern: both active
decision writers and projection rebuilds must reject a pre-#3510 parent before
they can write (or truncate) the projection.
"""

from __future__ import annotations

from typing import Any


_DECISIONS_MIGRATION_HINT = (
    "Decisions schema is migration-owned (#3488): run 'alembic upgrade head' "
    "against this database. See docs/DB_SCHEMA.md :: decisions."
)


def _row_value(row: Any, key: str, index: int) -> Any:
    return row.get(key) if isinstance(row, dict) else row[index]


def assert_decisions_schema(conn: Any) -> None:
    """Assert the Alembic-owned decisions schema without runtime mutation."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.decisions')")
        table_row = cur.fetchone()
        if table_row is None or _row_value(table_row, "to_regclass", 0) is None:
            raise RuntimeError(_DECISIONS_MIGRATION_HINT)
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'decisions'
            """
        )
        required_columns = {"id", "object_id", "agent", "kind", "key", "value", "created_at"}
        if missing_columns := required_columns - {
            _row_value(row, "column_name", 0) for row in cur.fetchall()
        }:
            raise RuntimeError(
                f"{_DECISIONS_MIGRATION_HINT} Missing columns: {', '.join(sorted(missing_columns))}."
            )
        cur.execute(
            """
            SELECT
                object_id_column.is_nullable,
                id_column.column_default,
                fk.fk_count,
                fk.referenced_table_schema,
                fk.referenced_table_name,
                fk.referenced_column_name,
                fk.delete_rule
            FROM information_schema.columns AS object_id_column
            JOIN information_schema.columns AS id_column
              ON id_column.table_schema = object_id_column.table_schema
             AND id_column.table_name = object_id_column.table_name
             AND id_column.column_name = 'id'
            LEFT JOIN (
                SELECT
                    COUNT(*) AS fk_count,
                    MIN(ccu.table_schema) AS referenced_table_schema,
                    MIN(ccu.table_name) AS referenced_table_name,
                    MIN(ccu.column_name) AS referenced_column_name,
                    MIN(rc.delete_rule) AS delete_rule
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                JOIN information_schema.referential_constraints AS rc
                  ON rc.constraint_name = tc.constraint_name
                 AND rc.constraint_schema = tc.table_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.constraint_schema = tc.table_schema
                WHERE tc.table_schema = 'public'
                  AND tc.table_name = 'decisions'
                  AND tc.constraint_type = 'FOREIGN KEY'
                  AND kcu.column_name = 'object_id'
            ) AS fk ON TRUE
            WHERE object_id_column.table_schema = 'public'
              AND object_id_column.table_name = 'decisions'
              AND object_id_column.column_name = 'object_id'
            """
        )
        shape_row = cur.fetchone()
        if (
            shape_row is None
            or _row_value(shape_row, "is_nullable", 0) != "YES"
            or "gen_random_uuid" not in (_row_value(shape_row, "column_default", 1) or "")
            or tuple(
                _row_value(shape_row, key, index)
                for index, key in enumerate(
                    (
                        "referenced_table_schema",
                        "referenced_table_name",
                        "referenced_column_name",
                        "delete_rule",
                    ),
                    start=3,
                )
            )
            != ("public", "store_objects", "object_id", "SET NULL")
            or _row_value(shape_row, "fk_count", 2) != 1
        ):
            raise RuntimeError(f"{_DECISIONS_MIGRATION_HINT} Schema shape is stale.")
