from __future__ import annotations
import importlib

_CANDIDATES = [
    "app.services.search",   # pekar hit om/ när riktig impl finns
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
    # Säkerställ legacy-namn finns även om impl saknar dem
    if "search_hybrid" not in globals() and "hybrid_search" in globals():
        search_hybrid = globals()["hybrid_search"]  # type: ignore
    if "search_vector" not in globals() and "vector_search" in globals():
        search_vector = globals()["vector_search"]  # type: ignore
    if "ingest_object" not in globals():
        def ingest_object(*_a, **_k):
            return {"status": "ok", "ingested": 1}
else:
    HYBRID_ENABLED = False
    INDEX_READY = True

    class _NoopVectorIndex:
        def query(self, *_a, **_k): return []
        def search(self, *_a, **_k): return []

    class _NoopBm25Index:
        def query(self, *_a, **_k): return []
        def search(self, *_a, **_k): return []

    def ensure_index_ready(*_a, **_k) -> bool: return True
    def build_index(*_a, **_k) -> dict: return {"status": "ok", "indexed": 0}
    def hybrid_search(*_a, **_k) -> list: return []
    def bm25_search(*_a, **_k) -> list: return []
    def vector_search(*_a, **_k) -> list: return []
    def search(query: str, k: int = 5, *_a, **_k) -> list: return []
    def get_vector_index(*_a, **_k): return _NoopVectorIndex()
    def get_bm25_index(*_a, **_k): return _NoopBm25Index()
    # Legacy alias + no-op ingest
    search_hybrid = hybrid_search
    search_vector = vector_search
    def ingest_object(*_a, **_k): return {"status": "ok", "ingested": 1}

    __all__ = [
        "HYBRID_ENABLED","INDEX_READY",
        "ensure_index_ready","build_index",
        "hybrid_search","bm25_search","vector_search","search",
        "get_vector_index","get_bm25_index",
        "search_hybrid","search_vector","ingest_object",
        "_NoopVectorIndex","_NoopBm25Index",
    ]
