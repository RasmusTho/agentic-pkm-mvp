from __future__ import annotations
import os
import json
import uuid
from datetime import datetime
from typing import Any, Optional

import psycopg
from psycopg.rows import dict_row

from app.db import conn_rw


def _dsn() -> str:
    # Fallback till din lokala dev-URL om DATABASE_URL inte är satt
    v = os.environ.get("DATABASE_URL") or "postgresql+psycopg://app:app@127.0.0.1:15432/app"
    # psycopg2-style
    return v.replace("postgresql+psycopg://", "postgresql://")


def _enabled() -> bool:
    # MEMORY_ENABLED=false => helt av
    v = os.environ.get("MEMORY_ENABLED", "true").lower()
    return v not in ("0", "false", "no", "off")


def _safe_connect(rowed: bool = False):
    """
    Försök skapa en psycopg-connection direkt mot _dsn().
    Om det failar (t.ex. ingen DB i pytest) -> returnera None istället för att kasta.
    """
    try:
        if rowed:
            return psycopg.connect(_dsn(), row_factory=dict_row)
        else:
            return psycopg.connect(_dsn())
    except Exception:
        return None


def remember(agent: str, kind: str, object_id: Optional[str], trace_id: str, data: dict) -> None:
    """
    Spara korttidsminne för agenten.
    I testmiljön ska detta aldrig få krascha om DB saknas.
    """
    if not _enabled():
        return

    payload = dict(data or {})
    payload["trace_id"] = trace_id

    provenance: dict[str, Any] = {"agent": agent, "kind": kind}
    if object_id is not None:
        provenance["object_id"] = object_id

    conn = _safe_connect(rowed=False)
    if conn is None:
        # No DB -> skip silently
        return

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
    finally:
        conn.close()


def recall(agent: str, kind: str, *, object_id: Optional[str] = None, limit: int = 20) -> list[dict]:
    """
    Hämta senaste minnen för agenten.
    I testmiljön ska detta bara returnera [] om DB inte är uppe.
    """
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
        # No DB in pytest -> just act like empty memory
        return []

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                rows = cur.fetchall()
                return [r["payload"] for r in rows]
    finally:
        conn.close()


def decay(agent: str, kind: str, *, before_ts: Optional[datetime] = None) -> int:
    """
    Glöm gamla minnen före en viss timestamp.
    Testmiljön: ska inte kasta om DB saknas.
    """
    if not _enabled():
        return 0
    if before_ts is None:
        return 0

    conn = _safe_connect(rowed=False)
    if conn is None:
        return 0

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
    finally:
        conn.close()