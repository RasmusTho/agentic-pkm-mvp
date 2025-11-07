import os
from .vector_index import VectorResult, NullVectorIndex, PgVectorIndex

def get_vector_index():
    backend = os.getenv("STORE_BACKEND", "auto")
    dsn = os.getenv("DATABASE_URL", "")
    if backend == "pg" and dsn:
        try:
            return PgVectorIndex(dsn)
        except Exception:
            return NullVectorIndex()
    if backend == "auto" and dsn:
        try:
            return PgVectorIndex(dsn)
        except Exception:
            pass
    return NullVectorIndex()

try:
    from .service import get_search_service  # pragma: no cover
except Exception:
    def get_search_service():
        return None

__all__ = ["VectorResult", "get_vector_index", "NullVectorIndex", "PgVectorIndex", "get_search_service"]
