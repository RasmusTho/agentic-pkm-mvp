from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from app.db.db import COMPATIBILITY_BINDING_ID, conn_rw


def save_membership(object_id: str, set_id: str, *, trace_id: Optional[str] = None) -> None:
    """
    Binding-scoped membership persistence.

    Schema/key failures deliberately propagate: swallowing a missing MVR-05A4
    primary-key or binding invariant would falsely report a successful write.
    """
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
            common = (COMPATIBILITY_BINDING_ID, object_id, set_id, datetime.now(timezone.utc))
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
            else:
                raise RuntimeError(
                    "unsupported membership primary key; run MVR-05A4 migrations before writing"
                )
    return None


__all__ = ["save_membership"]
