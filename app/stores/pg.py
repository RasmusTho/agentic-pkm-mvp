from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from typing import Iterable, List, Tuple
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.components.embeddings import EmbeddingIdentity, get_embedding_identity
from app.db.dsn import resolve_dsn
from app.embedding_config import assert_embed_dim, coerce_floats, l2_normalize

from .base import ObjectStore, RelationIndex, VectorIndex

_TABLES_READY = False


def _dsn() -> str:
    url = resolve_dsn()
    if not url:
        url = os.environ.get("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")
    if url.startswith("postgresql+psycopg://"):
        url = "postgresql://" + url.split("postgresql+psycopg://", 1)[1]
    return url


def _connect():
    return psycopg.connect(_dsn(), row_factory=dict_row)


def _ensure_tables() -> None:
    global _TABLES_READY
    if _TABLES_READY:
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
                CREATE TABLE IF NOT EXISTS vector_index_meta (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    identity_json TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute("ALTER TABLE store_vector_index ADD COLUMN IF NOT EXISTS dim INTEGER")
            cur.execute("UPDATE store_vector_index SET dim = array_length(embedding, 1) WHERE dim IS NULL")
    _TABLES_READY = True


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
            cur.execute("TRUNCATE TABLE vector_index_meta")


class PgObjectStore(ObjectStore):
    def __init__(self) -> None:
        _ensure_tables()

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


@dataclass
class _VectorHit:
    object_id: UUID
    payload: dict
    score: float


class PgVectorIndex(VectorIndex):
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
    ) -> None:
        _ensure_tables()
        embedding_floats = coerce_floats(embedding)
        assert_embed_dim(embedding_floats, name="embedding")
        embedding_norm = l2_normalize(embedding_floats)
        with _connect() as conn:
            with conn.cursor() as cur:
                stored_identity = _ensure_index_identity(cur, resolved_identity, allow_create=True)
                dim = stored_identity.dim
                if stored_identity.normalize:
                    embedding_values = l2_normalize(embedding_floats)
                else:
                    embedding_values = embedding_floats
                cur.execute(
                    """
                    INSERT INTO store_vector_index (
                        object_id, kind, source_ref, payload, embedding, dim, model, updated_at
                    )
                    VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, now())
                    ON CONFLICT (object_id) DO UPDATE
                    SET kind = EXCLUDED.kind,
                        source_ref = EXCLUDED.source_ref,
                        payload = EXCLUDED.payload,
                        embedding = EXCLUDED.embedding,
                        dim = EXCLUDED.dim,
                        model = EXCLUDED.model,
                        updated_at = now()
                    """,
                    (object_id, kind, source_ref, json.dumps(payload), embedding_norm, model),
                )

    def search(self, vector: list[float], *, k: int = 5, identity: EmbeddingIdentity | None = None) -> List[_VectorHit]:
        _ensure_tables()

        query = coerce_floats(vector)
        assert_embed_dim(query, name="query embedding")
        query_norm = l2_normalize(query)

        with _connect() as conn:
            with conn.cursor() as cur:
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
            assert_embed_dim(embedding, name="stored embedding")
            candidate_norm = l2_normalize(embedding)
            score = self._dot(query_norm, candidate_norm)
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


class PgRelationIndex(RelationIndex):
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
