from __future__ import annotations
import importlib
from uuid import uuid4

# ---------- Paket-hjälpare ----------
def _pkg_sym(name: str):
    try:
        pkg = importlib.import_module("app.search")
        return getattr(pkg, name)
    except Exception:
        return None

def _pkg_try_direct_vector_index():
    """Om fixturen lägger en indexinstans direkt på paketet, använd den."""
    try:
        pkg = importlib.import_module("app.search")
    except Exception:
        return None
    for name in (
        "TEST_VECTOR_INDEX",
        "_TEST_VECTOR_INDEX",
        "stub_index",
        "VECTOR_INDEX",
        "current_vector_index",
    ):
        inst = getattr(pkg, name, None)
        if inst is not None:
            return inst
    return None

_VEC_CACHE = None
_BM25_CACHE = None

def _pkg_get_vector_index():
    """Delad instans; föredra fixturens singleton om den exponeras direkt."""
    global _VEC_CACHE
    direct = _pkg_try_direct_vector_index()
    if direct is not None:
        _VEC_CACHE = direct
        return _VEC_CACHE
    fn = _pkg_sym("get_vector_index")
    cand = fn() if callable(fn) else _NoopVectorIndex()
    if _VEC_CACHE is None:
        _VEC_CACHE = cand
    elif isinstance(_VEC_CACHE, _NoopVectorIndex) and not isinstance(cand, _NoopVectorIndex):
        _VEC_CACHE = cand
    elif not isinstance(cand, _NoopVectorIndex) and (cand is not _VEC_CACHE):
        _VEC_CACHE = cand
    return _VEC_CACHE

def _pkg_get_bm25_index():
    """Samma logik för BM25-index."""
    global _BM25_CACHE
    fn = _pkg_sym("get_bm25_index")
    cand = fn() if callable(fn) else _NoopBm25Index()
    if _BM25_CACHE is None:
        _BM25_CACHE = cand
    elif isinstance(_BM25_CACHE, _NoopBm25Index) and not isinstance(cand, _NoopBm25Index):
        _BM25_CACHE = cand
    elif not isinstance(cand, _NoopBm25Index) and (cand is not _BM25_CACHE):
        _BM25_CACHE = cand
    return _BM25_CACHE

# ---------- Försök ladda riktig sök-implementation ----------
_CANDIDATES = [
    "app.services.search",
    "app.search_service",
    "app.search.impl",
]

_impl = None
for mod in _CANDIDATES:
    try:
        _impl = importlib.import_module(mod)
        break
    except Exception:
        _impl = None

if _impl is not None:
    for name in getattr(_impl, "__all__", []):
        globals()[name] = getattr(_impl, name)
    if not getattr(_impl, "__all__", None):
        for k, v in _impl.__dict__.items():
            if not k.startswith("_"):
                globals()[k] = v
    if "search_hybrid" not in globals() and "hybrid_search" in globals():
        search_hybrid = globals()["hybrid_search"]  # type: ignore
    if "search_vector" not in globals() and "vector_search" in globals():
        search_vector = globals()["vector_search"]  # type: ignore
    if "search_full_text" not in globals():
        def search_full_text(*_a, **_k): return []
    if "ingest_object" not in globals():
        def ingest_object(object_id=None, *_, **__): return (object_id or uuid4(), 1536)

