from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from datetime import datetime, timezone

from app.store.object_store import DomainObject, ObjectStore
from app.store.vector_store import VectorIndex as StoreVectorIndex


def format_vector(values: Sequence[float]) -> str:
    if not values:
        raise ValueError("Embedding vector is empty")
    formatted = ",".join(f"{value:.10f}" for value in values)
    return f"[{formatted}]"


@dataclass(slots=True)
class VectorResult:
    object_id: UUID
    score: float
    payload: dict[str, Any]


class VectorIndex(Protocol):
    def upsert(
        self,
        *,
        object_id: UUID,
        kind: str | None,
        source_ref: str | None,
        payload: dict[str, Any],
        embedding: Sequence[float],
        model: str,
    ) -> None:
        ...

    def query(
        self,
        *,
        embedding: Sequence[float],
        k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorResult]:
        ...


class PgVectorIndex(VectorIndex):
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._store = ObjectStore()
        self._vector_index = StoreVectorIndex()

    def upsert(
        self,
        *,
        object_id: UUID,
        kind: str | None,
        source_ref: str | None,
        payload: dict[str, Any],
        embedding: Sequence[float],
        model: str,
    ) -> None:
        object_uuid = str(object_id)
        existing = self._store.get_object(object_uuid)
        created_at = existing.created_at if existing else datetime.now(timezone.utc)

        merged_payload: dict[str, Any] = {}
        if existing and existing.payload:
            merged_payload.update(dict(existing.payload))
        merged_payload.update(payload)

        domain = DomainObject(
            uuid=object_uuid,
            kind=kind or (existing.kind if existing else "note"),
            payload=merged_payload,
            source_ref=source_ref if source_ref is not None else (existing.source_ref if existing else None),
            created_at=created_at,
        )
        self._store.save_object(domain, emit_outbox=False, trace_id=None)
        self._vector_index.upsert_embedding(object_uuid, embedding)

    def query(
        self,
        *,
        embedding: Sequence[float],
        k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorResult]:
        vector_literal = format_vector(embedding)
        where_clause = ""
        params: list[Any] = [vector_literal]
        if filters:
            where_clause = "WHERE obj.payload @> %s::jsonb"
            params.append(json.dumps(filters))
        params.extend([vector_literal, k])
        sql = f"""
            SELECT
              obj.id AS object_id,
              1 - (emb.vec <=> %s::vector) AS score,
              obj.payload
            FROM embeddings AS emb
            JOIN objects AS obj ON obj.id = emb.object_id
            {where_clause}
            ORDER BY emb.vec <=> %s::vector
            LIMIT %s
        """
        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        results: list[VectorResult] = []
        for row in rows:
            results.append(
                VectorResult(
                    object_id=UUID(row["object_id"]),
                    score=float(row["score"]),
                    payload=row["payload"],
                )
            )
        return results
