from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import psycopg
from psycopg.rows import dict_row


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
        vector_literal = format_vector(embedding)
        dim = len(embedding)
        with psycopg.connect(self._dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO objects (id, kind, source_ref, payload)
                    VALUES (%s, %s, %s, %s::jsonb)
                    ON CONFLICT (id) DO UPDATE
                      SET kind = EXCLUDED.kind,
                          source_ref = EXCLUDED.source_ref,
                          payload = EXCLUDED.payload
                    """,
                    (str(object_id), kind, source_ref, json.dumps(payload)),
                )
                cur.execute(
                    """
                    INSERT INTO embeddings (id, object_id, model, dim, vec)
                    VALUES (%s, %s, %s, %s, %s::vector)
                    ON CONFLICT (id) DO UPDATE
                      SET object_id = EXCLUDED.object_id,
                          model = EXCLUDED.model,
                          dim = EXCLUDED.dim,
                          vec = EXCLUDED.vec
                    """,
                    (
                        str(object_id),
                        str(object_id),
                        model,
                        dim,
                        vector_literal,
                    ),
                )

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
