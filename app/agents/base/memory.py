from __future__ import annotations
import os, json, time, uuid
from typing import Any
import psycopg
from psycopg.rows import dict_row

def _dsn() -> str:
    return (os.environ.get("DATABASE_URL") or "postgresql+psycopg://app:app@127.0.0.1:15432/app").replace("postgresql+psycopg://","postgresql://")

def remember(*, agent: str, key: str, value: dict[str, Any], scope_object_id: str | None = None, ttl_seconds: int | None = None) -> None:
    expires_at = int(time.time()) + int(ttl_seconds) if ttl_seconds else None
    oid = uuid.UUID(scope_object_id) if scope_object_id else None
    try:
        with psycopg.connect(_dsn(), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM agent_memories WHERE agent=%s AND key=%s AND scope_object_id IS NOT DISTINCT FROM %s", (agent, key, oid))
                cur.execute("INSERT INTO agent_memories(id, agent, key, value, scope_object_id, expires_at) VALUES (%s,%s,%s,%s::jsonb,%s,%s)", (str(uuid.uuid4()), agent, key, json.dumps(value), oid, expires_at))
    except Exception:
        with psycopg.connect(_dsn(), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO decisions(id, object_id, key, value, created_at) VALUES (%s,%s,%s,%s::jsonb, now())", (str(uuid.uuid4()), str(oid) if oid else None, f"memory:{agent}:{key}", json.dumps({"value": value, "expires_at": expires_at})))

def recall(*, agent: str, key: str, scope_object_id: str | None = None) -> dict[str, Any] | None:
    oid = uuid.UUID(scope_object_id) if scope_object_id else None
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT value, expires_at FROM agent_memories WHERE agent=%s AND key=%s AND scope_object_id IS NOT DISTINCT FROM %s ORDER BY id DESC LIMIT 1", (agent, key, oid))
            row = cur.fetchone()
            if not row:
                return None
            if row["expires_at"] and int(time.time()) > int(row["expires_at"]):
                return None
            return row["value"]
