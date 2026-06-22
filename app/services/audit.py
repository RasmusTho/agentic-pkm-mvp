from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import json

from app.db.db import conn_rw
from app.stores import resolve_store_backend

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
    # Skip the DB write entirely unless the store layer resolves to the durable
    # Postgres backend. In memory/non-pg mode the resolved DSN may still be
    # non-empty but point at the default unreachable host (db:5432), and
    # ``psycopg.connect()`` can stall in ``socket.getaddrinfo()``. Use the same
    # backend resolver as the store layer so auto-detected pg deployments still
    # write audit rows while genuine memory mode avoids DB/DNS work.
    if resolve_store_backend() != "pg":
        return

    payload = {
        "event": event,
        "agent": agent,
        "object_id": object_id,
        "extra": extra or {},
    }

    try:
        # Bound the connect on this best-effort path so an unreachable DB host
        # (e.g. memory/non-pg mode resolving a non-empty DSN to db:5432) cannot
        # stall in DNS/socket resolution before the offline except below catches.
        with conn_rw(connect_timeout=1) as conn:
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
