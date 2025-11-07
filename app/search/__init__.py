from __future__ import annotations

import os

# Import only safe symbols at import time; delay PgVectorIndex to runtime.
try:
    from .vector_index import VectorResult, NullVectorIndex  # noqa: F401
except Exception:
    # Very defensive fallback for smoke environments
    VectorResult = None  # type: ignore

    class NullVectorIndex:  # type: ignore
        def upsert(self, *_, **__): return None
        def query(self, *_, **__): return []

def get_vector_index():
    """
    Backend selection rules:
    - STORE_BACKEND=pg and DATABASE_URL set  -> PgVectorIndex(dsn)
    - STORE_BACKEND=auto (default) and DATABASE_URL set -> PgVectorIndex(dsn)
    - Otherwise -> NullVectorIndex()
    """
    backend = os.getenv("STORE_BACKEND", "auto").lower().strip()
    dsn = os.getenv("DATABASE_URL", "").strip()

    use_pg = (backend == "pg" and bool(dsn)) or (backend in ("auto", "") and bool(dsn))
    if use_pg:
        try:
            # Local import so smoke doesn't require pg deps
            from .vector_index import PgVectorIndex
            return PgVectorIndex(dsn)
        except Exception:
            # Fall back silently if pg stack isn't available
            pass
    return NullVectorIndex()

__all__ = ["VectorResult", "get_vector_index", "NullVectorIndex"]
