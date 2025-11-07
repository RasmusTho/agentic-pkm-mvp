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
    """PgVector-implementation med lazy psycopg-import för smoke."""

    def __init__(self, dsn: str) -> None:
        if not dsn:
            raise RuntimeError("PgVectorIndex requires a DSN")
        try:
            import psycopg  # type: ignore
            from psycopg.rows import dict_row  # type: ignore
        except Exception as exc:  # pragma: no cover - miljö utan psycopg
            raise RuntimeError("psycopg not installed") from exc
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
        return None  # Placeholder för riktig implementation

    def query(
        self,
        *,
        embedding: Sequence[float],
        k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorResult]:
        return []  # Placeholder – smoke kräver bara struktur


__all__ = ["VectorResult", "VectorIndex", "NullVectorIndex", "PgVectorIndex"]
