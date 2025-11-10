from __future__ import annotations

import json
import os
import threading
import uuid
from collections import deque

import psycopg

_AUDIT_RING = deque(maxlen=1024)
_AUDIT_LOCK = threading.Lock()


def _dsn() -> str:
    return (os.environ.get("DATABASE_URL") or "postgresql+psycopg://app:app@127.0.0.1:15432/app").replace(
        "postgresql+psycopg://", "postgresql://"
    )


def audit_log(
    *,
    object_id: str | None,
    agent: str,
    action: str,
    trace_id: str | None,
    details: dict | None = None,
) -> None:
    store_backend = os.getenv("STORE_BACKEND", "memory").lower()
    if store_backend != "pg":
        payload = {
            "object_id": object_id,
            "agent": agent,
            "action": action,
            "trace_id": trace_id,
            "details": details or {},
        }
        with _AUDIT_LOCK:
            _AUDIT_RING.append(payload)
        return

    with psycopg.connect(_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit(id, object_id, agent, action, ts, trace_id, details)
                VALUES (%s, %s, %s, %s, now(), %s, %s::jsonb)
                """,
                (str(uuid.uuid4()), object_id, agent, action, trace_id, json.dumps(details or {})),
            )


def _audit_ring_snapshot() -> list[dict]:
    with _AUDIT_LOCK:
        return list(_AUDIT_RING)


__all__ = ["audit_log", "_audit_ring_snapshot"]