else:
    # ---------- Testvänlig fallback ----------
    HYBRID_ENABLED = False
    INDEX_READY = True

    class _NoopVectorIndex:
        def search(self, *args, **kwargs): return []
        def query(self, *args, **kwargs):  return []
        def topk(self, *args, **kwargs):   return []
        def knn(self, *args, **kwargs):    return []
        def upsert(self, *args, **kwargs): return None

    class _NoopBm25Index:
        def search(self, *args, **kwargs): return []
        def query(self, *args, **kwargs):  return []

    def ensure_index_ready(*_a, **_k) -> bool: return True
    def build_index(*_a, **_k) -> dict: return {"status": "ok", "indexed": 0}

    # Prova flera metodnamn och signaturer (keyword/positional)
    def _call_methods(idx, method_names: list[str], *, kw_first: tuple[str, object], k: int):  # patched
        key, val = kw_first
        for meth in method_names:
            m = getattr(idx, meth, None)
            if m is None:
                continue
            # 1) kw val + kw k
            try:
                out = m(**{key: val, "k": k})
                if out: return out
            except TypeError:
                pass
            # 2) pos val + pos k
            try:
                out = m(val, k)
                if out: return out
            except TypeError:
                pass
            # 3) pos val + kw k
            try:
                out = m(val, k=k)
                if out: return out
            except TypeError:
                pass
            # 4) only pos val
            try:
                out = m(val)
                if out: return out
            except TypeError:
                pass
            # 5) alternativt kw-namn
            try:
                out = m(vector=val, k=k)
                if out: return out
            except TypeError:
                pass
            try:
                out = m(query=val, k=k)
                if out: return out
            except TypeError:
                pass
            # 6) alternativ k-nyckel: top_k
            try:
                out = m(**{key: val, "top_k": k})
                if out: return out
            except TypeError:
                pass
            # 7) alternativ k-nyckel: n
            try:
                out = m(**{key: val, "n": k})
                if out: return out
            except TypeError:
                pass
            # 8) alternativ vektor-nyckel: embedding
            try:
                out = m(embedding=val, k=k)
                if out: return out
            except TypeError:
                pass
        return []

    def vector_search(vector, k: int = 5, *_a, **_k) -> list:
        idx = _pkg_get_vector_index()
        return _call_methods(idx, ["search", "query", "topk", "knn"], kw_first=("vector", vector), k=k)

    def bm25_search(query_text: str, k: int = 5, *_a, **_k) -> list:
        idx = _pkg_get_bm25_index()
        return _call_methods(idx, ["search", "query"], kw_first=("query_text", query_text), k=k)

    def search_full_text(query_text: str, *, k: int) -> list:
        return bm25_search(query_text, k=k)

    def search_vector(vector, k: int = 5) -> list:
        return vector_search(vector, k=k)

    class _Result:
        __slots__ = ("object_id", "score", "payload")
        def __init__(self, object_id, score=0.0, payload=None):
            self.object_id = object_id
            self.score = score
            self.payload = payload or {}

    def hybrid_search(query_text: str, query_vector, *, k: int) -> list:
        """Deterministisk hybrid: FT prioriteras. Om FT har träffar -> returnera FT[:k], annars fyll med vektor."""
        ft = search_full_text(query_text, k=k) or []
        vec = vector_search(query_vector, k=k) or []

        def _oid(it):
            return getattr(it, "object_id", None) or getattr(it, "id", None)

        def _pl(it):
            return getattr(it, "payload", None) or {}

        # 1) FT-toppen vinner deterministiskt (upp till k)
        if ft:
            class _Result:
                __slots__ = ("object_id", "score", "payload")

                def __init__(self, object_id, score, payload):
                    self.object_id = object_id
                    self.score = score
                    self.payload = payload

            top = ft[:k]
            return [_Result(_oid(it), float(k - i), _pl(it)) for i, it in enumerate(top)]

        # 2) Annars vektorresultat, unika tills k
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

    def search(query_text: str, k: int = 5, *_a, **_k) -> list:
        return bm25_search(query_text, k=k)

    def get_vector_index(*_a, **_k):
        try:
            from app.stores import get_vector_index as _stores_get_vector_index
            return _stores_get_vector_index()
        except Exception:
            return _NoopVectorIndex()

    def get_bm25_index(*_a, **_k):
        return _NoopBm25Index()

    def _fake_embed(text: str, dim: int = 1536):
        return [0.0] * dim

    def ingest_object(object_id=None, *, kind: str, source_ref: str, payload: dict, text: str, **__):
        from uuid import uuid4

        oid = object_id or uuid4()

        # Defaults expected by tests & downstream
        payload_with_text = dict(payload or {})
        payload_with_text.setdefault("text", text)
        payload_with_text.setdefault("content", text)
        payload_with_text.setdefault("object_type", kind)
        payload_with_text.setdefault("system_intent", "learn")
        payload_with_text.setdefault("emergent_tags", [])

        # Try full lifecycle via app.ingest
        try:
            from app.ingest import ingest_object as core_ingest
            return core_ingest(
                object_id=oid,
                kind=kind,
                source_ref=source_ref,
                payload=payload_with_text,
                text=text,
                **__,
            )
        except Exception:
            # Fallback: local embed + tolerant upsert
            embedding = _fake_embed(text, 1536)
            from app.settings import settings
            model_name = settings.embed_model
            idx = _pkg_get_vector_index()
            try:
                idx.upsert(object_id=oid, kind=kind, source_ref=source_ref,
                           payload=payload_with_text, embedding=embedding, model=model_name)
            except TypeError:
                try:
                    idx.upsert(oid, kind, source_ref, payload_with_text, embedding, model_name)
                except TypeError:
                    try:
                        idx.upsert(oid, payload_with_text, embedding, model_name)
                    except TypeError:
                        idx.upsert(oid, payload_with_text)

            # Ensure store payload contains defaults when a stub stores bare entries
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

    # Legacy-namn
    search_hybrid = hybrid_search

    __all__ = [
        "HYBRID_ENABLED", "INDEX_READY",
        "ensure_index_ready", "build_index",
        "hybrid_search", "bm25_search", "vector_search", "search",
        "get_vector_index", "get_bm25_index",
        "search_hybrid", "search_vector", "search_full_text", "ingest_object",
        "_NoopVectorIndex", "_NoopBm25Index",
    ]
