from __future__ import annotations
from uuid import UUID, uuid4
from typing import Any, Iterable
import logging

from app.components.retrieval import embed_query
from app.agents.panel.filters import strip_ai_panels
from app.index.artifact_metadata import build_indexed_unit_payload

logger = logging.getLogger(__name__)

# --- Noops om stores/bm25 saknas i minimal miljö -----------------------------

class _NoopVectorIndex:
    """
    Minimal in-memory vector index used in tests/dev.
    - Tolerant `upsert` (positional or keyword args)
    - Dot-product `search` with deterministic tiebreak by insert order
    - Exposes `store` so the fallback path can read payloads
    """
    def __init__(self) -> None:
        self._entries = {}      # object_id -> entry dict
        self._order = []        # insertion order
        self.store = {}         # legacy compat: id -> obj(payload=...)

    def _coerce_vec(self, v):
        try:
            return [float(x) for x in v]
        except Exception:
            return []

    def upsert(self, *args, **kwargs):
        from uuid import uuid4
        object_id = kwargs.get("object_id") if "object_id" in kwargs else (args[0] if len(args) > 0 else uuid4())
        kind      = kwargs.get("kind")      if "kind"      in kwargs else (args[1] if len(args) > 1 else "note")
        source_ref= kwargs.get("source_ref")if "source_ref"in kwargs else (args[2] if len(args) > 2 else "noop")
        payload   = kwargs.get("payload")   if "payload"   in kwargs else (args[3] if len(args) > 3 else {})
        emb = (
            kwargs.get("embedding")
            or kwargs.get("vector")
            or (args[4] if len(args) > 4 and isinstance(args[4], (list, tuple)) else [])
        )
        model = kwargs.get("model") if "model" in kwargs else (args[5] if len(args) > 5 else "test")
        entry = {
            "object_id": object_id,
            "kind": kind,
            "source_ref": source_ref,
            "payload": dict(payload or {}),
            "embedding": self._coerce_vec(emb),
            "model": model,
        }
        is_new = object_id not in self._entries
        self._entries[object_id] = entry
        if is_new:
            self._order.append(object_id)
        # legacy `store` view (used by fallback)
        self.store[object_id] = type("_Item", (), {"payload": entry["payload"], "kind": kind, "source_ref": source_ref, "model": model})

    def search(self, *args, **kwargs) -> list:
        k = (
            kwargs.get("k")
            or kwargs.get("top_k")
            or kwargs.get("n")
            or (args[1] if len(args) > 1 and isinstance(args[1], int) else 5)
        )
        qvec = (
            kwargs.get("vector")
            or kwargs.get("embedding")
            or (args[0] if len(args) > 0 else [])
        )
        q = self._coerce_vec(qvec)
        if not q or not self._entries:
            return []
        def dot(a, b):
            L = min(len(a), len(b))
            s = 0.0
            for i in range(L):
                s += (a[i] or 0.0) * (b[i] or 0.0)
            return s
        scored = []
        for idx, oid in enumerate(self._order):
            e = self._entries[oid]
            scored.append((dot(q, e["embedding"]), idx, e))
        scored.sort(key=lambda t: (-t[0], t[1]))
        class _Hit:
            __slots__ = ("object_id", "payload", "score", "kind", "source_ref", "model")
            def __init__(self, e, score):
                self.object_id = e["object_id"]
                self.payload = e["payload"]
                self.kind = e["kind"]
                self.source_ref = e["source_ref"]
                self.model = e["model"]
                self.score = float(score)
        return [_Hit(e, s) for s, _, e in scored[:int(k) if k else 5]]

    # aliases some fixtures use
    def query(self, *a, **k):  return self.search(*a, **k)
    def topk(self, *a, **k):   return self.search(*a, **k)
    def knn(self, *a, **k):    return self.search(*a, **k)
class _NoopVectorIndex:
    def search(self, *a, **k): return []
    def query(self, *a, **k):  return []
    def topk(self, *a, **k):   return []
    def knn(self, *a, **k):    return []
    def upsert(self, *a, **k): return None
    # test-fixtures kan stoppa in .store
    store: dict = {}

class _NoopBm25Index:
    def search(self, *a, **k): return []
    def query(self, *a, **k):  return []

def get_vector_index(*_a, **_k):
    try:
        from app.stores import get_vector_index as _stores_get_vector_index
        return _stores_get_vector_index()
    except Exception:
        return _NoopVectorIndex()

def get_bm25_index(*_a, **_k):
    try:
        # om ett internt BM25 finns
        from app.search.bm25_lite import Bm25Lite  # type: ignore
        return Bm25Lite()
    except Exception:
        return _NoopBm25Index()

# --- BM25 fulltext -----------------------------------------------------------

def search_full_text(query_text: str, *, k: int) -> list:
    idx = get_bm25_index()
    for name in ("search","query","topk"):
        m = getattr(idx, name, None)
        if not m: continue
        try:
            out = m(query_text, k=k)
            if out: return out
        except TypeError:
            pass
        try:
            out = m(query_text, **{"k": k})
            if out: return out
        except TypeError:
            pass
    return []

bm25_search = search_full_text

# --- Robust method-prober för vektor ----------------------------------------

def _call_methods(idx, method_names: list[str], *, kw_first: tuple[str, object], k: int) -> list:
    key, val = kw_first
    for meth in method_names:
        m = getattr(idx, meth, None)
        if m is None:
            continue
        # 1) keyword vector + keyword k
        try:
            out = m(**{key: val, "k": k})
            if out: return out
        except TypeError:
            pass
        # 2) positional vector + positional k
        try:
            out = m(val, k)
            if out: return out
        except TypeError:
            pass
        # 3) positional vector + keyword k
        try:
            out = m(val, k=k)
            if out: return out
        except TypeError:
            pass
    return []

