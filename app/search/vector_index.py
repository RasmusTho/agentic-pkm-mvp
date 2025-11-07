from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence
from uuid import UUID

@dataclass(slots=True)
class VectorResult:
    object_id: UUID
    score: float
    payload: dict[str, Any]

class VectorIndex(Protocol):
    def upsert(
        self,
        *,
        object_id: UUID,
        kind: str | None,
        source_ref: str | None,
        payload: dict[str, Any],
        embedding: Sequence[float],
        model: str,
    ) -> None: ...
    def query(
        self,
        *,
        embedding: Sequence[float],
        k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorResult]: ...

class NullVectorIndex:
    def upsert(self, *_, **__) -> None:
        return None
    def query(self, *_, **__) -> list[VectorResult]:
        return []

class PgVectorIndex:
    """
    Postgres/pgvector-implementation. Importerar psycopg först i __init__
    så att modulimporten inte kräver pg-dependencies i smoke.
    """
    def __init__(self, dsn: str) -> None:
        if not dsn:
            raise RuntimeError("PgVectorIndex requires a DSN")
        try:
            import psycopg  # type: ignore
            from psycopg.rows import dict_row  # type: ignore
        except Exception as e:
            raise RuntimeError("psycopg not installed") from e
        self._dsn = dsn
        self._psycopg = psycopg
        self._dict_row = dict_row

    def upsert(
        self,
        *,
        object_id: UUID,
        kind: str | None,
        source_ref: str | None,
        payload: dict[str, Any],
        embedding: Sequence[float],
        model: str,
    ) -> None:
        # Placeholder för smoke: gör inget. Riktig impl kan komma senare.
        return None

    def query(
        self,
        *,
        embedding: Sequence[float],
        k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorResult]:
        # Placeholder för smoke: returnera tomt.
        return []

__all__ = ["VectorResult", "VectorIndex", "NullVectorIndex", "PgVectorIndex"]
