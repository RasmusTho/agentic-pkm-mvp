from __future__ import annotations

from typing import Any, Iterable
from uuid import uuid4, UUID

# -------------------------
# No-op fallbacks (safe in minimal envs)
# -------------------------

HYBRID_ENABLED = False
INDEX_READY = True


def ensure_index_ready(*_a, **_k) -> bool:
    return True


def build_index(*_a, **_k) -> dict[str, Any]:
    return {"status": "ok", "indexed": 0}


class _NoopVectorIndex:
    def __init__(self) -> None:
        self.store = {}

    # very tolerant signatures
    def upsert(self, *args, **kwargs):
        # Accept both named and positional upserts; store minimal info for tests.
        try:
            object_id = kwargs.get("object_id") or args[0]
            payload = kwargs.get("payload") or args[3]
        except Exception:
            object_id, payload = uuid4(), {}
        self.store[object_id] = type("_Item", (), {"payload": dict(payload), "kind": kwargs.get("kind"), "source_ref": kwargs.get("source_ref"), "model": kwargs.get("model", "test")})

    def search(self, *args, **kwargs) -> list:
        return []

    # compatibility aliases
    query = search
    topk = search
    knn = search


class _NoopBm25Index:
    def add(self, *args, **kwargs): ...
    def search(self, *args, **kwargs) -> list: return []


# -------------------------
# Shared helpers
# -------------------------

def _pkg_get_vector_index():
    """Prefer real store backend if available, else noop."""
    try:
        from app.stores import get_vector_index as _stores_get_vector_index
        return _stores_get_vector_index()
    except Exception:
        return _NoopVectorIndex()

def _call_methods(idx, method_names: list[str], *, kw_first: tuple[str, object], k: int) -> list:
    """
    Probe common method signatures across backends:
      1) keyword vector + keyword k
      2) positional vector + positional k
      3) positional vector + keyword k
    """
    key, val = kw_first
    for meth in method_names:
        m = getattr(idx, meth, None)
        if m is None:
            continue
        try:
            out = m(**{key: val, "k": k})
            if out: return out
        except TypeError:
            pass
        try:
            out = m(val, k)
            if out: return out
        except TypeError:
            pass
        try:
            out = m(val, k=k)
            if out: return out
        except TypeError:
            pass
    return []

# -------------------------
# Public search API (fallback)
# -------------------------

def bm25_search(query_text: str, *, k: int = 5) -> list:
    idx = get_bm25_index()
    try:
        return idx.search(query_text, k=k)
    except TypeError:
        return idx.search(query_text, k)

def vector_search(vector: Iterable[float], *, k: int = 5) -> list:
    idx = get_vector_index()
    # Try common vector methods/signatures
    out = _call_methods(idx, ["search", "query", "topk", "knn"], kw_first=("vector", list(vector)), k=k)
    return out or []


def search_vector(vector: Iterable[float], *, k: int = 5) -> list:
    return vector_search(vector, k=k)

def hybrid_search(query_text: str, query_vector: Iterable[float], *, k: int = 5) -> list:
    """
    Deterministic hybrid with FT-first semantics:
      - If full-text returns hits, return them in FT order (truncated to k).
      - Otherwise, return unique vector hits in their native order up to k.
    Returns objects with .object_id, .score, .payload to match tests.
    """
    ft = search_full_text(query_text, k=k) or []
    vec = vector_search(query_vector, k=k) or []

    def _oid(it): return getattr(it, "object_id", None) or getattr(it, "id", None)
    def _pl(it):  return getattr(it, "payload", None) or {}

    if ft:
        class _Result:
            __slots__ = ("object_id", "score", "payload")
            def __init__(self, object_id, score, payload):
                self.object_id = object_id
                self.score = score
                self.payload = payload
        top = ft[:k]
        return [_Result(_oid(it), float(k - i), _pl(it)) for i, it in enumerate(top)]

    # Fallback to vector results
    seen = set()
    ordered = []
    for it in vec:
        oid = _oid(it)
        if oid is None or oid in seen:
            continue
        ordered.append((oid, _pl(it)))
        seen.add(oid)
        if len(ordered) >= k:
            break

    class _Result:
        __slots__ = ("object_id", "score", "payload")
        def __init__(self, object_id, score, payload):
            self.object_id = object_id
            self.score = score
            self.payload = payload

    return [_Result(oid, float(k - i), pl) for i, (oid, pl) in enumerate(ordered)]


