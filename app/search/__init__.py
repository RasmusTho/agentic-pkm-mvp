"""
Lightweight search facade safe for CI smoke (no psycopg required).
Importing this module must not pull in Postgres dependencies.
"""
from __future__ import annotations
import os
from typing import Any, List

class NullVectorIndex:
    """No-op index used in memory/smoke runs."""
    def upsert(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        return None
    def search(self, *args: Any, **kwargs: Any) -> List[dict]:  # pragma: no cover
        return []

def get_vector_index() -> Any:
    """
    Return a vector index implementation without importing Postgres deps
    unless explicitly running with STORE_BACKEND=pg.
    """
    backend = os.getenv("STORE_BACKEND", "auto")
    if backend == "pg":
        try:
            # Import only when backend is pg and deps are available.
            from .vector_index import PgVectorIndex  # type: ignore
            return PgVectorIndex()
        except Exception:
            # Fallback to no-op in CI smoke if psycopg/pgvector is missing.
            return NullVectorIndex()
    # memory / auto default → no-op
    return NullVectorIndex()

__all__ = ["get_vector_index", "NullVectorIndex"]
