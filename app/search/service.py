from __future__ import annotations

import os
from typing import Any, List


class NullSearchService:
    def search(self, query: str, k: int = 10) -> List[dict[str, Any]]:
        return []


class PgSearchService:
    def __init__(self, conn) -> None:
        self._conn = conn

    def search(self, query: str, k: int = 10) -> List[dict[str, Any]]:
        # Placeholder-implementation; riktig SQL kommer senare.
        return []


_service_singleton = None


def _connect():
    backend = os.getenv("STORE_BACKEND", "auto").lower()
    if backend != "pg":
        return None
    dsn = os.getenv("DATABASE_URL") or ""
    if not dsn:
        return None
    try:
        import psycopg  # importeras endast om vi faktiskt ska använda PG
        return psycopg.connect(dsn)
    except Exception:
        return None


def get_search_service():
    """Returnera singleton för söktjänst med säkert fallback-beteende."""
    global _service_singleton
    if _service_singleton is not None:
        return _service_singleton
    conn = _connect()
    _service_singleton = PgSearchService(conn) if conn else NullSearchService()
    return _service_singleton


__all__ = ["get_search_service", "NullSearchService", "PgSearchService"]
