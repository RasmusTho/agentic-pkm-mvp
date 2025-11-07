from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple
from uuid import UUID, uuid4
import math

from app.search import get_vector_index
try:
    # Om VectorResult går att importera, använd den, annars fall tillbaka till dictar
    from app.search import VectorResult as _VectorResult  # type: ignore
except Exception:
    _VectorResult = None  # type: ignore

# ---- Minimal, deterministisk "embedding" för smoke ----
def _embed_text(text: str, dim: int = 64) -> List[float]:
    # Enkel, deterministisk vektor (ej ML) så tester kan köra utan nät/psycopg
    v = [0.0] * dim
    if not text:
        return v
    for i, ch in enumerate(text):
        v[i % dim] += (ord(ch) % 97) / 97.0
    # L2-normalisera
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]

# In-memory spegling för hybrid (keyword) för smoke
_mem_objects: Dict[str, Dict[str, Any]] = {}
_mem_terms: Dict[str, set[str]] = {}

def _tokenize(s: str) -> Iterable[str]:
    for w in s.lower().split():
        w = "".join(c for c in w if c.isalnum())
        if w:
            yield w

def ingest_object(*, object_id: UUID | str | None = None,
                  payload: Dict[str, Any] | None = None,
                  text: str = "",
                  model: str = "smoke") -> str:
    """
    Lägger in ett objekt i vektorindex (om tillgängligt) och i enkel in-memory keyword-index.
    Returnerar object_id (skapas om det inte gavs).
    """
    oid = str(object_id or uuid4())
    payload = payload or {}

    # 1) Vector-index (no-op om NullVectorIndex)
    idx = get_vector_index()
    emb = _embed_text(text)
    try:
        # Signaturen accepteras av både NullVectorIndex(*args, **kwargs) och PgVectorIndex
        idx.upsert(object_id=UUID(oid), kind=payload.get("kind"), source_ref=payload.get("source_ref"),
                   payload=payload, embedding=emb, model=model)  # type: ignore[arg-type]
    except Exception:
        # I smoke ska vi inte dö för att Pg-index saknas
        pass

    # 2) In-memory keyword-index för hybrid
    _mem_objects[oid] = {"payload": payload, "text": text}
    for t in _tokenize(text):
        _mem_terms.setdefault(t, set()).add(oid)
    return oid

def _cosine(a: List[float], b: List[float]) -> float:
    return sum(x*y for x, y in zip(a, b))

def search_vector(query: str, k: int = 10, filters: Dict[str, Any] | None = None) -> List[Any]:
    """
    Gör en vektorsökning via get_vector_index(); faller tillbaka till tom lista om NullVectorIndex.
    Returnerar VectorResult-objekt om de finns, annars dictar med object_id/score/payload.
    """
    idx = get_vector_index()
    qemb = _embed_text(query)
    try:
        results = idx.query(embedding=qemb, k=k, filters=filters)  # kan vara []
        # Om resultat redan är VectorResult, returnera som är; annars mappa till dictar.
        if results and isinstance(results[0], dict):
            return results
        return results  # typiskt List[VectorResult]
    except Exception:
        # NullVectorIndex eller annan smoke-miljö: kör en enkel cosine mot _mem_objects
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
    """
    Enkel RRF-liknande hybrid: kombinerar keyword-rank och vektor-rank.
    """
    # Keyword-score (rank baserat på förekomst och enkel tf)
    toks = list(_tokenize(query))
    kw_counts: Dict[str, int] = {}
    for t in toks:
        for oid in _mem_terms.get(t, ()):
            kw_counts[oid] = kw_counts.get(oid, 0) + 1
    kw_sorted = sorted(kw_counts.items(), key=lambda x: x[1], reverse=True)
    kw_rank: Dict[str, int] = {oid: i for i, (oid, _) in enumerate(kw_sorted, start=1)}

    # Vector-score (ranka sökresultat)
    vec_results = search_vector(query, k=max(k, 50))
    def _oid(x: Any) -> str:
        return str(x.object_id) if hasattr(x, "object_id") else str(x.get("object_id"))
    vec_rank: Dict[str, int] = {_oid(r): i for i, r in enumerate(vec_results, start=1)}

    # RRF-sammanvägning
    C = 60
    scores: Dict[str, float] = {}
    for oid in set(list(kw_rank.keys()) + list(vec_rank.keys())):
        s_kw = 1.0 / (C + kw_rank.get(oid, 10**6))
        s_vec = 1.0 / (C + vec_rank.get(oid, 10**6))
        scores[oid] = alpha * s_vec + (1.0 - alpha) * s_kw

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:k]

    # Bygg utdata i samma form som search_vector
    out: List[Any] = []
    payload_of = lambda oid: (_mem_objects.get(oid, {}).get("payload") or {})
    # Recycla redan byggda vec_results om möjligt
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
