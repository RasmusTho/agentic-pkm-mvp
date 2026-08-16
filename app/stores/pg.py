from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, asdict
from typing import Iterable, List, Tuple
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.components.embeddings import EmbeddingIdentity, get_embedding_identity
from app.db.db import COMPATIBILITY_BINDING_ID
from app.db.dsn import resolve_dsn
from app.db.errors import StoreSchemaMissingError
from app.embedding_config import coerce_floats, l2_normalize
from app.index.artifact_metadata import canonicalize_indexable_text
from app.objects.identity import (
    resolve_vault_uuid_with_connection as _resolve_vault_uuid_with_connection,
    retained_vault_uuid_with_connection as _retained_vault_uuid_with_connection,
    vault_uuid_to_canonical_id_map_with_connection as _vault_uuid_to_canonical_id_map_with_connection,
)

from .base import ObjectStore, RelationIndex, RelationMembership, VectorIndex, _IDENTITY_HASH_LEN

_TABLES_READY = False

# The five migration-owned store tables (Alembic revision c2766a04d001).
_STORE_TABLES = (
    "store_objects",
    "store_vector_index",
    "store_relations",
    "store_relation_memberships",
    "vector_index_meta",
)

# store_vector_index identity columns the migration guarantees.
_IDENTITY_COLUMNS = ("dim", "model", "provider", "normalize")

_MIGRATION_HINT = (
    "Store schema is migration-owned (KERNEL-04, #2766): run 'alembic upgrade head' "
    "against this database. See docs/DB_SCHEMA.md :: store tables."
)


def _schema_autocreate_enabled() -> bool:
    """Explicit test-fixture opt-in for create-on-demand schema.

    Production/runtime Postgres never auto-creates store tables; only test
    environments set STORE_SCHEMA_AUTOCREATE=1 (see tests/conftest.py).
    """
    return (os.getenv("STORE_SCHEMA_AUTOCREATE") or "").strip().lower() in {"1", "true", "yes"}


def _dsn() -> str:
    url = resolve_dsn()
    if not url:
        url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL is required for postgres store access")
    if url.startswith("postgresql+psycopg://"):
        url = "postgresql://" + url.split("postgresql+psycopg://", 1)[1]
    return url


def _connect():
    return psycopg.connect(_dsn(), row_factory=dict_row)


