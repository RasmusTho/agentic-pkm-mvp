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
from app.db.dsn import resolve_dsn
from app.db.errors import StoreSchemaMissingError
from app.embedding_config import coerce_floats, l2_normalize

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


def _ensure_tables() -> None:
    """Assert (or, in tests, create) the migration-owned store schema.

    Outside tests this is assert-only (KERNEL-04, #2766): a missing store
    table or identity column raises ``StoreSchemaMissingError`` with a
    "run migrations" hint instead of creating schema imperatively. The
    idempotent per-row **data** repairs (`_run_data_repairs`: dim backfill +
    identity backfill) always run — data repair, not DDL. Test fixtures set
    STORE_SCHEMA_AUTOCREATE=1 to keep create-on-demand for scratch databases.
    """
    global _TABLES_READY
    if _TABLES_READY:
        return
    if not _schema_autocreate_enabled():
        _assert_tables()
        _TABLES_READY = True
        return
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS store_objects (
                    object_id UUID PRIMARY KEY,
                    kind TEXT NOT NULL,
                    source_ref TEXT,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS store_vector_index (
                    object_id UUID PRIMARY KEY,
                    kind TEXT NOT NULL,
                    source_ref TEXT,
                    payload JSONB NOT NULL,
                    embedding DOUBLE PRECISION[] NOT NULL,
                    dim INTEGER NOT NULL,
                    model TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS store_relations (
                    src_id UUID NOT NULL,
                    dst_id UUID NOT NULL,
                    rel TEXT NOT NULL,
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (src_id, dst_id, rel)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS store_relation_memberships (
                    src_id UUID NOT NULL,
                    rel TEXT NOT NULL,
                    value TEXT NOT NULL,
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (src_id, rel, value)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS vector_index_meta (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    identity_json TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute("ALTER TABLE store_vector_index ADD COLUMN IF NOT EXISTS dim INTEGER")
            # Phase A (EMBEDREL-06): per-vector full embedding identity columns.
            # `model` and `dim` already exist; add `provider` and `normalize` so every
            # row records the complete (provider, model, dim, normalize) identity tuple.
            cur.execute("ALTER TABLE store_vector_index ADD COLUMN IF NOT EXISTS provider TEXT")
            cur.execute("ALTER TABLE store_vector_index ADD COLUMN IF NOT EXISTS normalize BOOLEAN")
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
        with conn.cursor() as cur:
            missing_tables: list[str] = []
            for table in _STORE_TABLES:
                cur.execute("SELECT to_regclass(%s) AS oid", (table,))
                row = cur.fetchone()
                if not (row and row.get("oid")):
                    missing_tables.append(table)
            if missing_tables:
                raise StoreSchemaMissingError(
                    f"Missing store table(s) {missing_tables} in the configured Postgres. "
                    f"{_MIGRATION_HINT}"
                )
            # Schema-scope the column check to match to_regclass resolution
            # (first schema on search_path): an unfiltered information_schema
            # query could see a same-named table in another schema and mask a
            # genuinely missing column, or fail on a complete one.
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = current_schema() AND table_name = 'store_vector_index'
                """
            )
            present = {row["column_name"] for row in cur.fetchall()}
            missing_columns = [col for col in _IDENTITY_COLUMNS if col not in present]
            if missing_columns:
                raise StoreSchemaMissingError(
                    f"store_vector_index is missing identity column(s) {missing_columns}. "
                    f"{_MIGRATION_HINT}"
                )
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
        WHERE m.id = 1
          AND (v.provider IS NULL OR v.normalize IS NULL)
        """
    )


_IDENTITY_REBUILD_HINT = "Run 'python -m app.cli index rebuild' to rebuild embeddings."


def _load_index_identity(cur) -> EmbeddingIdentity | None:
    cur.execute("SELECT identity_json FROM vector_index_meta WHERE id = 1 LIMIT 1")
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


def _ensure_index_identity(cur, requested: EmbeddingIdentity, *, allow_create: bool) -> EmbeddingIdentity:
    stored = _load_index_identity(cur)
    if stored is None:
        if not allow_create:
            raise RuntimeError(f"Vector index identity missing. {_IDENTITY_REBUILD_HINT}")
        payload = json.dumps(asdict(requested), ensure_ascii=False)
        cur.execute(
            """
            INSERT INTO vector_index_meta (id, identity_json, updated_at)
            VALUES (1, %s, now())
            ON CONFLICT (id) DO NOTHING
            """,
            (payload,),
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
        return _ensure_index_identity(cur, requested, allow_create=True)
    primary = _load_index_identity(cur)
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


def truncate_pg_tables() -> None:
    if not pg_available():
        return
    _ensure_tables()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE store_objects")
            cur.execute("TRUNCATE TABLE store_vector_index")
            cur.execute("TRUNCATE TABLE store_relations")
            cur.execute("TRUNCATE TABLE store_relation_memberships")
            cur.execute("TRUNCATE TABLE vector_index_meta")


def reset_vector_index(cur) -> None:
    cur.execute("DELETE FROM store_vector_index")
    cur.execute("DELETE FROM vector_index_meta")


class PgObjectStore(ObjectStore):
    rebuild_source = "vault ingest (vault notes → app/ingest/vault_alpha.py → store_objects)"
    _OBJECTS_TABLE = "store_objects"

    def __init__(self) -> None:
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
                    WHERE object_id = %s
                    LIMIT 1
                    """,
                    (object_id,),
                )
                row = cur.fetchone()
        return row if row else None

    def put(self, object_id: UUID, *, kind: str, source_ref: str, payload: dict) -> None:
        _ensure_tables()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO store_objects (object_id, kind, source_ref, payload, created_at, updated_at)
                    VALUES (%s, %s, %s, %s::jsonb, now(), now())
                    ON CONFLICT (object_id) DO UPDATE
                    SET kind = EXCLUDED.kind,
                        source_ref = EXCLUDED.source_ref,
                        payload = EXCLUDED.payload,
                        updated_at = now()
                    """,
                    (object_id, kind, source_ref, json.dumps(payload)),
                )

    def list_by_kind(self, kind: str, *, limit: int = 100) -> Iterable[dict]:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT object_id, kind, source_ref, payload, created_at
                    FROM store_objects
                    WHERE kind = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (kind, limit),
                )
                return cur.fetchall()

    def list_objects(self, kind: str | None = None, *, limit: int = 100) -> Iterable[dict]:
        with _connect() as conn:
            with conn.cursor() as cur:
                table = self._active_table(conn)
                if kind is not None:
                    stmt = sql.SQL(
                        """
                        SELECT object_id, kind, source_ref, payload, created_at
                        FROM {table}
                        WHERE kind = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                        """
                    ).format(table=sql.Identifier(table))
                    params = (kind, limit)
                else:
                    stmt = sql.SQL(
                        """
                        SELECT object_id, kind, source_ref, payload, created_at
                        FROM {table}
                        ORDER BY created_at DESC
                        LIMIT %s
                        """
                    ).format(table=sql.Identifier(table))
                    params = (limit,)
                cur.execute(stmt, params)
                return cur.fetchall()

    def count_objects(self, kind: str | None = None) -> int:
        with _connect() as conn:
            with conn.cursor() as cur:
                table = self._active_table(conn)
                if kind is not None:
                    stmt = sql.SQL("SELECT count(*) AS total FROM {table} WHERE kind = %s").format(table=sql.Identifier(table))
                    params = (kind,)
                else:
                    stmt = sql.SQL("SELECT count(*) AS total FROM {table}").format(table=sql.Identifier(table))
                    params = ()
                cur.execute(stmt, params)
                row = cur.fetchone()
        if not row:
            return 0
        if isinstance(row, dict):
            return int(row.get('total') or row.get('count') or 0)
        return int(row[0] or 0)


@dataclass
class _VectorHit:
    object_id: UUID
    payload: dict
    score: float


class PgVectorIndex(VectorIndex):
    rebuild_source = "PgObjectStore payloads + embedding model (see docs/EMBEDDINGS.md)"

    def __init__(self) -> None:
        _ensure_tables()

    def get_identity(self) -> EmbeddingIdentity | None:
        _ensure_tables()
        with _connect() as conn:
            with conn.cursor() as cur:
                return _load_index_identity(cur)

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
                        object_id, kind, source_ref, payload, embedding,
                        dim, model, provider, normalize, updated_at
                    )
                    VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (object_id) DO UPDATE
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

    def search(self, vector: list[float], *, k: int = 5, identity: EmbeddingIdentity | None = None) -> List[_VectorHit]:
        _ensure_tables()

        query = coerce_floats(vector)

        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) AS total FROM store_vector_index")
                total_row = cur.fetchone() or {}
                total = int(total_row.get("total") or 0) if isinstance(total_row, dict) else int(total_row[0] or 0)
                if total == 0:
                    return []
                requested_identity = identity or get_embedding_identity()
                stored_identity = _ensure_index_identity(cur, requested_identity, allow_create=False)
                if stored_identity.normalize:
                    query_norm = l2_normalize(query)
                else:
                    query_norm = query
                index_dim = stored_identity.dim
                if len(query_norm) != index_dim:
                    raise ValueError(f"query embedding dim mismatch: expected {index_dim}, got {len(query_norm)}")
                cur.execute(
                    """
                    SELECT DISTINCT dim
                    FROM store_vector_index
                    """
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
                    WHERE dim = %s
                    """
                    ,
                    (index_dim,),
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
                    WHERE object_id = %s
                    """,
                    (object_id,),
                )
                return cur.rowcount or 0

    def count_vectors(self) -> int:
        _ensure_tables()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) AS total FROM store_vector_index")
                row = cur.fetchone()
        if not row:
            return 0
        if isinstance(row, dict):
            return int(row.get('total') or 0)
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
                    "(SELECT identity_json FROM vector_index_meta WHERE id = 1) AS identity_json, "
                    "count(*) AS total, "
                    "COALESCE(max(updated_at)::text, '') AS latest "
                    "FROM store_vector_index"
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
                    ORDER BY updated_at
                    """
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
    rebuild_source = "vault frontmatter links + PgObjectStore (see docs/CONCEPTS/RELATION_TAXONOMY.md)"

    def __init__(self) -> None:
        _ensure_tables()

    def link(self, src: UUID, dst: UUID, *, rel: str, payload: dict | None = None) -> None:
        _ensure_tables()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO store_relations (src_id, dst_id, rel, payload, created_at)
                    VALUES (%s, %s, %s, %s::jsonb, now())
                    ON CONFLICT (src_id, dst_id, rel) DO NOTHING
                    """,
                    (src, dst, rel, json.dumps(payload or {})),
                )

    def neighbors(self, src: UUID, *, rel: str, k: int = 20) -> list[UUID]:
        _ensure_tables()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT dst_id
                    FROM store_relations
                    WHERE src_id = %s AND rel = %s
                    ORDER BY created_at ASC
                    LIMIT %s
                    """,
                    (src, rel, k),
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
                    WHERE src_id = %s OR dst_id = %s
                    LIMIT 1
                    """,
                    (src, src),
                )
                row = cur.fetchone()
        return bool(row)

    def add_membership(self, src: UUID, *, rel: str, value: str, payload: dict | None = None) -> None:
        _ensure_tables()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO store_relation_memberships (src_id, rel, value, payload, created_at)
                    VALUES (%s, %s, %s, %s::jsonb, now())
                    ON CONFLICT (src_id, rel, value) DO UPDATE
                    SET payload = EXCLUDED.payload
                    """,
                    (src, rel, value, json.dumps(payload or {})),
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
                        WHERE src_id = %s AND rel = %s
                        ORDER BY created_at ASC
                        """,
                        (src, rel),
                    )
                else:
                    cur.execute(
                        """
                        SELECT src_id, rel, value, payload
                        FROM store_relation_memberships
                        WHERE src_id = %s
                        ORDER BY created_at ASC
                        """,
                        (src,),
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


def inspect_pg_identity_tuples() -> list[dict]:
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
                GROUP BY provider, model, dim, normalize
                ORDER BY provider, model, dim, normalize
                """
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


def inspect_pg_metadata_completeness(*, limit: int = 5) -> dict:
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
                """
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


def inspect_pg_content_hash_staleness(*, limit: int = 5) -> dict:
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
                JOIN store_objects AS o ON o.object_id = v.object_id
                """
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


def inspect_pg_index_state() -> dict:
    """Return diagnostics for the Postgres vector index (identity + dims)."""
    _ensure_tables()
    state: dict[str, object] = {}
    with _connect() as conn:
        with conn.cursor() as cur:
            identity = _load_index_identity(cur)
            state["identity"] = asdict(identity) if identity else None
            state["identity_present"] = identity is not None
            cur.execute("SELECT DISTINCT dim FROM store_vector_index WHERE dim IS NOT NULL")
            dims = [row["dim"] for row in cur.fetchall()]
            state["dims"] = dims
            cur.execute("SELECT COUNT(*) AS total FROM store_vector_index")
            total_rows = cur.fetchone().get("total") if cur else 0
            state["rows"] = total_rows
            if identity is not None:
                cur.execute(
                    "SELECT COUNT(*) AS drift FROM store_vector_index WHERE array_length(embedding, 1) <> %s",
                    (identity.dim,),
                )
                drift_row = cur.fetchone() or {"drift": 0}
                state["rows_wrong_dim"] = drift_row.get("drift", 0)
            else:
                state["rows_wrong_dim"] = None
    return state
