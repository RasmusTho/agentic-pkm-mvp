import json
import os
from uuid import UUID, uuid4

import psycopg

from app.db.decisions_schema import assert_decisions_schema

from .pg import PgObjectStore


def _dsn() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is required for postgres store access")
    return url.replace("+psycopg", "")


class PgObjects:
    def upsert(self, *, id: str | None = None, kind: str, payload: dict, source_ref: str | None = None, path: str | None = None):
        # PgObjects is a temporary compatibility adapter for the vault-root
        # ingest path.  Delegate to the canonical writer so its assert-only
        # migration preflight and migration hint remain the single contract.
        str_id = id or str(uuid4())
        canonical_store = PgObjectStore()

        canonical_store.put(
            object_id=UUID(str_id),
            kind=kind,
            source_ref=source_ref or path,
            payload=payload,
        )
        return {"id": str_id}


class PgDecisions:
    def put(self, *, object_id: str, agent: str, kind: str, key: str, value: dict):
        conn = psycopg.connect(_dsn())
        try:
            with conn:
                assert_decisions_schema(conn)
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