# Grouped by table so a group can be skipped whole when the table already
# exists (MVR-05A2, #4576), mirroring `app/db/db.py::_run_migration_sql`.
# `CREATE TABLE IF NOT EXISTS` alone is not enough: it no-ops silently against
# an older shape while the `ALTER` statements after it still run, which makes
# this fixture a second owner able to reshape a migration-owned table — the
# defect MVR-05A1 (#4560) removed from `app/db/db.py`.  MVR-05A3 extends the
# explicit test-fixture producer through the minimum child-FK shape guarded by
# the store parent rekey.  `sets` is reproduced only as the unchanged fresh-
# lineage parent required by membership.set_id; the fixture also seeds the
# named `published` row consumed by the production membership writer.
_MIGRATION_OWNED_AUTOCREATE_SQL: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "store_objects",
        (
            """
            CREATE TABLE IF NOT EXISTS store_objects (
                object_id UUID NOT NULL,
                kind TEXT NOT NULL,
                source_ref TEXT,
                payload JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                vault_binding_id TEXT NOT NULL,
                PRIMARY KEY (vault_binding_id, object_id)
            )
            """,
        ),
    ),
    (
        "store_vector_index",
        (
            """
            CREATE TABLE IF NOT EXISTS store_vector_index (
                object_id UUID NOT NULL,
                kind TEXT NOT NULL,
                source_ref TEXT,
                payload JSONB NOT NULL,
                embedding DOUBLE PRECISION[] NOT NULL,
                dim INTEGER NOT NULL,
                model TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                vault_binding_id TEXT NOT NULL,
                PRIMARY KEY (vault_binding_id, object_id)
            )
            """,
            "ALTER TABLE store_vector_index ADD COLUMN IF NOT EXISTS dim INTEGER",
            # Phase A (EMBEDREL-06): per-vector full embedding identity columns.
            # `model` and `dim` already exist; add `provider` and `normalize` so
            # every row records the complete (provider, model, dim, normalize)
            # identity tuple. These now run only for a table this fixture just
            # created; an existing one is the revision chain's to reshape.
            "ALTER TABLE store_vector_index ADD COLUMN IF NOT EXISTS provider TEXT",
            "ALTER TABLE store_vector_index ADD COLUMN IF NOT EXISTS normalize BOOLEAN",
            "CREATE INDEX IF NOT EXISTS ix_store_vector_index_content_hash "
            "ON store_vector_index ((payload ->> 'content_hash'))",
        ),
    ),
    (
        "store_relations",
        (
            """
            CREATE TABLE IF NOT EXISTS store_relations (
                src_id UUID NOT NULL,
                dst_id UUID NOT NULL,
                rel TEXT NOT NULL,
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                vault_binding_id TEXT NOT NULL,
                PRIMARY KEY (vault_binding_id, src_id, dst_id, rel)
            )
            """,
        ),
    ),
    (
        "store_relation_memberships",
        (
            """
            CREATE TABLE IF NOT EXISTS store_relation_memberships (
                src_id UUID NOT NULL,
                rel TEXT NOT NULL,
                value TEXT NOT NULL,
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                vault_binding_id TEXT NOT NULL,
                PRIMARY KEY (vault_binding_id, src_id, rel, value)
            )
            """,
        ),
    ),
    (
        "vector_index_meta",
        (
            """
            CREATE TABLE IF NOT EXISTS vector_index_meta (
                id INTEGER NOT NULL CHECK (id = 1),
                identity_json TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                vault_binding_id TEXT NOT NULL,
                PRIMARY KEY (vault_binding_id, id)
            )
            """,
        ),
    ),
    (
        "chunks",
        (
            """
            CREATE TABLE IF NOT EXISTS chunks (
                id UUID PRIMARY KEY,
                object_id UUID NOT NULL,
                idx INTEGER NOT NULL,
                offset_start INTEGER NOT NULL,
                offset_end INTEGER NOT NULL,
                text TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                vault_binding_id TEXT NOT NULL,
                CONSTRAINT chunks_object_id_fkey
                    FOREIGN KEY (vault_binding_id, object_id)
                    REFERENCES store_objects (vault_binding_id, object_id)
                    ON DELETE CASCADE
            )
            """,
            "CREATE INDEX IF NOT EXISTS chunks_object_binding_idx "
            "ON chunks (vault_binding_id, object_id)",
            "ALTER TABLE chunks ADD CONSTRAINT chunks_binding_id_key "
            "UNIQUE (vault_binding_id, id)",
        ),
    ),
    (
        "embeddings",
        (
            """
            CREATE TABLE IF NOT EXISTS embeddings (
                id UUID PRIMARY KEY,
                object_id UUID NOT NULL,
                chunk_id UUID,
                provider TEXT DEFAULT 'mock',
                dim INTEGER NOT NULL DEFAULT 1536,
                embedding VECTOR,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                vault_binding_id TEXT NOT NULL,
                CONSTRAINT embeddings_object_id_fkey
                    FOREIGN KEY (vault_binding_id, object_id)
                    REFERENCES store_objects (vault_binding_id, object_id)
                    ON DELETE CASCADE,
                CONSTRAINT embeddings_chunk_id_fkey
                    FOREIGN KEY (vault_binding_id, chunk_id)
                    REFERENCES chunks (vault_binding_id, id)
                    ON DELETE CASCADE
            )
            """,
            "CREATE INDEX IF NOT EXISTS embeddings_object_binding_idx "
            "ON embeddings (vault_binding_id, object_id)",
            "CREATE INDEX IF NOT EXISTS embeddings_chunk_binding_idx "
            "ON embeddings (vault_binding_id, chunk_id)",
        ),
    ),
    (
        "relations",
        (
            """
            CREATE TABLE IF NOT EXISTS relations (
                id UUID PRIMARY KEY,
                src_id UUID NOT NULL,
                dst_id UUID NOT NULL,
                type TEXT NOT NULL,
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                vault_binding_id TEXT NOT NULL,
                CONSTRAINT relations_src_id_fkey
                    FOREIGN KEY (vault_binding_id, src_id)
                    REFERENCES store_objects (vault_binding_id, object_id)
                    ON DELETE CASCADE,
                CONSTRAINT relations_dst_id_fkey
                    FOREIGN KEY (vault_binding_id, dst_id)
                    REFERENCES store_objects (vault_binding_id, object_id)
                    ON DELETE CASCADE
            )
            """,
            "CREATE INDEX IF NOT EXISTS relations_src_binding_idx "
            "ON relations (vault_binding_id, src_id)",
            "CREATE INDEX IF NOT EXISTS relations_dst_binding_idx "
            "ON relations (vault_binding_id, dst_id)",
        ),
    ),
    (
        "sets",
        (
            """
            CREATE TABLE IF NOT EXISTS sets (
                id UUID PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                meta JSONB NOT NULL DEFAULT '{}'::jsonb
            )
            """,
            """
            INSERT INTO sets (id, name, meta)
            VALUES (
                'afa60fd2-731a-5c30-ae25-07f56c115393'::uuid,
                'published',
                '{"system":"membership-projection"}'::jsonb
            )
            ON CONFLICT (name) DO NOTHING
            """,
        ),
    ),
    (
        "membership",
        (
            """
            CREATE TABLE IF NOT EXISTS membership (
                id UUID NOT NULL,
                set_id UUID NOT NULL
                    CONSTRAINT membership_set_id_fkey
                    REFERENCES sets(id) ON DELETE CASCADE,
                object_id UUID NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                vault_binding_id TEXT NOT NULL,
                CONSTRAINT membership_object_id_fkey
                    FOREIGN KEY (vault_binding_id, object_id)
                    REFERENCES store_objects (vault_binding_id, object_id)
                    ON DELETE CASCADE,
                PRIMARY KEY (vault_binding_id, id)
            )
            """,
            "CREATE INDEX IF NOT EXISTS membership_object_binding_idx "
            "ON membership (vault_binding_id, object_id)",
        ),
    ),
    (
        "decisions",
        (
            """
            CREATE TABLE IF NOT EXISTS decisions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                object_id UUID,
                agent TEXT,
                kind TEXT,
                key TEXT NOT NULL,
                value JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                vault_binding_id TEXT NOT NULL,
                CONSTRAINT decisions_object_binding_check
                    CHECK (object_id IS NULL OR vault_binding_id IS NOT NULL),
                CONSTRAINT decisions_object_id_fkey
                    FOREIGN KEY (vault_binding_id, object_id)
                    REFERENCES store_objects (vault_binding_id, object_id)
                    ON DELETE SET NULL (object_id)
            )
            """,
            "CREATE INDEX IF NOT EXISTS decisions_object_binding_idx "
            "ON decisions (vault_binding_id, object_id)",
        ),
    ),
    (
        "audit",
        (
            """
            CREATE TABLE IF NOT EXISTS audit (
                id UUID PRIMARY KEY,
                object_id UUID,
                agent TEXT NOT NULL,
                action TEXT NOT NULL,
                ts TIMESTAMPTZ NOT NULL DEFAULT now(),
                trace_id TEXT,
                details JSONB NOT NULL DEFAULT '{}'::jsonb,
                vault_binding_id TEXT,
                CONSTRAINT audit_object_binding_check
                    CHECK (object_id IS NULL OR vault_binding_id IS NOT NULL),
                CONSTRAINT audit_object_id_fkey
                    FOREIGN KEY (vault_binding_id, object_id)
                    REFERENCES store_objects (vault_binding_id, object_id)
                    ON DELETE SET NULL (object_id)
            )
            """,
            "CREATE INDEX IF NOT EXISTS audit_object_binding_idx "
            "ON audit (vault_binding_id, object_id)",
        ),
    ),
)

_MIGRATION_OWNED_AUTOCREATE_VIEWS: tuple[tuple[str, str], ...] = (
    (
        "view_chunks_missing_embeddings",
        """
        CREATE VIEW view_chunks_missing_embeddings AS
        SELECT c.object_id::text AS object_id,
               count(DISTINCT c.id) AS chunk_count,
               count(DISTINCT e.chunk_id) AS embedded_chunks,
               c.vault_binding_id
          FROM chunks c
          LEFT JOIN embeddings e
            ON e.vault_binding_id=c.vault_binding_id AND e.chunk_id=c.id
         GROUP BY c.vault_binding_id, c.object_id
        HAVING count(DISTINCT c.id) > count(DISTINCT e.chunk_id)
        """,
    ),
    (
        "view_objects_ready_for_projection",
        """
        CREATE VIEW view_objects_ready_for_projection AS
        SELECT d.object_id::text AS object_id,
               coalesce(d.value->>'type','') AS type,
               coalesce(d.value->>'trust','') AS trust,
               d.created_at,
               d.vault_binding_id
          FROM decisions d
         WHERE d.key='classification' AND coalesce(d.value->>'type','') <> ''
           AND NOT EXISTS (SELECT 1 FROM membership m
             WHERE m.vault_binding_id=d.vault_binding_id AND m.object_id=d.object_id)
        """,
    ),
)


