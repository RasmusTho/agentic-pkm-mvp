from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg
from psycopg.rows import dict_row

MemoryKey = tuple[str, str, str | None]
MemoryEntry = tuple[datetime, dict[str, Any]]

_IN_MEMORY_STORE: dict[MemoryKey, list[MemoryEntry]] = {}
MEMORY_ENABLED = os.getenv("MEMORY_ENABLED", "true").lower() not in ("0", "false", "no", "off")


def _dsn() -> str:
    """Return a psycopg-compatible DSN if explicitly configured.

    We intentionally avoid a local Postgres fallback: unit tests (and dev runs)
    must not implicitly couple to a DB that happens to be running.
    """

    v = (os.environ.get("DATABASE_URL") or "").strip()
    if not v:
        return ""
    return v.replace("postgresql+psycopg://", "postgresql://")


def _enabled() -> bool:
    return MEMORY_ENABLED


def _safe_connect(rowed: bool = False):
    dsn = _dsn()
    if not dsn:
        return None
    try:
        if rowed:
            return psycopg.connect(dsn, row_factory=dict_row)
        return psycopg.connect(dsn)
    except Exception:
        return None


def _memory_key(agent: str, kind: str, object_id: Optional[str]) -> MemoryKey:
    return (agent, kind, object_id)


def _memory_now() -> datetime:
    return datetime.now(timezone.utc)


def _remember_in_memory(agent: str, kind: str, object_id: Optional[str], trace_id: str, data: dict) -> None:
    payload = dict(data or {})
    payload["trace_id"] = trace_id

    key = _memory_key(agent, kind, object_id)
    bucket = _IN_MEMORY_STORE.setdefault(key, [])
    bucket.insert(0, (_memory_now(), payload))
    _IN_MEMORY_STORE[key] = bucket[:200]


def _recall_in_memory(agent: str, kind: str, object_id: Optional[str], limit: int) -> list[dict]:
    key = _memory_key(agent, kind, object_id)
    entries = _IN_MEMORY_STORE.get(key, [])
    return [dict(entry[1]) for entry in entries[:limit]]


def _decay_in_memory(agent: str, kind: str, before_ts: datetime) -> int:
    total_deleted = 0
    for key, entries in list(_IN_MEMORY_STORE.items()):
        key_agent, key_kind, _ = key
        if key_agent != agent or key_kind != kind:
            continue
        kept = [entry for entry in entries if entry[0] >= before_ts]
        total_deleted += len(entries) - len(kept)
        if kept:
            _IN_MEMORY_STORE[key] = kept
        else:
            _IN_MEMORY_STORE.pop(key, None)
    return total_deleted


def remember(agent: str, kind: str, object_id: Optional[str], trace_id: str, data: dict) -> None:
    if not _enabled():
        return

    conn = _safe_connect(rowed=False)
    if conn is None:
        _remember_in_memory(agent, kind, object_id, trace_id, data)
        return

    payload = dict(data or {})
    payload["trace_id"] = trace_id

    provenance: dict[str, Any] = {"agent": agent, "kind": kind}
    if object_id is not None:
        provenance["object_id"] = object_id

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_memories (id, run_id, layer, payload, provenance)
                    VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
                    """,
                    (
                        str(uuid.uuid4()),
                        None,
                        "short_term",
                        json.dumps(payload),
                        json.dumps(provenance),
                    ),
                )
    except psycopg.errors.UndefinedTable:
        _remember_in_memory(agent, kind, object_id, trace_id, data)
    finally:
        conn.close()


def recall(agent: str, kind: str, *, object_id: Optional[str] = None, limit: int = 20) -> list[dict]:
    if not _enabled():
        return []

    where_clauses = [
        "provenance ->> 'agent' = %s",
        "provenance ->> 'kind' = %s",
    ]
    args: list[Any] = [agent, kind]

    if object_id is not None:
        where_clauses.append("provenance ->> 'object_id' = %s")
        args.append(object_id)

    sql = f"""
        SELECT payload
        FROM agent_memories
        WHERE {' AND '.join(where_clauses)}
        ORDER BY created_at DESC
        LIMIT %s
    """
    args.append(int(limit))

    conn = _safe_connect(rowed=True)
    if conn is None:
        return _recall_in_memory(agent, kind, object_id, limit)

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                rows = cur.fetchall()
                return [r["payload"] for r in rows]
    except psycopg.errors.UndefinedTable:
        return _recall_in_memory(agent, kind, object_id, limit)
    finally:
        conn.close()


def decay(agent: str, kind: str, *, before_ts: Optional[datetime] = None) -> int:
    if not _enabled():
        return 0
    if before_ts is None:
        return 0

    conn = _safe_connect(rowed=False)
    if conn is None:
        return _decay_in_memory(agent, kind, before_ts)

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM agent_memories
                    WHERE
                        provenance ->> 'agent' = %s
                        AND provenance ->> 'kind' = %s
                        AND created_at < %s
                    """,
                    (agent, kind, before_ts),
                )
                return cur.rowcount or 0
    except psycopg.errors.UndefinedTable:
        return _decay_in_memory(agent, kind, before_ts)
    finally:
        conn.close()
