"""Fail-loud preflight for the migration-owned ``decisions`` projection.

This is a database contract, not a legacy-store adapter concern: both active
decision writers and projection rebuilds must reject the pre-MVR-05A3 global
parent before they can write or replace their binding's projection.
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
        required_columns = {
            "id",
            "vault_binding_id",
            "object_id",
            "agent",
            "kind",
            "key",
            "value",
            "created_at",
        }
        if missing_columns := required_columns - {
            _row_value(row, "column_name", 0) for row in cur.fetchall()
        }:
            raise RuntimeError(
                f"{_DECISIONS_MIGRATION_HINT} Schema shape is stale. Missing columns: "
                f"{', '.join(sorted(missing_columns))}."
            )
        cur.execute(
            """
            SELECT object_col.is_nullable,
                   binding_col.is_nullable AS binding_nullable,
                   id_col.column_default,
                   count(fk.*) AS fk_count,
                   min(fk.child_columns) AS child_columns,
                   min(fk.parent_schema) AS parent_schema,
                   min(fk.parent_table) AS parent_table,
                   min(fk.parent_columns) AS parent_columns,
                   min(fk.delete_action) AS delete_action,
                   min(fk.delete_set_columns) AS delete_set_columns
              FROM information_schema.columns object_col
              JOIN information_schema.columns binding_col
                ON binding_col.table_schema = object_col.table_schema
               AND binding_col.table_name = object_col.table_name
               AND binding_col.column_name = 'vault_binding_id'
              JOIN information_schema.columns id_col
                ON id_col.table_schema = object_col.table_schema
               AND id_col.table_name = object_col.table_name
               AND id_col.column_name = 'id'
              LEFT JOIN LATERAL (
                  SELECT array_agg(child.attname ORDER BY ck.ordinality) AS child_columns,
                         pn.nspname AS parent_schema,
                         parent.relname AS parent_table,
                         array_agg(parent_att.attname ORDER BY ck.ordinality) AS parent_columns,
                         c.confdeltype::text AS delete_action,
                         COALESCE((
                             SELECT array_agg(del_att.attname ORDER BY dk.ordinality)
                               FROM unnest(c.confdelsetcols) WITH ORDINALITY dk(attnum, ordinality)
                               JOIN pg_attribute del_att
                                 ON del_att.attrelid = c.conrelid
                                AND del_att.attnum = dk.attnum
                         ), ARRAY[]::name[]) AS delete_set_columns
                    FROM pg_constraint c
                    JOIN pg_class parent ON parent.oid = c.confrelid
                    JOIN pg_namespace pn ON pn.oid = parent.relnamespace
                    JOIN unnest(c.conkey) WITH ORDINALITY ck(attnum, ordinality) ON true
                    JOIN pg_attribute child
                      ON child.attrelid = c.conrelid AND child.attnum = ck.attnum
                    JOIN pg_attribute parent_att
                      ON parent_att.attrelid = c.confrelid
                     AND parent_att.attnum = c.confkey[ck.ordinality]
                   WHERE c.conrelid = 'public.decisions'::regclass
                     AND c.contype = 'f'
                   GROUP BY c.oid, pn.nspname, parent.relname
              ) fk ON true
             WHERE object_col.table_schema = 'public'
               AND object_col.table_name = 'decisions'
               AND object_col.column_name = 'object_id'
             GROUP BY object_col.is_nullable, binding_col.is_nullable, id_col.column_default
            """
        )
        shape_row = cur.fetchone()
        if (
            shape_row is None
            or _row_value(shape_row, "is_nullable", 0) != "YES"
            or _row_value(shape_row, "binding_nullable", 1) != "YES"
            or "gen_random_uuid" not in (_row_value(shape_row, "column_default", 2) or "")
            or _row_value(shape_row, "fk_count", 3) != 1
            or list(_row_value(shape_row, "child_columns", 4) or [])
            != ["vault_binding_id", "object_id"]
            or _row_value(shape_row, "parent_schema", 5) != "public"
            or _row_value(shape_row, "parent_table", 6) != "store_objects"
            or list(_row_value(shape_row, "parent_columns", 7) or [])
            != ["vault_binding_id", "object_id"]
            or _row_value(shape_row, "delete_action", 8) != "n"
            or list(_row_value(shape_row, "delete_set_columns", 9) or []) != ["object_id"]
        ):
            raise RuntimeError(f"{_DECISIONS_MIGRATION_HINT} Schema shape is stale.")
