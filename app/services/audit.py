from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import json

from app.db.db import conn_rw

def audit_event(
    *,
    event: str,
    object_id: str | None,
    agent: str,
    trace_id: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """
    Best-effort audit logger.
    Writes to audit table if DB is up, otherwise silently no-ops for pytest.
    """
    payload = {
        "event": event,
        "agent": agent,
        "object_id": object_id,
        "extra": extra or {},
    }

    try:
        with conn_rw() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit (trace_id, event, payload, created_at)
                    VALUES (%s, %s, %s::jsonb, %s)
                    """,
                    (
                        trace_id,
                        event,
                        json.dumps(payload),
                        datetime.now(timezone.utc),
                    ),
                )
    except Exception:
        # offline pytest path (no DB running)
        return
