from __future__ import annotations

from functools import lru_cache

from app.settings import settings

from .vector_index import PgVectorIndex, VectorIndex


@lru_cache(maxsize=1)
def get_vector_index() -> VectorIndex:
    backend = (settings.vector_backend or "pgvector").lower()
    if backend != "pgvector":
        raise NotImplementedError(
            f"Vector backend '{backend}' is not supported. Only pgvector is currently available."
        )
    return PgVectorIndex(settings.db_dsn)


__all__ = ["get_vector_index", "VectorIndex"]
