import os
import json
from uuid import UUID, uuid4

import psycopg

from .pg import PgObjectStore


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
                object_id uuid REFERENCES objects(id) ON DELETE SET NULL,
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
        # Environments whose `decisions` table predates this change (#2788,
        # D-5/D-7) still carry the old `ON DELETE CASCADE` FK and a NOT NULL
        # object_id; the forward-only Alembic migration
        # (1a739d9494af_decisions_fk_set_null.py) is the primary path for
        # migration-managed databases, but this runtime bootstrap path must
        # not fight it or leave freshly-created tables on the old cascade
        # posture, so it re-asserts the same target shape idempotently.
        cur.execute("ALTER TABLE decisions ALTER COLUMN object_id DROP NOT NULL")
        cur.execute(
            """
            DO $$
            DECLARE
                fk_name text;
                delete_rule text;
            BEGIN
                SELECT tc.constraint_name, rc.delete_rule INTO fk_name, delete_rule
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                JOIN information_schema.referential_constraints rc
                  ON rc.constraint_name = tc.constraint_name
                 AND rc.constraint_schema = tc.table_schema
                WHERE tc.table_schema = 'public'
                  AND tc.table_name = 'decisions'
                  AND tc.constraint_type = 'FOREIGN KEY'
                  AND kcu.column_name = 'object_id'
                LIMIT 1;

                IF fk_name IS NOT NULL AND delete_rule IS DISTINCT FROM 'SET NULL' THEN
                    EXECUTE format('ALTER TABLE public.decisions DROP CONSTRAINT %I', fk_name);
                    EXECUTE
                        'ALTER TABLE public.decisions '
                        || 'ADD CONSTRAINT decisions_object_id_fkey '
                        || 'FOREIGN KEY (object_id) REFERENCES public.objects(id) ON DELETE SET NULL';
                END IF;
            END$$;
            """
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
