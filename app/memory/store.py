from __future__ import annotations
import os
import json
import uuid
from datetime import datetime
from typing import Any, Optional
import psycopg
from psycopg.rows import dict_row

def _dsn() -> str:
    v = os.environ.get("DATABASE_URL") or "postgresql+psycopg://app:app@127.0.0.1:15432/app"
    return v.replace("postgresql+psycopg://", "postgresql://")

def _enabled() -> bool:
    v = os.environ.get("MEMORY_ENABLED", "true").lower()
    return v not in ("0", "false", "no", "off")

def remember(agent: str, kind: str, object_id: Optional[str], trace_id: str, data: dict) -> None:
    if not _enabled():
        return
    payload = dict(data or {})
    payload["trace_id"] = trace_id
    provenance: dict[str, Any] = {"agent": agent, "kind": kind}
    if object_id is not None:
        provenance["object_id"] = object_id
    with psycopg.connect(_dsn(), autocommit=True) as conn:
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

def recall(agent: str, kind: str, *, object_id: Optional[str] = None, limit: int = 20) -> list[dict]:
    if not _enabled():
        return []
    where = ["provenance ->> 'agent' = %s", "provenance ->> 'kind' = %s"]
    args: list[Any] = [agent, kind]
    if object_id is not None:
        where.append("provenance ->> 'object_id' = %s")
        args.append(object_id)
    sql = f"""
        SELECT payload
        FROM agent_memories
        WHERE {' AND '.join(where)}
        ORDER BY created_at DESC
        LIMIT %s
    """
    args.append(int(limit))
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            rows = cur.fetchall()
            return [r["payload"] for r in rows]

def decay(agent: str, kind: str, *, before_ts: Optional[datetime] = None) -> int:
    if not _enabled():
        return 0
    if before_ts is None:
        return 0
    with psycopg.connect(_dsn(), autocommit=True) as conn:
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
