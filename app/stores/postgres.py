import os
import json
from uuid import uuid4

import psycopg


def _dsn() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is required for postgres store access")
    return url.replace("+psycopg", "")


def _ensure_decisions(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("create extension if not exists pgcrypto")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS decisions (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                object_id uuid NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
                agent text,
                kind text,
                key text NOT NULL,
                value jsonb NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute("ALTER TABLE decisions ADD COLUMN IF NOT EXISTS agent text")
        cur.execute("ALTER TABLE decisions ADD COLUMN IF NOT EXISTS kind text")
        cur.execute("ALTER TABLE decisions ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now()")


class PgObjects:
    def upsert(self, *, id: str | None = None, kind: str, payload: dict, source_ref: str | None = None, path: str | None = None):
        conn = psycopg.connect(_dsn())
        try:
            with conn:
                with conn.cursor() as cur:
                    str_id = id or str(uuid4())
                    effective_source_ref = source_ref or path
                    cur.execute(
                        "INSERT INTO objects (id, uuid, kind, payload, created_at, updated_at) "
                        "VALUES (%s,%s,%s,%s::jsonb, now(), now()) "
                        "ON CONFLICT (id) DO UPDATE SET "
                        "uuid=EXCLUDED.uuid, kind=EXCLUDED.kind, payload=EXCLUDED.payload, updated_at=now()",
                        (str_id, str_id, kind, json.dumps(payload)),
                    )
                    cur.execute(
                        "INSERT INTO store_objects (object_id, kind, source_ref, payload, created_at, updated_at) "
                        "VALUES (%s,%s,%s,%s::jsonb, now(), now()) "
                        "ON CONFLICT (object_id) DO UPDATE SET "
                        "kind=EXCLUDED.kind, source_ref=EXCLUDED.source_ref, payload=EXCLUDED.payload, updated_at=now() "
                        "RETURNING object_id",
                        (str_id, kind, effective_source_ref, json.dumps(payload)),
                    )
                    row = cur.fetchone()
            return {"id": (row[0] if isinstance(row, (list, tuple)) else row.get("id"))}
        finally:
            conn.close()


class PgDecisions:
    def put(self, *, object_id: str, agent: str, kind: str, key: str, value: dict):
        conn = psycopg.connect(_dsn())
        try:
            with conn:
                _ensure_decisions(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO decisions (id, object_id, agent, kind, key, value, created_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s::jsonb, now()) "
                        "RETURNING id",
                        (str(uuid4()), object_id, agent, kind, key, json.dumps(value)),
                    )
                    row = cur.fetchone()
            return {"id": (row[0] if isinstance(row, (list, tuple)) else row.get("id"))}
        finally:
            conn.close()