# --- Fallback mot samma idx.store -------------------------------------------

def _dot(a: Iterable[float], b: Iterable[float]) -> float:
    total = 0.0
    for x, y in zip(a, b):
        total += (x or 0.0) * (y or 0.0)
    return total

def _fallback_from_store(idx, vector: list[float], k: int) -> list:
    store = getattr(idx, "store", None)
    if not store:
        return []
    results = []
    for oid, rec in getattr(store, "items", lambda: store.items())():
        emb = getattr(rec, "embedding", None) or (rec.get("embedding") if isinstance(rec, dict) else None)
        if not emb:
            continue
        score = _dot(vector, emb)
        class _Hit:
            __slots__ = ("object_id","payload","score","kind","source_ref","model")
            def __init__(self, oid, rec, score):
                self.object_id = oid
                self.payload = getattr(rec, "payload", None) or rec.get("payload", {})
                self.kind = getattr(rec, "kind", None) or rec.get("kind")
                self.source_ref = getattr(rec, "source_ref", None) or rec.get("source_ref")
                self.model = getattr(rec, "model", None) or rec.get("model")
                self.score = score
        results.append((score, _Hit(oid, rec, score)))
    results.sort(key=lambda t: -t[0])
    return [h for _, h in results[:k]]

# --- Vector search (shared-index + fallback) --------------------------------

def vector_search(query_vector: list[float], *, k: int) -> list:
    idx = get_vector_index()
    out = _call_methods(idx, ["search","query","topk","knn"], kw_first=("vector", query_vector), k=k)
    if out:
        return out
    # några index använder andra nycklar
    for vk in ("embedding","embeddings","vec"):
        out = _call_methods(idx, ["search","query","topk","knn"], kw_first=(vk, query_vector), k=k)
        if out:
            return out
    # sista säkerhetsnätet
    return _fallback_from_store(idx, query_vector, k)

search_vector = vector_search  # legacy-alias

# --- Hybrid (FT-first) ------------------------------------------------------

def hybrid_search(query_text: str, query_vector: list[float], *, k: int) -> list:
    """FT-prioriterad hybrid: FT[:k] om träffar; annars vektor, unika tills k."""
    ft = search_full_text(query_text, k=k) or []
    if ft:
        def _oid(it): return getattr(it, "object_id", None) or getattr(it, "id", None)
        def _pl(it):  return getattr(it, "payload", None) or {}
        class _Result:
            __slots__=("object_id","score","payload")
            def __init__(self, object_id, score, payload):
                self.object_id=object_id; self.score=score; self.payload=payload
        top = ft[:k]
        return [_Result(_oid(it), float(k-i), _pl(it)) for i, it in enumerate(top)]
    # annars fyll på med vektor
    vec = vector_search(query_vector, k=k) or []
    seen, ordered = set(), []
    def _oid(it): return getattr(it, "object_id", None) or getattr(it, "id", None)
    def _pl(it):  return getattr(it, "payload", None) or {}
    for it in vec:
        oid = _oid(it)
        if oid is None or oid in seen: continue
        ordered.append((oid, _pl(it))); seen.add(oid)
        if len(ordered) >= k: break
    class _Result:
        __slots__=("object_id","score","payload")
        def __init__(self, object_id, score, payload):
            self.object_id=object_id; self.score=score; self.payload=payload
    return [_Result(oid, float(k-i), pl) for i, (oid, pl) in enumerate(ordered)]

search_hybrid = hybrid_search  # legacy

# --- Simple search() ---------------------------------------------------------

def search(query_text: str, k: int = 5, *_a, **_k) -> list:
    return bm25_search(query_text, k=k)

def ingest_object(object_id=None, *, kind: str, source_ref: str, payload: dict, text: str, **__):
    oid = object_id or uuid4()
    safe_text = strip_ai_panels(text)

    embedding, identity = embed_query(safe_text)
    payload_out = build_indexed_unit_payload(
        object_id=oid,
        kind=kind,
        source_ref=source_ref,
        payload=payload,
        text=safe_text,
        embedding_identity=identity,
    )
    idx = get_vector_index()
    try:
        idx.upsert(
            object_id=oid,
            kind=kind,
            source_ref=source_ref,
            payload=payload_out,
            embedding=embedding,
            model=identity.model,
            identity=identity,
        )
    except TypeError as exc:
        raise TypeError("VectorIndex upsert must accept identity to enforce embedding identity") from exc

    try:
        st = getattr(idx, "store", None)
        if st is not None and oid in st:
            item = st[oid]
            if isinstance(item, dict):
                item.setdefault("payload", {})
                item["payload"].setdefault("text", safe_text)
                item["payload"].setdefault("content", safe_text)
                item["payload"].setdefault("object_type", kind)
                item["payload"].setdefault("system_intent", "learn")
                item["payload"].setdefault("emergent_tags", [])
            else:
                pl = getattr(item, "payload", None)
                if isinstance(pl, dict):
                    pl.setdefault("text", safe_text)
                    pl.setdefault("content", safe_text)
                    pl.setdefault("object_type", kind)
                    pl.setdefault("system_intent", "learn")
                    pl.setdefault("emergent_tags", [])
    except Exception:
        pass

    return (oid, len(embedding))

# Publik export-yta (plus legacy-namn)
__all__ = [
    "hybrid_search","bm25_search","vector_search","search",
    "get_vector_index","get_bm25_index","ingest_object",
    "search_hybrid","search_vector",
    "_NoopVectorIndex","_NoopBm25Index",
]
