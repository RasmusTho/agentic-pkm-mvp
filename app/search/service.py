from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from app.ingest import handle_post_ingest, normalize_payload
from app.search import get_vector_index
from app.search.embeddings import embed_text
from app.search.vector_index import VectorResult
from app.settings import settings


def _ensure_payload(payload: dict[str, Any], text: str) -> dict[str, Any]:
    return normalize_payload(payload, text)


def ingest_object(
    *,
    object_id: UUID | None,
    kind: str | None,
    source_ref: str | None,
    payload: dict[str, Any],
    text: str,
) -> tuple[UUID, int]:
    if not text.strip():
        raise ValueError("Ingest text may not be empty")
    target_id = object_id or uuid4()
    embedding = embed_text(text)
    resolved_payload = _ensure_payload(payload, text)
    index = get_vector_index()
    index.upsert(
        object_id=target_id,
        kind=kind,
        source_ref=source_ref,
        payload=resolved_payload,
        embedding=embedding,
        model=settings.embed_model,
    )
    handle_post_ingest(target_id, resolved_payload, text)
    return target_id, len(embedding)


def _call_sql(query: str, params: Sequence[Any]) -> list[dict[str, Any]]:
    with psycopg.connect(settings.psycopg_dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()


def search_full_text(query_text: str, *, k: int) -> list[VectorResult]:
    rows = _call_sql("SELECT * FROM search_ft(%s, %s)", (query_text, k))
    if not rows:
        return []
    object_ids = [UUID(row["object_id"]) for row in rows]
    placeholders = ",".join(["%s"] * len(object_ids))
    objs = _call_sql(
        f"SELECT id, payload FROM objects WHERE id IN ({placeholders})",
        [str(i) for i in object_ids],
    )
    payload_map = {str(row["id"]): row["payload"] for row in objs}
    results: list[VectorResult] = []
    for row in rows:
        oid = str(row["object_id"])
        payload = payload_map.get(oid, {})
        results.append(
            VectorResult(
                object_id=UUID(oid),
                score=float(row.get("rank_ft", 0.0)),
                payload=payload,
            )
        )
    return results


def search_vector(embedding: Sequence[float], *, k: int) -> list[VectorResult]:
    index = get_vector_index()
    return index.query(embedding=embedding, k=k)


def search_hybrid(query_text: str, embedding: Sequence[float], *, k: int) -> list[VectorResult]:
    max_results = max(k * 4, 10)
    ft_results = search_full_text(query_text, k=max_results)
    vec_results = search_vector(embedding, k=max_results)

    rank_ft = {result.object_id: idx for idx, result in enumerate(ft_results)}
    rank_vec = {result.object_id: idx for idx, result in enumerate(vec_results)}
    payload_map: dict[UUID, dict[str, Any]] = {}
    for result in ft_results + vec_results:
        payload_map.setdefault(result.object_id, result.payload)

    all_ids = set(rank_ft) | set(rank_vec)
    combined: list[VectorResult] = []
    k1 = 60
    k2 = 60
    for object_id in all_ids:
        ft_rank = rank_ft.get(object_id)
        vec_rank = rank_vec.get(object_id)
        score_ft = 1.0 / (k1 + ft_rank) if ft_rank is not None else 0.0
        score_vec = 1.0 / (k2 + vec_rank) if vec_rank is not None else 0.0
        combined.append(
            VectorResult(
                object_id=object_id,
                score=score_ft + score_vec,
                payload=payload_map.get(object_id, {}),
            )
        )

    combined.sort(key=lambda item: item.score, reverse=True)
    return combined[:k]