def _ensure_tables() -> None:
    """Assert (or, in tests, create) the migration-owned store schema.

    Outside tests this is assert-only (KERNEL-04, #2766): a missing store
    table or identity column raises ``StoreSchemaMissingError`` with a
    "run migrations" hint instead of creating schema imperatively. The
    idempotent per-row **data** repairs (`_run_data_repairs`: dim backfill +
    identity backfill) always run — data repair, not DDL. Test fixtures set
    STORE_SCHEMA_AUTOCREATE=1 to keep create-on-demand for scratch databases.

    A table that already exists is left completely alone (MVR-05A2, #4576).
    Before that, the three ``ALTER TABLE store_vector_index ADD COLUMN IF NOT
    EXISTS`` statements ran unconditionally in this branch, so a scratch
    database stamped at a pre-EMBEDREL-06 revision had its migration-owned
    table reshaped from the runtime. Idempotence comes from the `to_regclass`
    existence probe, not from `IF NOT EXISTS`.
    """
    global _TABLES_READY
    if _TABLES_READY:
        return
    if not _schema_autocreate_enabled():
        _assert_tables()
        _TABLES_READY = True
        return
    with _connect() as conn:
        created_any_table = False
        for table, statements in _MIGRATION_OWNED_AUTOCREATE_SQL:
            with conn.cursor() as cur:
                # Bound to the *current* schema rather than resolved through the
                # whole `search_path`. Three pg tests run this fixture under
                # `options=-csearch_path=pgtest_<hex>,public`
                # (`tests/integration/test_vault_sync_atomicity.py`,
                # `tests/services/test_outbox_idempotency_pg.py`,
                # `tests/indexer/test_outbox_roundtrip_pg.py`) and rely on the
                # unqualified `CREATE TABLE` landing a private copy in their own
                # schema. A bare `to_regclass('store_objects')` would find the
                # migrated `public` table, skip the group, and silently hand
                # those tests the shared tables instead.
                #
                # `quote_ident`, not `format('%I.%I', ...)`: psycopg's
                # client-side placeholder parser rejects any `%` sequence that
                # is not one of its own, so a `%I` in the statement raises
                # `only '%s', '%b', '%t' are allowed as placeholders` before the
                # server ever sees it.
                cur.execute(
                    "SELECT to_regclass("
                    "quote_ident(current_schema()) || '.' || quote_ident(%s)"
                    ") IS NOT NULL AS present",
                    (table,),
                )
                row = cur.fetchone()
            present = (row.get("present") if isinstance(row, dict) else row[0]) if row else False
            if present:
                continue
            created_any_table = True
            for statement in statements:
                with conn.cursor() as cur:
                    cur.execute(statement)
        if created_any_table:
            for view, view_sql in _MIGRATION_OWNED_AUTOCREATE_VIEWS:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT to_regclass("
                        "quote_ident(current_schema()) || '.' || quote_ident(%s)"
                        ") IS NOT NULL AS present",
                        (view,),
                    )
                    row = cur.fetchone()
                present = (
                    (row.get("present") if isinstance(row, dict) else row[0]) if row else False
                )
                if not present:
                    with conn.cursor() as cur:
                        cur.execute(view_sql)
        with conn.cursor() as cur:
            _run_data_repairs(cur)
    _TABLES_READY = True


def _assert_tables() -> None:
    """Fail loud when the migration-owned store schema is absent.

    Raises ``StoreSchemaMissingError`` — classified transient by the outbox
    worker dispatch path (`_is_transient_dispatch_error`): schema-missing is a
    boot-ordering condition on a fresh stack (alembic runs in api/agent-service
    boot; worker/watcher depend only on db), so it must crash-retry under
    supervision, never spend poison budget or dead-letter.
    """
    with _connect() as conn:
        assert_store_schema_with_connection(conn, repair_data=True)


def assert_store_schema_with_connection(conn, *, repair_data: bool = False) -> None:
    """Run the canonical schema assertion on a caller-owned transaction.

    Per-row boot repairs remain an ``_ensure_tables`` responsibility; ordinary
    transactional producers only need the fail-loud table/identity assertion.
    """
    with conn.cursor() as cur:
        missing_tables: list[str] = []
        for table in _STORE_TABLES:
            cur.execute("SELECT to_regclass(%s) AS oid", (table,))
            row = cur.fetchone()
            oid = row.get("oid") if isinstance(row, dict) else (row[0] if row else None)
            if oid is None:
                missing_tables.append(table)
        if missing_tables:
            raise StoreSchemaMissingError(
                f"Missing store table(s) {missing_tables} in the configured Postgres. "
                f"{_MIGRATION_HINT}"
            )
        # Bind the shape check to the exact relations resolved by to_regclass.
        # A migrated producer must never execute against the former global-key
        # shape: that would either cross namespaces or fail after a canonical
        # receipt had already been committed.
        cur.execute(
            """
            SELECT t.table_name,
                   (
                       SELECT array_agg(a.attname ORDER BY k.ordinality)
                       FROM pg_constraint c
                       JOIN unnest(c.conkey) WITH ORDINALITY k(attnum, ordinality) ON true
                       JOIN pg_attribute a
                         ON a.attrelid = c.conrelid AND a.attnum = k.attnum
                       WHERE c.conrelid = to_regclass(t.table_name)
                         AND c.contype = 'p'
                   ) AS pk_columns,
                   EXISTS (
                       SELECT 1 FROM pg_attribute a
                       WHERE a.attrelid = to_regclass(t.table_name)
                         AND a.attname = 'vault_binding_id'
                         AND a.attnum > 0 AND NOT a.attisdropped
                   ) AS has_binding
            FROM (VALUES
                ('store_objects'), ('store_vector_index'), ('store_relations'),
                ('store_relation_memberships'), ('vector_index_meta')
            ) AS t(table_name)
            """
        )
        expected_pks = {
            "store_objects": ["vault_binding_id", "object_id"],
            "store_vector_index": ["vault_binding_id", "object_id"],
            "store_relations": ["vault_binding_id", "src_id", "dst_id", "rel"],
            "store_relation_memberships": ["vault_binding_id", "src_id", "rel", "value"],
            "vector_index_meta": ["vault_binding_id", "id"],
        }
        shapes = {}
        for row in cur.fetchall():
            table_name = row.get("table_name") if isinstance(row, dict) else row[0]
            pk_columns = row.get("pk_columns") if isinstance(row, dict) else row[1]
            has_binding = row.get("has_binding") if isinstance(row, dict) else row[2]
            shapes[str(table_name)] = (list(pk_columns or []), bool(has_binding))
        stale = [table for table, pk in expected_pks.items() if shapes.get(table) != (pk, True)]
        cur.execute(
            """
            SELECT attname AS column_name FROM pg_attribute
            WHERE attrelid = to_regclass('store_vector_index')
              AND attnum > 0 AND NOT attisdropped
            """
        )
        present = {
            row.get("column_name") if isinstance(row, dict) else row[0] for row in cur.fetchall()
        }
        missing_identity = [col for col in _IDENTITY_COLUMNS if col not in present]
        if stale or missing_identity:
            raise StoreSchemaMissingError(
                f"Store schema has stale binding key(s) {stale} or missing vector identity "
                f"column(s) {missing_identity}. "
                f"{_MIGRATION_HINT}"
            )
        if repair_data:
            # Idempotent data repair (not DDL) — same repairs the old boot path ran.
            _run_data_repairs(cur)


