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
        cur.execute(
            """
            SELECT
                object_id_column.is_nullable,
                id_column.column_default,
                fk.table_schema,
                fk.table_name,
                fk.column_name,
                fk.delete_rule
            FROM information_schema.columns AS object_id_column
            JOIN information_schema.columns AS id_column
              ON id_column.table_schema = object_id_column.table_schema
             AND id_column.table_name = object_id_column.table_name
             AND id_column.column_name = 'id'
            LEFT JOIN (
                SELECT
                    ccu.table_schema,
                    ccu.table_name,
                    ccu.column_name,
                    rc.delete_rule
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                JOIN information_schema.referential_constraints AS rc
                  ON rc.constraint_name = tc.constraint_name
                 AND rc.constraint_schema = tc.table_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.constraint_schema = tc.table_schema
                WHERE tc.table_schema = 'public'
                  AND tc.table_name = 'decisions'
                  AND tc.constraint_type = 'FOREIGN KEY'
                  AND kcu.column_name = 'object_id'
                LIMIT 1
            ) AS fk ON TRUE
            WHERE object_id_column.table_schema = 'public'
            AND object_id_column.table_name = 'decisions'
            AND object_id_column.column_name = 'object_id'
            """
        )
        shape_row = cur.fetchone()
        if (
            shape_row is None
            or shape_row[0] != "YES"
            or "gen_random_uuid" not in (shape_row[1] or "")
            or tuple(shape_row[2:])
            != ("public", "store_objects", "object_id", "SET NULL")
        ):
            raise RuntimeError(f"{_DECISIONS_MIGRATION_HINT} Schema shape is stale.")


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
