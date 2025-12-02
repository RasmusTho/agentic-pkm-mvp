import os
import json
from uuid import uuid4

import psycopg


def _dsn() -> str:
    url = os.environ.get("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")
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
                    cur.execute(
                        "INSERT INTO objects (id, uuid, kind, source_ref, payload, created_at, path) "
                        "VALUES (%s,%s,%s,%s,%s::jsonb, now(), %s) "
                        "ON CONFLICT (id) DO UPDATE SET "
                        "kind=EXCLUDED.kind, source_ref=EXCLUDED.source_ref, payload=EXCLUDED.payload, path=EXCLUDED.path "
                        "RETURNING id",
                        (str_id, str_id, kind, source_ref, json.dumps(payload), path),
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