def _run_data_repairs(cur) -> None:
    """Idempotent per-row data repairs (data, never DDL) run at store preflight.

    Runs in both the assert-only path and the test-only autocreate path so the
    migration-owned posture loses no repair the old create-on-boot path
    performed:

    - `dim` backfill: legacy environments hold rows written before the `dim`
      column existed; `PgVectorIndex.search` filters `WHERE dim = %s`, so a
      NULL-dim row would silently vanish from retrieval (I-S3 class).
    - provider/normalize identity backfill (`_backfill_identity_columns`).
    """
    cur.execute("UPDATE store_vector_index SET dim = array_length(embedding, 1) WHERE dim IS NULL")
    _backfill_identity_columns(cur)


def _backfill_identity_columns(cur) -> None:
    """Backfill per-row provider/normalize from the index-level identity.

    Idempotent: only rows with a NULL provider or normalize are touched, so a
    second run on an already-migrated database is a no-op. Object ids, vectors,
    dims, and models are never modified.
    """
    # vector_index_meta.identity_json is declared TEXT, so it must be cast to
    # jsonb before the ->> JSON field-access operator (which has no text overload).
    cur.execute(
        """
        UPDATE store_vector_index AS v
        SET provider = COALESCE(v.provider, (m.identity_json::jsonb)->>'provider'),
            normalize = COALESCE(v.normalize, ((m.identity_json::jsonb)->>'normalize')::boolean)
        FROM vector_index_meta AS m
        WHERE m.vault_binding_id = v.vault_binding_id
          AND m.id = 1
          AND (v.provider IS NULL OR v.normalize IS NULL)
        """
    )


_IDENTITY_REBUILD_HINT = "Run 'python -m app.cli index rebuild' to rebuild embeddings."


def _load_index_identity(
    cur, vault_binding_id: str = COMPATIBILITY_BINDING_ID
) -> EmbeddingIdentity | None:
    cur.execute(
        "SELECT identity_json FROM vector_index_meta "
        "WHERE vault_binding_id = %s AND id = 1 LIMIT 1",
        (vault_binding_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    try:
        data = json.loads(row["identity_json"])
        provider = str(data.get("provider") or "").strip()
        model = str(data.get("model") or "").strip()
        dim = int(data.get("dim") or 0)
        normalize = bool(data.get("normalize", True))
        if not provider or not model or dim <= 0:
            return None
        return EmbeddingIdentity(provider=provider, model=model, dim=dim, normalize=normalize)
    except Exception:
        return None


def _ensure_index_identity(
    cur,
    requested: EmbeddingIdentity,
    *,
    allow_create: bool,
    vault_binding_id: str = COMPATIBILITY_BINDING_ID,
) -> EmbeddingIdentity:
    stored = _load_index_identity(cur, vault_binding_id)
    if stored is None:
        if not allow_create:
            raise RuntimeError(f"Vector index identity missing. {_IDENTITY_REBUILD_HINT}")
        payload = json.dumps(asdict(requested), ensure_ascii=False)
        cur.execute(
            """
            INSERT INTO vector_index_meta (vault_binding_id, id, identity_json, updated_at)
            VALUES (%s, 1, %s, now())
            ON CONFLICT (vault_binding_id, id) DO NOTHING
            """,
            (vault_binding_id, payload),
        )
        return requested
    if (
        stored.provider != requested.provider
        or stored.model != requested.model
        or stored.dim != requested.dim
        or stored.normalize != requested.normalize
    ):
        raise RuntimeError(
            f"Embedding identity mismatch (stored provider={stored.provider} model={stored.model} dim={stored.dim} normalize={stored.normalize}; "
            f"requested provider={requested.provider} model={requested.model} dim={requested.dim} normalize={requested.normalize}). {_IDENTITY_REBUILD_HINT}"
        )
    return stored


def _resolve_primary_identity_for_write(
    cur,
    requested: EmbeddingIdentity,
    *,
    reconcilable_fallback: bool,
    vault_binding_id: str = COMPATIBILITY_BINDING_ID,
) -> EmbeddingIdentity:
    """Resolve the index PRIMARY identity for a write.

    Ordinary write: behaves like ``_ensure_index_identity(allow_create=True)`` —
    creates the primary identity if absent, otherwise requires the requested
    identity to match it (provider/model/dim/normalize), failing loud on drift.

    Reconcilable fallback write: the index must already have a primary identity
    (you cannot fall back from nothing); the primary identity stays unchanged and
    is returned even when the requested provider/model/normalize diverges from it.
    The dim guard is enforced by the caller against the returned primary dim.
    """
    if not reconcilable_fallback:
        return _ensure_index_identity(
            cur, requested, allow_create=True, vault_binding_id=vault_binding_id
        )
    primary = _load_index_identity(cur, vault_binding_id)
    if primary is None:
        raise RuntimeError(
            f"Reconcilable fallback write requires an existing primary vector index identity. {_IDENTITY_REBUILD_HINT}"
        )
    return primary


def pg_available() -> bool:
    try:
        with _connect() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def truncate_pg_tables(*, vault_binding_id: str = COMPATIBILITY_BINDING_ID) -> None:
    if not pg_available():
        return
    _ensure_tables()
    with _connect() as conn:
        with conn.cursor() as cur:
            # Do not hide reset scope behind an implicit CASCADE. Delete every
            # canonical-FK CASCADE consumer explicitly, then let the remaining
            # SET NULL consumers (decisions/audit) keep their declared rows.
            cur.execute(
                "DELETE FROM store_vector_index WHERE vault_binding_id = %s",
                (vault_binding_id,),
            )
            cur.execute(
                "DELETE FROM store_relation_memberships WHERE vault_binding_id = %s",
                (vault_binding_id,),
            )
            cur.execute(
                "DELETE FROM store_relations WHERE vault_binding_id = %s",
                (vault_binding_id,),
            )
            cur.execute(
                "DELETE FROM vector_index_meta WHERE vault_binding_id = %s",
                (vault_binding_id,),
            )
            cur.execute(
                "DELETE FROM public.chunks WHERE vault_binding_id = %s",
                (vault_binding_id,),
            )
            cur.execute(
                "DELETE FROM public.embeddings WHERE vault_binding_id = %s",
                (vault_binding_id,),
            )
            cur.execute(
                "DELETE FROM public.relations WHERE vault_binding_id = %s",
                (vault_binding_id,),
            )
            cur.execute(
                "DELETE FROM public.membership WHERE vault_binding_id = %s",
                (vault_binding_id,),
            )
            cur.execute(
                "DELETE FROM store_objects WHERE vault_binding_id = %s",
                (vault_binding_id,),
            )


def reset_vector_index(cur, *, vault_binding_id: str = COMPATIBILITY_BINDING_ID) -> None:
    cur.execute(
        "DELETE FROM store_vector_index WHERE vault_binding_id = %s",
        (vault_binding_id,),
    )
    cur.execute(
        "DELETE FROM vector_index_meta WHERE vault_binding_id = %s",
        (vault_binding_id,),
    )


def put_object_with_connection(
    conn,
    *,
    object_id: UUID,
    kind: str,
    source_ref: str | None,
    payload: dict,
    vault_binding_id: str = COMPATIBILITY_BINDING_ID,
) -> None:
    """Write a canonical object on a caller-owned Postgres transaction."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO store_objects (
                vault_binding_id, object_id, kind, source_ref, payload, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s::jsonb, now(), now())
            ON CONFLICT (vault_binding_id, object_id) DO UPDATE
            SET kind = EXCLUDED.kind,
                source_ref = EXCLUDED.source_ref,
                payload = EXCLUDED.payload,
                updated_at = now()
            """,
            (vault_binding_id, object_id, kind, source_ref, json.dumps(payload)),
        )


def put_object_if_absent_with_connection(
    conn,
    *,
    object_id: UUID,
    kind: str,
    source_ref: str | None,
    payload: dict,
    vault_binding_id: str = COMPATIBILITY_BINDING_ID,
) -> bool:
    """Atomically create one binding-scoped immutable object identity."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO store_objects (
                vault_binding_id, object_id, kind, source_ref, payload, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s::jsonb, now(), now())
            ON CONFLICT (vault_binding_id, object_id) DO NOTHING
            RETURNING object_id
            """,
            (vault_binding_id, object_id, kind, source_ref, json.dumps(payload)),
        )
        return cur.fetchone() is not None


