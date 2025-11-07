import os
from .vector_index import VectorResult, NullVectorIndex, PgVectorIndex  # noqa: F401

def get_vector_index():
    backend = os.getenv("STORE_BACKEND", "auto")
    dsn = os.getenv("DATABASE_URL", "")
    if backend == "pg" and dsn:
        try:
            return PgVectorIndex(dsn)
        except Exception:
            return NullVectorIndex()
    if backend == "memory" or not dsn:
        return NullVectorIndex()
    try:
        return PgVectorIndex(dsn)
    except Exception:
        return NullVectorIndex()

try:
    from .service import get_search_service  # noqa: F401
except Exception:
    def get_search_service():
        return None

__all__ = ["VectorResult", "get_vector_index", "NullVectorIndex", "PgVectorIndex", "get_search_service"]
