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
                INSERT INTO membership (
                    vault_binding_id, id, object_id, set_id, created_at
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    COMPATIBILITY_BINDING_ID,
                    uuid4(),
                    object_id,
                    set_id,
                    datetime.now(timezone.utc),
                ),
            )
    return None


__all__ = ["save_membership"]