def resolve_vault_uuid_with_connection(
    conn, vault_uuid: str, *, vault_binding_id: str = COMPATIBILITY_BINDING_ID
) -> str:
    """Resolve a retained vault UUID to one unambiguous canonical object id."""
    return _resolve_vault_uuid_with_connection(conn, vault_uuid, vault_binding_id=vault_binding_id)


def resolve_vault_uuid(vault_uuid: str, *, vault_binding_id: str = COMPATIBILITY_BINDING_ID) -> str:
    """Resolve retained identity through a fresh collision-checked snapshot."""
    with _connect() as conn:
        return resolve_vault_uuid_with_connection(
            conn, vault_uuid, vault_binding_id=vault_binding_id
        )


def vault_uuid_to_canonical_id_map_with_connection(
    conn, *, vault_binding_id: str = COMPATIBILITY_BINDING_ID
) -> dict[str, str]:
    """Return retained vault UUID -> canonical id from the shared identity join."""
    return _vault_uuid_to_canonical_id_map_with_connection(conn, vault_binding_id=vault_binding_id)


def retained_vault_uuid_with_connection(
    conn, object_id: str, *, vault_binding_id: str = COMPATIBILITY_BINDING_ID
) -> str | None:
    """Resolve canonical id -> retained vault UUID without inventing an alias."""
    return _retained_vault_uuid_with_connection(conn, object_id, vault_binding_id=vault_binding_id)


def update_object_source_ref_with_connection(
    conn,
    *,
    object_id: UUID,
    source_ref: str | None,
    vault_binding_id: str = COMPATIBILITY_BINDING_ID,
) -> None:
    """Move an existing canonical object's source on a caller transaction."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE store_objects
            SET source_ref = %s, updated_at = now()
            WHERE vault_binding_id = %s AND object_id = %s
            """,
            (source_ref, vault_binding_id, object_id),
        )
        if cur.rowcount != 1:
            raise RuntimeError(
                "Canonical store_objects parent is missing for vault-sync object "
                f"{object_id}; run migrations and reconcile the legacy objects row before retrying"
            )


class PgObjectStore(ObjectStore):
    rebuild_source = "vault ingest (vault notes → app/ingest/vault_alpha.py → store_objects)"
    _OBJECTS_TABLE = "store_objects"

    def __init__(self, *, vault_binding_id: str = COMPATIBILITY_BINDING_ID) -> None:
        self.vault_binding_id = vault_binding_id
        _ensure_tables()

    def _active_table(self, conn) -> str:
        del conn
        return self._OBJECTS_TABLE

    def get(self, object_id: UUID) -> dict | None:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT object_id, kind, source_ref, payload, created_at
                    FROM store_objects
                    WHERE vault_binding_id = %s AND object_id = %s
                    LIMIT 1
                    """,
                    (self.vault_binding_id, object_id),
                )
                row = cur.fetchone()
        return row if row else None

    def put(self, object_id: UUID, *, kind: str, source_ref: str, payload: dict) -> None:
        _ensure_tables()
        with _connect() as conn:
            put_object_with_connection(
                conn,
                object_id=object_id,
                kind=kind,
                source_ref=source_ref,
                payload=payload,
                vault_binding_id=self.vault_binding_id,
            )

    def put_if_absent(self, object_id: UUID, *, kind: str, source_ref: str, payload: dict) -> bool:
        _ensure_tables()
        with _connect() as conn:
            return put_object_if_absent_with_connection(
                conn,
                object_id=object_id,
                kind=kind,
                source_ref=source_ref,
                payload=payload,
                vault_binding_id=self.vault_binding_id,
            )

    def list_by_kind(self, kind: str, *, limit: int = 100) -> Iterable[dict]:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT object_id, kind, source_ref, payload, created_at
                    FROM store_objects
                    WHERE vault_binding_id = %s AND kind = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (self.vault_binding_id, kind, limit),
                )
                return cur.fetchall()

    def list_objects(self, kind: str | None = None, *, limit: int | None = 100) -> Iterable[dict]:
        with _connect() as conn:
            with conn.cursor() as cur:
                table = self._active_table(conn)
                if kind is not None:
                    stmt = sql.SQL(
                        """
                        SELECT object_id, kind, source_ref, payload, created_at
                        FROM {table}
                        WHERE vault_binding_id = %s AND kind = %s
                        ORDER BY created_at DESC
                        """
                    ).format(table=sql.Identifier(table))
                    params: tuple[object, ...] = (self.vault_binding_id, kind)
                else:
                    stmt = sql.SQL(
                        """
                        SELECT object_id, kind, source_ref, payload, created_at
                        FROM {table}
                        WHERE vault_binding_id = %s
                        ORDER BY created_at DESC
                        """
                    ).format(table=sql.Identifier(table))
                    params = (self.vault_binding_id,)
                if limit is not None:
                    stmt += sql.SQL(" LIMIT %s")
                    params = (*params, limit)
                cur.execute(stmt, params)
                return cur.fetchall()

    def count_objects(self, kind: str | None = None) -> int:
        with _connect() as conn:
            with conn.cursor() as cur:
                table = self._active_table(conn)
                if kind is not None:
                    stmt = sql.SQL(
                        "SELECT count(*) AS total FROM {table} "
                        "WHERE vault_binding_id = %s AND kind = %s"
                    ).format(table=sql.Identifier(table))
                    params = (self.vault_binding_id, kind)
                else:
                    stmt = sql.SQL(
                        "SELECT count(*) AS total FROM {table} WHERE vault_binding_id = %s"
                    ).format(table=sql.Identifier(table))
                    params = (self.vault_binding_id,)
                cur.execute(stmt, params)
                row = cur.fetchone()
        if not row:
            return 0
        if isinstance(row, dict):
            return int(row.get("total") or row.get("count") or 0)
        return int(row[0] or 0)


@dataclass
class _VectorHit:
    object_id: UUID
    payload: dict
    score: float


@dataclass(frozen=True)
class ConditionalVectorPurgeResult:
    """Atomic classification receipt for reconcile's semantic purge."""

    source_present: bool
    source_payload: dict | None
    source_indexable: bool
    purged: int


