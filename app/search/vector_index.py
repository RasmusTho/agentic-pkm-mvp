from __future__ import annotations
from typing import Any, Sequence, Protocol, NamedTuple

class VectorResult(NamedTuple):
    object_id: str
    score: float
    payload: dict[str, Any] | None = None

class VectorIndex(Protocol):
    def upsert(
        self,
        *,
        object_id: str,
        kind: str | None,
        source_ref: str | None,
        payload: dict[str, Any] | None,
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
    def upsert(self, **_: Any) -> None:
        return None
    def query(self, **_: Any) -> list[VectorResult]:
        return []

class PgVectorIndex:
    def __init__(self, dsn: str) -> None:
        try:
            import psycopg  # type: ignore
        except ModuleNotFoundError as e:
            raise RuntimeError("psycopg not installed") from e
        self._dsn = dsn
        self._psycopg = psycopg

    def upsert(self, **_: Any) -> None:
        # Placeholder för riktig pgvector-impl.
        return None

    def query(self, **_: Any) -> list[VectorResult]:
        # Placeholder – smoke kräver inte riktig sök.
        return []
