import os
import json
from uuid import UUID, uuid4

import psycopg

from .pg import PgObjectStore


_DECISIONS_MIGRATION_HINT = (
    "Decisions schema is migration-owned (#3488): run 'alembic upgrade head' "
    "against this database. See docs/DB_SCHEMA.md :: decisions."
)


def _dsn() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is required for postgres store access")
    return url.replace("+psycopg", "")


def _ensure_decisions(conn) -> None:
    """Assert the Alembic-owned decisions schema without mutating it at runtime."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.decisions')")
        table_row = cur.fetchone()
        if table_row is None or table_row[0] is None:
            raise RuntimeError(_DECISIONS_MIGRATION_HINT)
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'decisions'
            """
        )
        required_columns = {"id", "object_id", "agent", "kind", "key", "value", "created_at"}
        if missing_columns := required_columns - {row[0] for row in cur.fetchall()}:
            raise RuntimeError(
                f"{_DECISIONS_MIGRATION_HINT} Missing columns: {', '.join(sorted(missing_columns))}."
            )


class PgObjects:
    def upsert(self, *, id: str | None = None, kind: str, payload: dict, source_ref: str | None = None, path: str | None = None):
        # PgObjects is a temporary compatibility adapter for the vault-root
        # ingest path.  Delegate to the canonical writer so its assert-only
        # migration preflight and migration hint remain the single contract.
        str_id = id or str(uuid4())
        canonical_store = PgObjectStore()

        # ``decisions.object_id`` still has a live FK to the legacy ``objects``
        # table.  Keep the smallest possible parent row until #3510 migrates
        # that FK; ``store_objects`` remains exclusively canonical-owned.
        conn = psycopg.connect(_dsn())
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO objects (id, kind, payload) VALUES (%s, %s, '{}'::jsonb) "
                        "ON CONFLICT (id) DO NOTHING",
                        (str_id, kind),
                    )
        finally:
            conn.close()

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
