from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.db.db import conn_rw


def save_membership(object_id: str, set_id: str, *, trace_id: Optional[str] = None) -> None:
    """
    Best-effort membership persistence.
    Inserts into membership table when DB is available; no-ops otherwise.
    """
    try:
        with conn_rw() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO membership (object_id, set_id, created_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (object_id, set_id, datetime.now(timezone.utc)),
                )
    except Exception:
        # offline/pytest path with no DB
        return None
    return None


__all__ = ["save_membership"]