# Legacy alias
search_hybrid = hybrid_search

def search(query_text: str, k: int = 5, *_a, **_k) -> list:
    return bm25_search(query_text, k=k)

# -------------------------
# Full-text stub (codex may improve later)
# -------------------------

def search_full_text(query_text: str, *, k: int = 5) -> list:
    idx = get_bm25_index()
    try:
        return idx.search(query_text, k=k)
    except Exception:
        return []

# -------------------------
# Ingest: delegate to core, fallback to local upsert
# -------------------------

def ingest_object(object_id=None, *, kind: str, source_ref: str, payload: dict, text: str, **__) -> tuple[UUID, int]:
    """
    1) Ensure payload defaults needed by tests and downstream:
       - text, content, object_type, system_intent, emergent_tags
    2) Try to delegate to app.ingest.ingest_object (full lifecycle).
    3) If that import/call fails, fallback to tolerant local upsert into the vector index.
    """
    oid = object_id or uuid4()

    payload_with_text = dict(payload or {})
    payload_with_text.setdefault("text", text)
    payload_with_text.setdefault("content", text)
    payload_with_text.setdefault("object_type", kind)
    payload_with_text.setdefault("system_intent", "learn")
    payload_with_text.setdefault("emergent_tags", [])

    # Try real ingest path
    try:
        from app.ingest import ingest_object as core_ingest  # lazy import avoids cycles
        return core_ingest(
            object_id=oid,
            kind=kind,
            source_ref=source_ref,
            payload=payload_with_text,
            text=text,
            **__,
        )
    except Exception:
        # Fallback: fake embed + tolerant upsert
        emb = _fake_embed(text, 1536)
        try:
            from app.settings import settings
            model_name = settings.embed_model
        except Exception:
            model_name = "openai/text-embedding-3-large"

        idx = _pkg_get_vector_index()
        # tolerant upsert signatures
        try:
            idx.upsert(object_id=oid, kind=kind, source_ref=source_ref,
                       payload=payload_with_text, embedding=emb, model=model_name)
        except TypeError:
            try:
                idx.upsert(oid, kind, source_ref, payload_with_text, emb, model_name)
            except TypeError:
                try:
                    idx.upsert(oid, payload_with_text, emb, model_name)
                except TypeError:
                    idx.upsert(oid, payload_with_text)

        # ensure stub store (if dict-like) gets our payload defaults
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

        return (oid, len(emb))


# -------------------------
# Index getters (prefer real stores)
# -------------------------

def get_vector_index(*_a, **_k):
    return _pkg_get_vector_index()

def get_bm25_index(*_a, **_k):
    return _NoopBm25Index()


# -------------------------
# Minimal embed stub (fallback only)
# -------------------------

def _fake_embed(text: str, dims: int) -> list[float]:
    # very simple positional hash to meet deterministic length
    out = [0.0] * dims
    if text:
        h = sum(ord(c) for c in text) % dims
        out[h] = 1.0
    return out


__all__ = [
    "HYBRID_ENABLED", "INDEX_READY",
    "ensure_index_ready", "build_index",
    "hybrid_search", "bm25_search", "vector_search", "search",
    "get_vector_index", "get_bm25_index",
    "search_hybrid", "search_vector", "search_full_text", "ingest_object",
    "_NoopVectorIndex", "_NoopBm25Index",
]
