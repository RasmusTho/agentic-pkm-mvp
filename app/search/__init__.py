from __future__ import annotations
from typing import Protocol, Sequence
from app.settings import settings
from .vector_index import PgVectorIndex  # använder din befintliga pgvector-implementation

class VectorIndex(Protocol):
    def upsert(
        self,
        *,
        object_id,
        kind: str | None,
        source_ref: str | None,
        payload: dict,
        embedding: Sequence[float],
        model: str,
    ) -> None: ...
    def query(
        self,
        *,
        embedding: Sequence[float],
        k: int = 10,
        filters: dict | None = None,
    ): ...

def get_vector_index() -> VectorIndex:
    # Skapar en PgVectorIndex mot din DATABASE_URL i settings
    return PgVectorIndex(settings.database_url)
