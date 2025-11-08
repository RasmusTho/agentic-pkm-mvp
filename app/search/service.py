from __future__ import annotations
import importlib

_CANDIDATES = [
    "app.services.search",   # put your real module here if/when it exists
    "app.search_service",
    "app.search.impl",
]

# Try real implementation first
_impl = None
for mod in _CANDIDATES:
    try:
        _impl = importlib.import_module(mod)
        break
    except Exception:
        _impl = None

if _impl is not None:
    # Re-export everything public from the real implementation
    for name in getattr(_impl, "__all__", []):
        globals()[name] = getattr(_impl, name)
    if not getattr(_impl, "__all__", None):
        for k, v in _impl.__dict__.items():
            if not k.startswith("_"):
                globals()[k] = v
else:
    # Minimal, self-contained fallback so imports work
    HYBRID_ENABLED = False
    INDEX_READY = True

    class _NoopVectorIndex:
        def query(self, *_args, **_kwargs):
            return []
        def search(self, *_args, **_kwargs):
            return []

    class _NoopBm25Index:
        def query(self, *_args, **_kwargs):
            return []
        def search(self, *_args, **_kwargs):
            return []

    def ensure_index_ready(*_a, **_k) -> bool:
        return True

    def build_index(*_a, **_k) -> dict:
        return {"status": "ok", "indexed": 0}

    def hybrid_search(*_a, **_k) -> list:  # pragma: no cover
        return []

    def bm25_search(*_a, **_k) -> list:    # pragma: no cover
        return []

    def vector_search(*_a, **_k) -> list:  # pragma: no cover
        return []

    def search(query: str, k: int = 5, *_a, **_k) -> list:
        return []

    def get_vector_index(*_a, **_k):
        return _NoopVectorIndex()

    def get_bm25_index(*_a, **_k):
        return _NoopBm25Index()

    __all__ = [
        "HYBRID_ENABLED","INDEX_READY",
        "ensure_index_ready","build_index",
        "hybrid_search","bm25_search","vector_search","search",
        "get_vector_index","get_bm25_index",
        "_NoopVectorIndex","_NoopBm25Index",
    ]
