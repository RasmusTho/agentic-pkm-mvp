from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import json
import os

from app.db.db import conn_rw
from app.stores import resolved_store_backend_hint


def _audit_pg_backend_selected() -> bool:
    explicit_backend = (os.getenv("STORE_BACKEND") or "").strip().lower()
    if explicit_backend:
        return explicit_backend == "pg"
    return resolved_store_backend_hint() == "pg"

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
    # Skip unless pg is explicit or already known from the store layer. Calling
    # the auto-detect resolver from this best-effort audit path can perform a
    # DNS/pg probe before the offline no-op below gets a chance to catch it.
    if not _audit_pg_backend_selected():
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
