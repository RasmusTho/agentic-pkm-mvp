from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import UUID
import math

@dataclass
class VectorResult:
    object_id: UUID
    score: float
    payload: Dict[str, Any]

@dataclass
class _Record:
    object_id: UUID
    kind: str
    source_ref: str
    payload: Dict[str, Any]
    embedding: List[float]
    model: str

def _norm(v: List[float]) -> float:
    return math.sqrt(sum(x * x for x in v)) or 1.0

def _normalize(v: List[float]) -> List[float]:
    n = _norm(v)
    return [x / n for x in v]

def _cosine(a: List[float], b: List[float]) -> float:
    m = min(len(a), len(b))
    return sum(a[i] * b[i] for i in range(m))

class _MemoryVectorIndex:
    def __init__(self) -> None:
        self.store: Dict[UUID, _Record] = {}

    def upsert(
        self,
        *,
        object_id: UUID,
        kind: str,
        source_ref: str,
        payload: Dict[str, Any],
        embedding: List[float],
        model: str,
    ) -> None:
        self.store[object_id] = _Record(
            object_id=object_id,
            kind=kind,
            source_ref=source_ref,
            payload=payload,
            embedding=list(embedding),
            model=model,
        )

    def query(self, query_embedding: List[float], *, k: int = 5) -> List[VectorResult]:
        if not self.store:
            return []
        q = _normalize(query_embedding)
        scored: List[VectorResult] = []
        for rec in self.store.values():
            s = _cosine(q, _normalize(rec.embedding))
            scored.append(VectorResult(object_id=rec.object_id, score=float(s), payload=rec.payload))
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:k]

_MEM_INDEX: Optional[_MemoryVectorIndex] = None

def get_vector_index() -> _MemoryVectorIndex:
    global _MEM_INDEX
    if _MEM_INDEX is None:
        _MEM_INDEX = _MemoryVectorIndex()
    return _MEM_INDEX
