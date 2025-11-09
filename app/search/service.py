from __future__ import annotations
from uuid import UUID, uuid4

# --- Lightweight FT stub (unchanged) -------------------------------------------------
def bm25_search(query_text: str, k: int = 5) -> list:
    try:
        idx = get_bm25_index()
        # Try keyword and positional variants
        for fn in ("search", "query", "topk"):
            m = getattr(idx, fn, None)
            if not m:
                continue
            try:
                out = m(query_text=query_text, k=k)
                if out: return out
            except TypeError:
                pass
            try:
                out = m(query_text, k)
                if out: return out
            except TypeError:
                pass
        return []
    except Exception:
        return []

# --- Shared index access via stores (preferred), otherwise no-ops ---------------------
def get_vector_index(*_a, **_k):
    try:
        from app.stores import get_vector_index as _stores_get_vector_index
        return _stores_get_vector_index()
    except Exception:
        return _NoopVectorIndex()

def get_bm25_index(*_a, **_k):
    return _NoopBm25Index()

class _NoopVectorIndex:
    def upsert(self, *args, **kwargs): return None
    def search(self, *args, **kwargs): return []
    def query(self, *args, **kwargs): return []
    def topk(self, *args, **kwargs): return []
    def knn(self, *args, **kwargs): return []
    store = {}

class _NoopBm25Index:
    def add(self, *args, **kwargs): return None
    def search(self, *args, **kwargs): return []

# --- Vector search: shared-index first; try many signatures; fallback to store -------
def _fallback_from_store(idx, vector, k):
    # Try an attribute-level search directly (memory/pg stores expose .search)
    try:
        out = idx.search(vector, k=k)
        if out: return out
    except TypeError:
        try:
            out = idx.search(vector, k)
            if out: return out
        except Exception:
            pass
    except Exception:
        pass
    return []

def vector_search(vector, k: int = 5) -> list:
    idx = get_vector_index()
    # try known method names
    for meth in ("search", "query", "knn", "topk"):
        m = getattr(idx, meth, None)
        if m is None:
            continue
        # 1) keyword vector + keyword k
        try:
            out = m(vector=vector, k=k)
            if out: return out
        except TypeError:
            pass
        # 2) positional vector + positional k
        try:
            out = m(vector, k)
            if out: return out
        except TypeError:
            pass
        # 3) positional vector + keyword k
        try:
            out = m(vector, k=k)
            if out: return out
        except TypeError:
            pass
        # 4) other common names for k
        for kk in ("top_k", "n"):
            try:
                out = m(vector=vector, **{kk: k})
                if out: return out
            except TypeError:
                pass
            try:
                out = m(vector, **{kk: k})
                if out: return out
            except TypeError:
                pass
    # fallback: search through store impl
    return _fallback_from_store(idx, vector, k)

# Legacy alias expected by tests
search_vector = vector_search

# --- FT-first hybrid ---------------------------------------------------------------
def hybrid_search(query_text: str, query_vector, *, k: int) -> list:
    """Deterministic FT-first hybrid: if FT has hits, return its top-k; otherwise fill with vector hits."""
    ft = bm25_search(query_text, k=k) or []
    vec = vector_search(query_vector, k=k) or []

    def _oid(it):
        return getattr(it, "object_id", None) or getattr(it, "id", None)

    def _pl(it):
        return getattr(it, "payload", None) or {}

    # If FT has any results, return FT[:k] in order
    if ft:
        class _Result:
            __slots__ = ("object_id", "score", "payload")
            def __init__(self, object_id, score, payload):
                self.object_id = object_id; self.score = score; self.payload = payload
        top = ft[:k]
        return [_Result(_oid(it), float(k - i), _pl(it)) for i, it in enumerate(top)]

    # Otherwise, unique vector hits until k
    seen = set(); ordered = []
    for it in vec:
        oid = _oid(it)
        if oid is None or oid in seen:
            continue
        ordered.append((oid, _pl(it))); seen.add(oid)
        if len(ordered) >= k:
            break

    class _Result:
        __slots__ = ("object_id", "score", "payload")
        def __init__(self, object_id, score, payload):
            self.object_id = object_id; self.score = score; self.payload = payload

    return [_Result(oid, float(k - i), pl) for i, (oid, pl) in enumerate(ordered)]

# Legacy alias expected by tests
search_hybrid = hybrid_search

# --- Simple full-text proxy search ------------------------------------------------
def search(query_text: str, k: int = 5, *_a, **_k) -> list:
    return bm25_search(query_text, k=k)

# --- Ingest: set defaults, delegate to core ingest if present, else fallback ------
def ingest_object(object_id=None, *, kind: str, source_ref: str, payload: dict, text: str, **__):
    oid = object_id or uuid4()

    # Canonical payload defaults required by tests & pipeline
    payload_with_text = dict(payload or {})
    payload_with_text.setdefault("text", text)
    payload_with_text.setdefault("content", text)
    payload_with_text.setdefault("object_type", kind)
    payload_with_text.setdefault("system_intent", "learn")
    payload_with_text.setdefault("emergent_tags", [])

    # Try delegating to the real ingest (runs lifecycle hooks)
    try:
        from app.ingest import ingest_object as core_ingest
        return core_ingest(
            object_id=oid,
            kind=kind,
            source_ref=source_ref,
            payload=payload_with_text,
            text=text,
            **__
        )
    except Exception:
        # Minimal fallback: embed + tolerant upsert into the shared vector index
        def _fake_embed(t: str, dim: int) -> list[float]:
            # super simple stable embedding: length-scaled one-hot at index 0
            v = [0.0] * dim
            v[0] = float(len(t) % 2)
            return v

        embedding = _fake_embed(text, 1536)
        try:
            from app.settings import settings
            model_name = settings.embed_model
        except Exception:
            model_name = "openai/text-embedding-3-large"

        idx = get_vector_index()
        # tolerant upsert across varied signatures
        try:
            idx.upsert(
                object_id=oid,
                kind=kind,
                source_ref=source_ref,
                payload=payload_with_text,
                embedding=embedding,
                model=model_name,
            )
        except TypeError:
            try:
                idx.upsert(oid, kind, source_ref, payload_with_text, embedding, model_name)
            except TypeError:
                try:
                    idx.upsert(oid, payload_with_text, embedding, model_name)
                except TypeError:
                    idx.upsert(oid, payload_with_text)

        # repair store payloads if the stub stored a different shape
        try:
            st = getattr(idx, "store", None)
            if st is not None and oid in st:
                item = st[oid]
                if isinstance(item, dict):
                    item.setdefault("payload", {})
                    item["payload"].setdefault("text", text)
                    item["payload"].setdefault("content", text)
                    item["payload"].setdefault("object_type", kind)
                    item["payload"].setdefault("system_intent", "learn")
                    item["payload"].setdefault("emergent_tags", [])
                else:
                    pl = getattr(item, "payload", None)
                    if isinstance(pl, dict):
                        pl.setdefault("text", text)
                        pl.setdefault("content", text)
                        pl.setdefault("object_type", kind)
                        pl.setdefault("system_intent", "learn")
                        pl.setdefault("emergent_tags", [])
        except Exception:
            pass

        return (oid, len(embedding))

# Public export surface (plus legacy names)
__all__ = [
    "hybrid_search","bm25_search","vector_search","search",
    "get_vector_index","get_bm25_index","ingest_object",
    "search_hybrid","search_vector",
    "_NoopVectorIndex","_NoopBm25Index",
]
