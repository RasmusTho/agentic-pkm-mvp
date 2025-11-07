from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Tuple
from uuid import UUID, uuid4

from app.search import get_vector_index

try:
    # Om VectorResult går att importera, använd den; annars fall tillbaka till dictar.
    from app.search import VectorResult as _VectorResult  # type: ignore
except Exception:  # pragma: no cover - fallback i smoke-miljö utan psycopg
    _VectorResult = None  # type: ignore


def _embed_text(text: str, dim: int = 64) -> List[float]:
    """Deterministisk "embedding" för smoke utan externa beroenden."""
    v = [0.0] * dim
    if not text:
        return v
    for i, ch in enumerate(text):
        v[i % dim] += (ord(ch) % 97) / 97.0
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


_mem_objects: Dict[str, Dict[str, Any]] = {}
_mem_terms: Dict[str, set[str]] = {}


def _tokenize(s: str) -> Iterable[str]:
    for w in s.lower().split():
        w = "".join(c for c in w if c.isalnum())
        if w:
            yield w


def ingest_object(
    *,
    object_id: UUID | str | None = None,
    payload: Dict[str, Any] | None = None,
    text: str = "",
    model: str = "smoke",
) -> str:
    """Indexera objekt både i vektorindex (om finns) och i in-memory keyword-index."""
    oid = str(object_id or uuid4())
    payload = payload or {}

    idx = get_vector_index()
    emb = _embed_text(text)
    try:
        idx.upsert(  # type: ignore[attr-defined]
            object_id=UUID(oid),
            kind=payload.get("kind"),
            source_ref=payload.get("source_ref"),
            payload=payload,
            embedding=emb,
            model=model,
        )
    except Exception:
        pass  # NullVectorIndex eller annan no-op är ok i smoke

    _mem_objects[oid] = {"payload": payload, "text": text}
    for t in _tokenize(text):
        _mem_terms.setdefault(t, set()).add(oid)
    return oid


def _cosine(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def search_vector(query: str, k: int = 10, filters: Dict[str, Any] | None = None) -> List[Any]:
    """Utför vektorsökning via get_vector_index() med smoke-fallback till cosine."""
    idx = get_vector_index()
    qemb = _embed_text(query)
    try:
        results = idx.query(embedding=qemb, k=k, filters=filters)
        if results and isinstance(results[0], dict):
            return results
        return results
    except Exception:
        scored: List[Tuple[str, float]] = []
        for oid, rec in _mem_objects.items():
            emb = _embed_text(rec.get("text", ""))
            scored.append((oid, _cosine(qemb, emb)))
        scored.sort(key=lambda x: x[1], reverse=True)
        out: List[Any] = []
        for oid, score in scored[:k]:
            payload = _mem_objects[oid]["payload"]
            if _VectorResult:
                out.append(_VectorResult(object_id=UUID(oid), score=float(score), payload=payload))  # type: ignore
            else:
                out.append({"object_id": oid, "score": float(score), "payload": payload})
        return out


def search_hybrid(query: str, k: int = 10, alpha: float = 0.5) -> List[Any]:
    """Kombinera keyword-rank + vektor-rank via enkel RRF."""
    toks = list(_tokenize(query))
    kw_counts: Dict[str, int] = {}
    for t in toks:
        for oid in _mem_terms.get(t, ()):  # pragma: no cover - små datastrukturer
            kw_counts[oid] = kw_counts.get(oid, 0) + 1
    kw_sorted = sorted(kw_counts.items(), key=lambda x: x[1], reverse=True)
    kw_rank: Dict[str, int] = {oid: i for i, (oid, _) in enumerate(kw_sorted, start=1)}

    vec_results = search_vector(query, k=max(k, 50))

    def _oid(x: Any) -> str:
        return str(x.object_id) if hasattr(x, "object_id") else str(x.get("object_id"))

    vec_rank: Dict[str, int] = {_oid(r): i for i, r in enumerate(vec_results, start=1)}

    C = 60
    scores: Dict[str, float] = {}
    for oid in set(list(kw_rank.keys()) + list(vec_rank.keys())):
        s_kw = 1.0 / (C + kw_rank.get(oid, 10**6))
        s_vec = 1.0 / (C + vec_rank.get(oid, 10**6))
        scores[oid] = alpha * s_vec + (1.0 - alpha) * s_kw

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:k]

    out: List[Any] = []
    payload_of = lambda oid: (_mem_objects.get(oid, {}).get("payload") or {})
    vec_by_oid = {_oid(r): r for r in vec_results}
    for oid, _ in ranked:
        if oid in vec_by_oid:
            out.append(vec_by_oid[oid])
        else:
            payload = payload_of(oid)
            if _VectorResult:
                out.append(_VectorResult(object_id=UUID(oid), score=0.0, payload=payload))  # type: ignore
            else:
                out.append({"object_id": oid, "score": 0.0, "payload": payload})
    return out
