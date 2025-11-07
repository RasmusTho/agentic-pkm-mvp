from __future__ import annotations
import os

try:
    from .vector_index import VectorResult, NullVectorIndex  # noqa: F401
except Exception:
    VectorResult = None  # type: ignore
    class NullVectorIndex:  # type: ignore
        def upsert(self, *_, **__): return None
        def query(self, *_, **__): return []

def get_vector_index():
    backend = os.getenv("STORE_BACKEND", "auto").lower().strip()
    dsn = os.getenv("DATABASE_URL", "").strip()
    use_pg = (backend == "pg" and dsn) or (backend in ("auto", "") and dsn)
    if use_pg:
        try:
            from .vector_index import PgVectorIndex
            return PgVectorIndex(dsn)
        except Exception:
            pass
    return NullVectorIndex()

__all__ = ["VectorResult", "get_vector_index", "NullVectorIndex"]
