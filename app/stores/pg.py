from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Iterable, List, Tuple
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

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
    _TABLES_READY = True


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

    def upsert(
        self,
        object_id: UUID,
        *,
        kind: str,
        source_ref: str,
        payload: dict,
        embedding: list[float],
        model: str,
    ) -> None:
        _ensure_tables()
        embedding_floats = coerce_floats(embedding)
        assert_embed_dim(embedding_floats, name="embedding")
        embedding_norm = l2_normalize(embedding_floats)
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO store_vector_index (
                        object_id, kind, source_ref, payload, embedding, model, updated_at
                    )
                    VALUES (%s, %s, %s, %s::jsonb, %s, %s, now())
                    ON CONFLICT (object_id) DO UPDATE
                    SET kind = EXCLUDED.kind,
                        source_ref = EXCLUDED.source_ref,
                        payload = EXCLUDED.payload,
                        embedding = EXCLUDED.embedding,
                        model = EXCLUDED.model,
                        updated_at = now()
                    """,
                    (object_id, kind, source_ref, json.dumps(payload), embedding_norm, model),
                )

    def search(self, vector: list[float], *, k: int = 5) -> List[_VectorHit]:
        _ensure_tables()

        query = coerce_floats(vector)
        assert_embed_dim(query, name="query embedding")
        query_norm = l2_normalize(query)

        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT object_id, payload, embedding, updated_at
                    FROM store_vector_index
                    """
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
