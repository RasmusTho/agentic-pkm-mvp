from __future__ import annotations
from typing import Any, Dict, List, Tuple
from uuid import UUID
from collections import defaultdict

from app.search.vector_index import get_vector_index, VectorResult
from app.ingest import ingest_object as _ingest_object  # re-export shim


def ingest_object(
    object_id: UUID | None,
    *,
    kind: str,
    source_ref: str,
    payload: Dict[str, Any],
    text: str,
) -> Tuple[UUID, int]:
    return _ingest_object(
        object_id=object_id,
        kind=kind,
        source_ref=source_ref,
        payload=payload,
        text=text,
    )


def search_full_text(query_text: str, *, k: int = 5) -> List[VectorResult]:
    # Stub: monkeypatchas i tester
    return []


def search_vector(query_embedding: List[float], *, k: int = 5) -> List[VectorResult]:
    idx = get_vector_index()
    return idx.query(embedding=query_embedding, k=k)


def search_hybrid(
    query_text: str,
    query_embedding: List[float],
    *,
    k: int = 5,
) -> List[VectorResult]:
    ft = search_full_text(query_text, k=k)
    vv = search_vector(query_embedding, k=k)

    K = 60.0
    fused: Dict[UUID, float] = defaultdict(float)
    payloads: Dict[UUID, Dict[str, Any]] = {}

    for i, r in enumerate(ft, start=1):
        fused[r.object_id] += 1.0 / (K + i)
        payloads.setdefault(r.object_id, r.payload)

    for i, r in enumerate(vv, start=1):
        fused[r.object_id] += 1.0 / (K + i)
        payloads.setdefault(r.object_id, r.payload)

    ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:k]
    return [VectorResult(object_id=oid, score=score, payload=payloads.get(oid, {})) for oid, score in ordered]