class PgVectorIndex(VectorIndex):
    rebuild_source = "PgObjectStore payloads + embedding model (see docs/EMBEDDINGS.md)"

    def __init__(self, *, vault_binding_id: str = COMPATIBILITY_BINDING_ID) -> None:
        self.vault_binding_id = vault_binding_id
        _ensure_tables()

    def get_identity(self) -> EmbeddingIdentity | None:
        _ensure_tables()
        with _connect() as conn:
            with conn.cursor() as cur:
                return _load_index_identity(cur, self.vault_binding_id)

    def upsert(
        self,
        object_id: UUID,
        *,
        kind: str,
        source_ref: str,
        payload: dict,
        embedding: list[float],
        model: str,
        identity: EmbeddingIdentity | None = None,
        reconcilable_fallback: bool = False,
    ) -> None:
        _ensure_tables()
        embedding_floats = coerce_floats(embedding)
        resolved_identity = identity or get_embedding_identity()
        if len(embedding_floats) != resolved_identity.dim:
            raise ValueError(
                f"embedding dim mismatch for identity {resolved_identity.model}: expected {resolved_identity.dim}, got {len(embedding_floats)}"
            )
        if model and model != resolved_identity.model:
            raise ValueError(
                f"embedding model mismatch: stored={resolved_identity.model} provided={model}"
            )
        model_value = model or resolved_identity.model
        with _connect() as conn:
            with conn.cursor() as cur:
                # The index keeps a stable PRIMARY identity in vector_index_meta,
                # used for queries and allow_create. An ordinary upsert must match
                # that primary identity. A reconcilable fallback write may diverge in
                # provider/model/normalize (recorded per-row), but the dim must always
                # match the primary identity — a dim mismatch fails loud and writes
                # nothing (CTI-1). See docs/EMBEDDING_RELIABILITY/DIMENSION_CONSISTENCY_AND_REINDEX.md.
                primary_identity = _resolve_primary_identity_for_write(
                    cur,
                    resolved_identity,
                    reconcilable_fallback=reconcilable_fallback,
                    vault_binding_id=self.vault_binding_id,
                )
                dim = primary_identity.dim
                if resolved_identity.dim != dim:
                    raise RuntimeError(
                        f"embedding dim mismatch for vector index (primary dim={dim}; "
                        f"requested provider={resolved_identity.provider} model={resolved_identity.model} "
                        f"dim={resolved_identity.dim}). {_IDENTITY_REBUILD_HINT}"
                    )
                if resolved_identity.normalize:
                    embedding_values = l2_normalize(embedding_floats)
                else:
                    embedding_values = embedding_floats
                cur.execute(
                    """
                    INSERT INTO store_vector_index (
                        vault_binding_id, object_id, kind, source_ref, payload, embedding,
                        dim, model, provider, normalize, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (vault_binding_id, object_id) DO UPDATE
                    SET kind = EXCLUDED.kind,
                        source_ref = EXCLUDED.source_ref,
                        payload = EXCLUDED.payload,
                        embedding = EXCLUDED.embedding,
                        dim = EXCLUDED.dim,
                        model = EXCLUDED.model,
                        provider = EXCLUDED.provider,
                        normalize = EXCLUDED.normalize,
                        updated_at = now()
                    """,
                    (
                        self.vault_binding_id,
                        object_id,
                        kind,
                        source_ref,
                        json.dumps(payload),
                        embedding_values,
                        resolved_identity.dim,
                        model_value,
                        resolved_identity.provider,
                        resolved_identity.normalize,
                    ),
                )

    def search(
        self, vector: list[float], *, k: int = 5, identity: EmbeddingIdentity | None = None
    ) -> List[_VectorHit]:
        _ensure_tables()

        query = coerce_floats(vector)

        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) AS total FROM store_vector_index "
                    "WHERE vault_binding_id = %s",
                    (self.vault_binding_id,),
                )
                total_row = cur.fetchone() or {}
                total = (
                    int(total_row.get("total") or 0)
                    if isinstance(total_row, dict)
                    else int(total_row[0] or 0)
                )
                if total == 0:
                    return []
                requested_identity = identity or get_embedding_identity()
                stored_identity = _ensure_index_identity(
                    cur,
                    requested_identity,
                    allow_create=False,
                    vault_binding_id=self.vault_binding_id,
                )
                if stored_identity.normalize:
                    query_norm = l2_normalize(query)
                else:
                    query_norm = query
                index_dim = stored_identity.dim
                if len(query_norm) != index_dim:
                    raise ValueError(
                        f"query embedding dim mismatch: expected {index_dim}, got {len(query_norm)}"
                    )
                cur.execute(
                    """
                    SELECT DISTINCT dim
                    FROM store_vector_index
                    WHERE vault_binding_id = %s
                    """,
                    (self.vault_binding_id,),
                )
                dims = {row["dim"] for row in cur.fetchall() if row["dim"] is not None}
                if not dims:
                    return []
                if len(dims) > 1 or next(iter(dims)) != index_dim:
                    raise RuntimeError("mixed embedding dimensions in index")
                cur.execute(
                    """
                    SELECT object_id, payload, embedding, updated_at
                    FROM store_vector_index
                    WHERE vault_binding_id = %s AND dim = %s
                    """,
                    (self.vault_binding_id, index_dim),
                )
                rows = cur.fetchall()
        if not rows:
            return []

        scored: List[Tuple[float, object, _VectorHit]] = []
        for row in rows:
            embedding = coerce_floats(row["embedding"] or [])
            if len(embedding) != index_dim:
                raise ValueError("stored embedding dim mismatch")
            if stored_identity.normalize:
                candidate_vector = l2_normalize(embedding)
            else:
                candidate_vector = embedding
            score = self._dot(query_norm, candidate_vector)
            scored.append(
                (
                    score,
                    row["updated_at"],
                    _VectorHit(object_id=row["object_id"], payload=row["payload"], score=score),
                )
            )
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [hit for _, _, hit in scored[:k]]

    @staticmethod
    def _dot(query: list[float], candidate: list[float]) -> float:
        length = min(len(query), len(candidate))
        return sum((query[i] or 0.0) * (candidate[i] or 0.0) for i in range(length))

    def purge_vectors(self, object_id: UUID, *, view: str) -> int:
        del view
        _ensure_tables()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM store_vector_index
                    WHERE vault_binding_id = %s AND object_id = %s
                    """,
                    (self.vault_binding_id, object_id),
                )
                return cur.rowcount or 0

    def purge_vector_if_present_source_non_indexable(
        self, object_id: UUID, *, view: str
    ) -> ConditionalVectorPurgeResult:
        """Purge only while a locked authoritative source is non-indexable.

        Reconcile's earlier candidate read is advisory: the source can change
        before mutation.  This method reclassifies the source under
        ``FOR UPDATE`` and performs the derived-row deletion in the same
        transaction, closing that read/purge TOCTOU window.
        """
        del view
        _ensure_tables()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload FROM store_objects "
                    "WHERE vault_binding_id = %s AND object_id = %s FOR UPDATE",
                    (self.vault_binding_id, object_id),
                )
                row = cur.fetchone()
                if row is None:
                    return ConditionalVectorPurgeResult(
                        source_present=False,
                        source_payload=None,
                        source_indexable=False,
                        purged=0,
                    )

                source_payload = dict(row.get("payload") or {})
                if canonicalize_indexable_text(source_payload):
                    return ConditionalVectorPurgeResult(
                        source_present=True,
                        source_payload=source_payload,
                        source_indexable=True,
                        purged=0,
                    )

                cur.execute(
                    "DELETE FROM store_vector_index "
                    "WHERE vault_binding_id = %s AND object_id = %s",
                    (self.vault_binding_id, object_id),
                )
                return ConditionalVectorPurgeResult(
                    source_present=True,
                    source_payload=source_payload,
                    source_indexable=False,
                    purged=cur.rowcount or 0,
                )

    def count_vectors(self) -> int:
        _ensure_tables()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) AS total FROM store_vector_index "
                    "WHERE vault_binding_id = %s",
                    (self.vault_binding_id,),
                )
                row = cur.fetchone()
        if not row:
            return 0
        if isinstance(row, dict):
            return int(row.get("total") or 0)
        return int(list(row.values())[0] or 0)

    def generation(self) -> str:
        """Cheap opaque store-generation token (G1res-1, #2981; identity-aware
        per ADR-0059 D2, #3403).

        ``count(*)`` changes on purge; ``max(updated_at)`` advances on every
        upsert (the upsert path always writes ``updated_at = now()``); the
        leading component is a short hash of ``vector_index_meta.identity_json``
        (empty-string component when no identity row exists yet), so an
        ADR-0052 repin that rewrites the identity WITHOUT touching any
        ``store_vector_index`` row also moves the token. All three signals
        come from one query — the identity lookup is a scalar subquery
        against the single-row (``id = 1``) ``vector_index_meta`` table, so
        this stays a single cheap query with no row scan.
        """
        _ensure_tables()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT "
                    "(SELECT identity_json FROM vector_index_meta "
                    "WHERE vault_binding_id = %s AND id = 1) AS identity_json, "
                    "count(*) AS total, "
                    "COALESCE(max(updated_at)::text, '') AS latest "
                    "FROM store_vector_index WHERE vault_binding_id = %s",
                    (self.vault_binding_id, self.vault_binding_id),
                )
                row = cur.fetchone()
        if not row:
            identity_json, total, latest = None, 0, ""
        elif isinstance(row, dict):
            identity_json = row.get("identity_json")
            total = int(row.get("total") or 0)
            latest = row.get("latest") or ""
        else:
            values = list(row.values())
            identity_json = values[0]
            total = int(values[1] or 0)
            latest = values[2] or ""
        identity_hash = hashlib.sha256((identity_json or "").encode("utf-8")).hexdigest()[
            :_IDENTITY_HASH_LEN
        ]
        return f"{identity_hash}:{total}:{latest}"

    def all_rows(self) -> List[dict]:
        """Return every durable row for a cache rebuild (KERNEL-05, I-D3).

        This is the single production read path a retrieval cache-through is
        allowed to bulk-load from; it never partial-loads or filters, so a
        rebuild from this method is always a faithful mirror of the durable
        index.

        ADR-0059 step 3: each row also carries its recorded ``model``/
        ``provider`` identity columns (EMBEDREL-06; no DDL — the columns
        already exist). This lets a cache-through rebuild recognize
        reconcilable CTI-2 fallback rows without a second query.
        """
        _ensure_tables()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT object_id, kind, source_ref, payload, embedding, model, provider, dim, normalize
                    FROM store_vector_index
                    WHERE vault_binding_id = %s
                    ORDER BY updated_at
                    """,
                    (self.vault_binding_id,),
                )
                rows = cur.fetchall()
        return [
            {
                "object_id": row["object_id"],
                "kind": row["kind"],
                "source_ref": row["source_ref"],
                "payload": row["payload"] or {},
                "embedding": coerce_floats(row["embedding"] or []),
                "model": row["model"],
                "provider": row["provider"],
                "dim": row["dim"],
                "normalize": row["normalize"],
            }
            for row in rows
        ]


