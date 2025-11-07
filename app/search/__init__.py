from .vector_index import VectorResult, NullVectorIndex, PgVectorIndex  # noqa: F401

def get_vector_index():
    import os
    dsn = os.getenv("DATABASE_URL") or ""
    backend = os.getenv("STORE_BACKEND", "auto")
    if backend == "pg" and dsn:
        try:
            return PgVectorIndex(dsn)  # kräver dsn i pg-läget
        except Exception:
            return NullVectorIndex()
    return NullVectorIndex()

try:
    from .service import get_search_service  # noqa: F401
except Exception:
    def get_search_service():
        return None

__all__ = ["VectorResult", "NullVectorIndex", "PgVectorIndex", "get_vector_index", "get_search_service"]
