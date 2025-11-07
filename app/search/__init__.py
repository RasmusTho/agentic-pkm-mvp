from __future__ import annotations

import os
from typing import List, Sequence, Any

# Minimal no-op index för smoke/CI utan pg/psycopg.
class NullVectorIndex:
    def upsert(
        self,
        *,
        object_id,
        kind: str | None,
        source_ref: str | None,
        payload: dict[str, Any],
        embedding: Sequence[float],
        model: str,
    ) -> None:
        return None

    def query(
        self,
        *,
        embedding: Sequence[float],
        k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list:
        return []

def get_vector_index():
    """Returnera en vektorindex-implementation.
    - Om STORE_BACKEND=pg och DATABASE_URL finns: försök PgVectorIndex.
    - Annars: NullVectorIndex.
    """
    backend = os.getenv("STORE_BACKEND", "auto").lower()
    dsn = os.getenv("DATABASE_URL", "")

    if backend == "pg" and dsn:
        try:
            from .vector_index import PgVectorIndex  # importera först när vi vet att vi ska använda pg
            return PgVectorIndex(dsn)
        except Exception:
            # Fallback säkrar att smoke aldrig dör på saknade pg/psycopg/pgvector
            pass
    return NullVectorIndex()

# (valfritt) re-exportera typer när de finns, utan att göra pg till ett krav
try:
    from .vector_index import VectorResult  # type: ignore
except Exception:  # pragma: no cover - inte kritiskt för smoke
    class VectorResult:  # minimal stub
        pass

__all__ = ["get_vector_index", "NullVectorIndex", "VectorResult"]