class PgRelationIndex(RelationIndex):
    rebuild_source = (
        "vault frontmatter links + PgObjectStore (see docs/CONCEPTS/RELATION_TAXONOMY.md)"
    )

    def __init__(self, *, vault_binding_id: str = COMPATIBILITY_BINDING_ID) -> None:
        self.vault_binding_id = vault_binding_id
        _ensure_tables()

    def link(self, src: UUID, dst: UUID, *, rel: str, payload: dict | None = None) -> None:
        _ensure_tables()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO store_relations (
                        vault_binding_id, src_id, dst_id, rel, payload, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s::jsonb, now())
                    ON CONFLICT (vault_binding_id, src_id, dst_id, rel) DO NOTHING
                    """,
                    (self.vault_binding_id, src, dst, rel, json.dumps(payload or {})),
                )

    def neighbors(self, src: UUID, *, rel: str, k: int = 20) -> list[UUID]:
        _ensure_tables()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT dst_id
                    FROM store_relations
                    WHERE vault_binding_id = %s AND src_id = %s AND rel = %s
                    ORDER BY created_at ASC
                    LIMIT %s
                    """,
                    (self.vault_binding_id, src, rel, k),
                )
                rows = cur.fetchall()
        return [row["dst_id"] for row in rows]

    def has_any(self, src: UUID) -> bool:
        _ensure_tables()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM store_relations
                    WHERE vault_binding_id = %s AND (src_id = %s OR dst_id = %s)
                    LIMIT 1
                    """,
                    (self.vault_binding_id, src, src),
                )
                row = cur.fetchone()
        return bool(row)

    def add_membership(
        self, src: UUID, *, rel: str, value: str, payload: dict | None = None
    ) -> None:
        _ensure_tables()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO store_relation_memberships (
                        vault_binding_id, src_id, rel, value, payload, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s::jsonb, now())
                    ON CONFLICT (vault_binding_id, src_id, rel, value) DO UPDATE
                    SET payload = EXCLUDED.payload
                    """,
                    (self.vault_binding_id, src, rel, value, json.dumps(payload or {})),
                )

    def memberships(self, src: UUID, *, rel: str | None = None) -> list[RelationMembership]:
        _ensure_tables()
        with _connect() as conn:
            with conn.cursor() as cur:
                if rel is not None:
                    cur.execute(
                        """
                        SELECT src_id, rel, value, payload
                        FROM store_relation_memberships
                        WHERE vault_binding_id = %s AND src_id = %s AND rel = %s
                        ORDER BY created_at ASC
                        """,
                        (self.vault_binding_id, src, rel),
                    )
                else:
                    cur.execute(
                        """
                        SELECT src_id, rel, value, payload
                        FROM store_relation_memberships
                        WHERE vault_binding_id = %s AND src_id = %s
                        ORDER BY created_at ASC
                        """,
                        (self.vault_binding_id, src),
                    )
                rows = cur.fetchall()
        return [
            RelationMembership(
                object_id=row["src_id"],
                relation_type=str(row["rel"]),
                value=str(row["value"]),
                payload=dict(row.get("payload") or {}),
            )
            for row in rows
        ]


