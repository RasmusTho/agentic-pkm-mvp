from __future__ import annotations
from typing import Any, Dict, List, Tuple
from uuid import UUID

import app.search as search
from app.search.vector_index import VectorResult
from app.ingest import ingest_object as _ingest_object


def ingest_object(
    object_id: UUID | None,
    *,
    kind: str,
    source_ref: str,
    payload: Dict[str, Any],
    text: str,
) -> Tuple[UUID, int]:
    return _ingest_object(object_id=object_id, kind=kind, source_ref=source_ref, payload=payload, text=text)


def search_full_text(query_text: str, *, k: int = 5) -> List[VectorResult]:
    return []


def search_vector(query_embedding: List[float], *, k: int = 5) -> List[VectorResult]:
    idx = search.get_vector_index()
    return idx.query(embedding=query_embedding, k=k)


def search_hybrid(
    query_text: str,
    query_embedding: List[float],
    *,
    k: int = 5,
) -> List[VectorResult]:
    ft = search_full_text(query_text, k=k)
    vv = search_vector(query_embedding, k=k)

    seen: set[UUID] = set()
    out: List[VectorResult] = []

    for r in ft:
        if r.object_id not in seen:
            out.append(r)
            seen.add(r.object_id)
            if len(out) >= k:
                return out

    for r in vv:
        if r.object_id not in seen:
            out.append(r)
            seen.add(r.object_id)
            if len(out) >= k:
                return out

    return out[:k]
