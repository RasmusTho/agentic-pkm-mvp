from __future__ import annotations
import os, json
import uuid
import psycopg

def _dsn() -> str:
    return (os.environ.get("DATABASE_URL") or "postgresql+psycopg://app:app@127.0.0.1:15432/app").replace("postgresql+psycopg://","postgresql://")

def audit_log(*, object_id: str | None, agent: str, action: str, trace_id: str | None, details: dict | None = None) -> None:
    with psycopg.connect(_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit(id, object_id, agent, action, ts, trace_id, details)
                VALUES (%s, %s, %s, %s, now(), %s, %s::jsonb)
                """,
                (str(uuid.uuid4()), object_id, agent, action, trace_id, json.dumps(details or {})),
            )