def inspect_pg_identity_tuples(*, vault_binding_id: str = COMPATIBILITY_BINDING_ID) -> list[dict]:
    """Return the distinct per-vector identity tuples present in store_vector_index.

    Each entry is ``{"provider", "model", "dim", "normalize", "count"}``. This is the
    raw material for mixed-identity detection (CTI-1): more than one entry means the
    index contains vectors from more than one embedding identity and must be reconciled.

    The grouping keys on the full ``(provider, model, dim, normalize)`` tuple — not
    provider alone — so a same-provider model swap at the same dim (e.g.
    ``ollama/nomic-embed-text`` -> ``ollama/mxbai-embed-large`` @ 768) is caught, not
    just cross-provider fallback.
    """
    _ensure_tables()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT provider, model, dim, normalize, COUNT(*) AS count
                FROM store_vector_index
                WHERE vault_binding_id = %s
                GROUP BY provider, model, dim, normalize
                ORDER BY provider, model, dim, normalize
                """,
                (vault_binding_id,),
            )
            rows = cur.fetchall()
    tuples: list[dict] = []
    for row in rows:
        tuples.append(
            {
                "provider": row["provider"],
                "model": row["model"],
                "dim": row["dim"],
                "normalize": row["normalize"],
                "count": int(row["count"] or 0),
            }
        )
    return tuples


def inspect_pg_metadata_completeness(
    *, limit: int = 5, vault_binding_id: str = COMPATIBILITY_BINDING_ID
) -> dict:
    """Return counts + sample ids of ``store_vector_index`` rows missing W3-SPINE-01 fields.

    Checks the retrieved-unit payload contract (``docs/DB_SCHEMA.md :: store_vector_index``)
    for the fields every row is expected to carry: ``language``, ``source_role``/``origin``
    (provenance), and ``embedding_identity`` (the per-row embedding-identity stamp). This is
    a completeness check (#2324), distinct from the identity-drift/mixed-identity checks
    (#2297): a row can carry a fully consistent, non-mixed identity and still be missing
    provenance or a language tag, e.g. rows written before the retrieved-unit payload
    contract was ratified.
    """
    _ensure_tables()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT object_id,
                       payload->>'language' AS language,
                       payload->>'source_role' AS source_role,
                       payload->>'origin' AS origin,
                       payload->'embedding_identity' AS embedding_identity
                FROM store_vector_index
                WHERE vault_binding_id = %s
                """,
                (vault_binding_id,),
            )
            rows = cur.fetchall()

    def _missing(row: dict) -> bool:
        language = row.get("language")
        source_role = row.get("source_role")
        origin = row.get("origin")
        identity = row.get("embedding_identity")
        if not language or str(language).strip().lower() in {"", "und"}:
            return True
        if not source_role and not origin:
            return True
        if not identity:
            return True
        return False

    missing_rows = [row for row in rows if _missing(row)]
    return {
        "checked": len(rows),
        "missing_count": len(missing_rows),
        "missing_sample_ids": [str(row["object_id"]) for row in missing_rows[:limit]],
    }


def inspect_pg_content_hash_staleness(
    *, limit: int = 5, vault_binding_id: str = COMPATIBILITY_BINDING_ID
) -> dict:
    """Return counts + sample ids of ``store_vector_index`` rows whose stored
    ``provenance.content_hash`` no longer matches the current ``store_objects``
    text (KERNEL-06, #2768).

    Read-only diagnosis only — never re-embeds or mutates. A mismatch means
    the source object's text changed since the vector was produced; ``index
    reconcile`` is the explicit, operator/agent-triggered repair (cross-task
    invariant #5: doctor detects, reconcile repairs, nothing auto-mutates).

    Rows with no recorded ``content_hash`` (written before this capability
    existed) are reported separately as ``unstamped_count`` rather than
    treated as stale — they need a rebuild to acquire a hash, not a
    content-drift re-embed.
    """
    _ensure_tables()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT v.object_id AS object_id,
                       v.payload->'provenance'->>'content_hash' AS stored_hash,
                       o.payload AS current_payload
                FROM store_vector_index AS v
                JOIN store_objects AS o
                  ON o.vault_binding_id = v.vault_binding_id
                 AND o.object_id = v.object_id
                WHERE v.vault_binding_id = %s
                """,
                (vault_binding_id,),
            )
            rows = cur.fetchall()

    from app.index.artifact_metadata import compute_payload_content_hash

    stale_ids: list[str] = []
    unstamped_ids: list[str] = []
    for row in rows:
        stored_hash = row.get("stored_hash")
        if not stored_hash:
            unstamped_ids.append(str(row["object_id"]))
            continue
        current_hash = compute_payload_content_hash(dict(row.get("current_payload") or {}))
        if current_hash != stored_hash:
            stale_ids.append(str(row["object_id"]))

    return {
        "checked": len(rows),
        "stale_count": len(stale_ids),
        "stale_sample_ids": stale_ids[:limit],
        "unstamped_count": len(unstamped_ids),
        "unstamped_sample_ids": unstamped_ids[:limit],
    }


def inspect_pg_index_state(*, vault_binding_id: str = COMPATIBILITY_BINDING_ID) -> dict:
    """Return diagnostics for the Postgres vector index (identity + dims)."""
    _ensure_tables()
    state: dict[str, object] = {}
    with _connect() as conn:
        with conn.cursor() as cur:
            identity = _load_index_identity(cur, vault_binding_id)
            state["identity"] = asdict(identity) if identity else None
            state["identity_present"] = identity is not None
            cur.execute(
                "SELECT DISTINCT dim FROM store_vector_index "
                "WHERE vault_binding_id = %s AND dim IS NOT NULL",
                (vault_binding_id,),
            )
            dims = [row["dim"] for row in cur.fetchall()]
            state["dims"] = dims
            cur.execute(
                "SELECT COUNT(*) AS total FROM store_vector_index WHERE vault_binding_id = %s",
                (vault_binding_id,),
            )
            total_rows = cur.fetchone().get("total") if cur else 0
            state["rows"] = total_rows
            if identity is not None:
                cur.execute(
                    "SELECT COUNT(*) AS drift FROM store_vector_index "
                    "WHERE vault_binding_id = %s AND array_length(embedding, 1) <> %s",
                    (vault_binding_id, identity.dim),
                )
                drift_row = cur.fetchone() or {"drift": 0}
                state["rows_wrong_dim"] = drift_row.get("drift", 0)
            else:
                state["rows_wrong_dim"] = None
    return state
