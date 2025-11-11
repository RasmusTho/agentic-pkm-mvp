from __future__ import annotations

import json
import os
import threading
import uuid

import psycopg

_AUDIT_CACHE: list[str] = []
_AUDIT_CACHE_LIMIT = 1024
_AUDIT_LOCK = threading.Lock()


def _dsn() -> str:
    return (os.environ.get("DATABASE_URL") or "postgresql+psycopg://app:app@127.0.0.1:15432/app").replace(
        "postgresql+psycopg://", "postgresql://"
    )


def _serialize_payload(payload: dict) -> str:
    return json.dumps(payload, separators=(",", ":"))


def _append_cache(json_line: str) -> None:
    with _AUDIT_LOCK:
        _AUDIT_CACHE.append(json_line)
        overflow = len(_AUDIT_CACHE) - _AUDIT_CACHE_LIMIT
        if overflow > 0:
            del _AUDIT_CACHE[:overflow]


def audit_log(
    *,
    object_id: str | None,
    agent: str,
    action: str,
    trace_id: str | None,
    details: dict | None = None,
) -> None:
    entry_id = str(uuid.uuid4())
    payload = {
        "id": entry_id,
        "object_id": object_id,
        "agent": agent,
        "action": action,
        "trace_id": trace_id,
        "details": details or {},
    }
    json_line = _serialize_payload(payload)

    store_backend = os.getenv("STORE_BACKEND", "memory").lower()
    if store_backend != "pg":
        _append_cache(json_line)
        return

    try:
        with psycopg.connect(_dsn(), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit(id, object_id, agent, action, ts, trace_id, details)
                    VALUES (%s, %s, %s, %s, now(), %s, %s::jsonb)
                    """,
                    (entry_id, object_id, agent, action, trace_id, json.dumps(details or {})),
                )
    except psycopg.Error:
        _append_cache(json_line)


def _audit_ring_snapshot() -> list[dict]:
    with _AUDIT_LOCK:
        return [json.loads(line) for line in _AUDIT_CACHE]


__all__ = ["audit_log", "_audit_ring_snapshot"]
