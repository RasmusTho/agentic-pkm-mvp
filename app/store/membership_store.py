from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from app.db.db import COMPATIBILITY_BINDING_ID, conn_rw
def _resolve_binding_id(vault_binding_id: str | None) -> str:
    """Keep scalar-era callers on compatibility until MVR-05B routes context."""
    requested = (vault_binding_id or "").strip()
    if vault_binding_id is None:
        return COMPATIBILITY_BINDING_ID
    if not requested:
        raise ValueError("vault_binding_id must be a non-empty string")
    return requested


def save_membership(
    object_id: str,
    set_name: str,
    *,
    trace_id: Optional[str] = None,
    vault_binding_id: str | None = None,
) -> None:
    """
    Binding-scoped membership persistence.

    ``set_name`` is resolved through the stable ``sets`` registry before the
    UUID endpoint is written on either supported membership lineage.
    Schema/key failures deliberately propagate: swallowing a missing MVR-05A4
    primary-key or binding invariant would falsely report a successful write.
    """
    resolved_binding_id = _resolve_binding_id(vault_binding_id)
    with conn_rw() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT array_agg(a.attname ORDER BY key.ordinality) AS primary_key
                  FROM pg_constraint c
                  JOIN unnest(c.conkey) WITH ORDINALITY key(attnum, ordinality) ON true
                  JOIN pg_attribute a
                    ON a.attrelid=c.conrelid AND a.attnum=key.attnum
                 WHERE c.conrelid='public.membership'::regclass AND c.contype='p'
                """
            )
            row = cur.fetchone()
            primary_key = (
                row.get("primary_key") if isinstance(row, dict) else (row[0] if row else None)
            )
            if list(primary_key or []) not in (
                ["vault_binding_id", "id"],
                ["vault_binding_id", "object_id", "set_id"],
            ):
                raise RuntimeError(
                    "unsupported membership primary key; run MVR-05A4 migrations before writing"
                )

            cur.execute(
                """
                SELECT (
                         SELECT array_agg(a.attname ORDER BY key.ordinality)
                           FROM pg_constraint c
                           JOIN unnest(c.conkey) WITH ORDINALITY key(attnum, ordinality)
                             ON true
                           JOIN pg_attribute a
                             ON a.attrelid=c.conrelid AND a.attnum=key.attnum
                          WHERE c.conrelid='public.sets'::regclass AND c.contype='p'
                       ) AS primary_key,
                       EXISTS (
                         SELECT 1 FROM pg_index i
                          WHERE i.indrelid='public.sets'::regclass AND i.indisunique
                            AND (SELECT array_agg(a.attname::text ORDER BY key.ordinality)
                                   FROM unnest(i.indkey::smallint[])
                                        WITH ORDINALITY key(attnum, ordinality)
                                   JOIN pg_attribute a
                                     ON a.attrelid=i.indrelid AND a.attnum=key.attnum)
                                = ARRAY['vault_binding_id','name']::text[]
                       ) AS has_binding_name_unique,
                       NOT EXISTS (
                         SELECT 1 FROM pg_index i
                          WHERE i.indrelid='public.sets'::regclass AND i.indisunique
                            AND (
                              i.indexprs IS NOT NULL
                              OR i.indpred IS NOT NULL
                              OR NOT EXISTS (
                                SELECT 1 FROM unnest(i.indkey::smallint[]) key(attnum)
                                JOIN pg_attribute a
                                  ON a.attrelid=i.indrelid AND a.attnum=key.attnum
                               WHERE a.attname='vault_binding_id'
                              )
                            )
                       ) AS has_no_global_unique
                """
            )
            set_shape = cur.fetchone()
            set_primary_key = (
                set_shape.get("primary_key")
                if isinstance(set_shape, dict)
                else (set_shape[0] if set_shape else None)
            )
            has_binding_name_unique = (
                set_shape.get("has_binding_name_unique")
                if isinstance(set_shape, dict)
                else (set_shape[1] if set_shape else False)
            )
            has_no_global_unique = (
                set_shape.get("has_no_global_unique")
                if isinstance(set_shape, dict)
                else (set_shape[2] if set_shape else False)
            )
            if (
                list(set_primary_key or []) != ["vault_binding_id", "id"]
                or not has_binding_name_unique
                or not has_no_global_unique
            ):
                raise RuntimeError(
                    "unsupported sets binding-key constraints; run MVR-05A residual "
                    "migrations before writing"
                )

            cur.execute(
                "SELECT id FROM sets WHERE vault_binding_id = %s AND name = %s",
                (resolved_binding_id, set_name),
            )
            set_row = cur.fetchone()
            set_id = (
                set_row.get("id")
                if isinstance(set_row, dict)
                else (set_row[0] if set_row else None)
            )
            if set_id is None:
                raise RuntimeError(
                    f"membership set {set_name!r} does not exist; "
                    "run alembic upgrade head to seed membership prerequisites"
                )

            common = (resolved_binding_id, object_id, set_id, datetime.now(timezone.utc))
            if list(primary_key or []) == ["vault_binding_id", "id"]:
                cur.execute(
                    "INSERT INTO membership "
                    "(vault_binding_id,id,object_id,set_id,created_at) "
                    "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (common[0], uuid4(), *common[1:]),
                )
            elif list(primary_key or []) == ["vault_binding_id", "object_id", "set_id"]:
                cur.execute(
                    "INSERT INTO membership "
                    "(vault_binding_id,object_id,set_id,created_at) "
                    "VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    common,
                )
    return None


__all__ = ["save_membership"]
