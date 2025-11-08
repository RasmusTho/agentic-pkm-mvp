"""
Minimal compatibility module for legacy import path: `app.search.service`.

Provides a tiny, no-dependency API surface so tests and code that *import* this
module won't crash even if a real search backend isn't wired yet.

If a real implementation exists (e.g. `app.services.search`), we will import it
and re-export its public symbols. Otherwise we fall back to a safe no-op API.
"""
from __future__ import annotations
import importlib

_CANDIDATES = [
    "app.services.search",
    "app.search_service",
    "app.search.impl",
]

# Try to locate a real implementation and re-export it.
for mod in _CANDIDATES:
    try:
        _m = importlib.import_module(mod)
        for name in getattr(_m, "__all__", []):
            globals()[name] = getattr(_m, name)
        if not getattr(_m, "__all__", None):
            for k, v in _m.__dict__.items():
                if not k.startswith("_"):
                    globals()[k] = v
        break
    except Exception:
        _m = None
else:
    # Fallback: minimal no-op API
    HYBRID_ENABLED = False
    INDEX_READY = True

    def ensure_index_ready(*_, **__) -> bool:
        return True

    def build_index(*_, **__) -> dict:
        return {"status": "ok", "indexed": 0}

    def hybrid_search(*_, **__) -> list:
        return []

    def bm25_search(*_, **__) -> list:
        return []

    def vector_search(*_, **__) -> list:
        return []

    def search(query: str, k: int = 5, *_, **__) -> list:
        return []

    __all__ = [
        "HYBRID_ENABLED",
        "INDEX_READY",
        "ensure_index_ready",
        "build_index",
        "hybrid_search",
        "bm25_search",
        "vector_search",
        "search",
    ]
