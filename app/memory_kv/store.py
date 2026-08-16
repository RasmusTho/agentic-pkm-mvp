from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg
from psycopg.rows import dict_row

from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from app.instance.scalar_binding_runtime import resolve_scalar_binding_runtime

MemoryKey = tuple[str, str, str | None, str]
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


class AgentMemorySchemaMissingError(RuntimeError):
    """The configured Postgres predates the MVR-05A residual binding key."""


def _resolve_binding_id(vault_binding_id: str | None) -> str:
    requested = (vault_binding_id or "").strip()
    runtime = resolve_scalar_binding_runtime(
        requested_binding_id=requested or None
    )
    if runtime is not None:
        return runtime.vault_binding_id
    if vault_binding_id is None:
        return COMPATIBILITY_BINDING_ID
    if not requested:
        raise ValueError("vault_binding_id must be a non-empty string")
    return requested


def _memory_key(
    agent: str, kind: str, object_id: Optional[str], vault_binding_id: str
) -> MemoryKey:
    return (agent, kind, object_id, vault_binding_id)


def _memory_now() -> datetime:
    return datetime.now(timezone.utc)


def _remember_in_memory(
    agent: str,
    kind: str,
    object_id: Optional[str],
    trace_id: str,
    data: dict,
    vault_binding_id: str,
) -> None:
    payload = dict(data or {})
    payload["trace_id"] = trace_id

    key = _memory_key(agent, kind, object_id, vault_binding_id)
    bucket = _IN_MEMORY_STORE.setdefault(key, [])
    bucket.insert(0, (_memory_now(), payload))
    _IN_MEMORY_STORE[key] = bucket[:200]


def _recall_in_memory(
    agent: str,
    kind: str,
    object_id: Optional[str],
    limit: int,
    vault_binding_id: str,
) -> list[dict]:
    key = _memory_key(agent, kind, object_id, vault_binding_id)
    entries = _IN_MEMORY_STORE.get(key, [])
    return [dict(entry[1]) for entry in entries[:limit]]


def _decay_in_memory(
    agent: str, kind: str, before_ts: datetime, vault_binding_id: str
) -> int:
    total_deleted = 0
    for key, entries in list(_IN_MEMORY_STORE.items()):
        key_agent, key_kind, _, key_binding = key
        if key_agent != agent or key_kind != kind or key_binding != vault_binding_id:
            continue
        kept = [entry for entry in entries if entry[0] >= before_ts]
        total_deleted += len(entries) - len(kept)
        if kept:
            _IN_MEMORY_STORE[key] = kept
        else:
            _IN_MEMORY_STORE.pop(key, None)
    return total_deleted


def _assert_agent_memory_schema(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT to_regclass('public.agent_memories') IS NOT NULL AS table_exists,
                   EXISTS (
                     SELECT 1 FROM pg_attribute
                      WHERE attrelid=to_regclass('public.agent_memories')
                        AND attname='vault_binding_id' AND attnotnull
                        AND attnum>0 AND NOT attisdropped
                   ) AS has_binding,
                   (
                     SELECT array_agg(a.attname ORDER BY k.ordinality)
                       FROM pg_constraint c
                       JOIN unnest(c.conkey) WITH ORDINALITY k(attnum, ordinality) ON true
                       JOIN pg_attribute a
                         ON a.attrelid=c.conrelid AND a.attnum=k.attnum
                      WHERE c.conrelid=to_regclass('public.agent_memories')
                        AND c.contype='p'
                   ) AS primary_key
            """
        )
        row = cur.fetchone()
    table_exists = row.get("table_exists") if isinstance(row, dict) else (row[0] if row else False)
    has_binding = row.get("has_binding") if isinstance(row, dict) else (row[1] if row else False)
    primary_key = row.get("primary_key") if isinstance(row, dict) else (row[2] if row else None)
    if not table_exists or not has_binding or list(primary_key or []) != [
        "vault_binding_id",
        "id",
    ]:
        raise AgentMemorySchemaMissingError(
            "agent_memories is missing its binding key; run 'alembic upgrade head' "
            "before starting an agent-memory producer"
        )


def remember(
    agent: str,
    kind: str,
    object_id: Optional[str],
    trace_id: str,
    data: dict,
    *,
    vault_binding_id: str | None = None,
) -> None:
    if not _enabled():
        return

    resolved_binding_id = _resolve_binding_id(vault_binding_id)
    conn = _safe_connect(rowed=False)
    if conn is None:
        _remember_in_memory(
            agent, kind, object_id, trace_id, data, resolved_binding_id
        )
        return

    payload = dict(data or {})
    payload["trace_id"] = trace_id

    provenance: dict[str, Any] = {"agent": agent, "kind": kind}
    if object_id is not None:
        provenance["object_id"] = object_id

    try:
        _assert_agent_memory_schema(conn)
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_memories
                        (vault_binding_id, id, run_id, layer, payload, provenance)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb)
                    """,
                    (
                        resolved_binding_id,
                        str(uuid.uuid4()),
                        None,
                        "short_term",
                        json.dumps(payload),
                        json.dumps(provenance),
                    ),
                )
    finally:
        conn.close()


def recall(
    agent: str,
    kind: str,
    *,
    object_id: Optional[str] = None,
    limit: int = 20,
    vault_binding_id: str | None = None,
) -> list[dict]:
    if not _enabled():
        return []

    where_clauses = [
        "vault_binding_id = %s",
        "provenance ->> 'agent' = %s",
        "provenance ->> 'kind' = %s",
    ]
    resolved_binding_id = _resolve_binding_id(vault_binding_id)
    args: list[Any] = [resolved_binding_id, agent, kind]

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
        return _recall_in_memory(
            agent, kind, object_id, limit, resolved_binding_id
        )

    try:
        _assert_agent_memory_schema(conn)
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                rows = cur.fetchall()
                return [r["payload"] for r in rows]
    finally:
        conn.close()


def decay(
    agent: str,
    kind: str,
    *,
    before_ts: Optional[datetime] = None,
    vault_binding_id: str | None = None,
) -> int:
    if not _enabled():
        return 0
    if before_ts is None:
        return 0

    resolved_binding_id = _resolve_binding_id(vault_binding_id)
    conn = _safe_connect(rowed=False)
    if conn is None:
        return _decay_in_memory(agent, kind, before_ts, resolved_binding_id)

    try:
        _assert_agent_memory_schema(conn)
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM agent_memories
                    WHERE
                        vault_binding_id = %s
                        AND provenance ->> 'agent' = %s
                        AND provenance ->> 'kind' = %s
                        AND created_at < %s
                    """,
                    (resolved_binding_id, agent, kind, before_ts),
                )
                return cur.rowcount or 0
    finally:
        conn.close()
