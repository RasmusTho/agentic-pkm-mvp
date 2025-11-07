from __future__ import annotations
import os
from typing import Any, List, Optional

_psycopg = None  # lazy-laddas vid första connect

def _connect():
    dsn = os.getenv("DATABASE_URL") or ""
    if not dsn:
        return None
    global _psycopg
    try:
        if _psycopg is None:
            import psycopg as _pg  # lazy import
            globals()["_psycopg"] = _pg
        return _psycopg.connect(dsn)
    except Exception:
        return None

class NullSearchService:
    def search(self, query: str, k: int = 10) -> List[dict[str, Any]]:
        return []

class PgSearchService:
    def __init__(self, conn):
        self._conn = conn
    def search(self, query: str, k: int = 10) -> List[dict[str, Any]]:
        # Placeholder – riktig implementation kan använda pg/pgvector senare.
        return []

_service_singleton: Optional[object] = None

def get_search_service():
    """Returnera singleton för söktjänst med säkert fallback-beteende."""
    global _service_singleton
    if _service_singleton is not None:
        return _service_singleton
    conn = _connect()
    _service_singleton = PgSearchService(conn) if conn is not None else NullSearchService()
    return _service_singleton
PY# Smoke-säker söktjänst: lazy psycopg + Null fallback
cat > app/search/service.py <<'PY'
from __future__ import annotations
import os
from typing import Any, List, Optional

_psycopg = None  # lazy-laddas vid första connect

def _connect():
    dsn = os.getenv("DATABASE_URL") or ""
    if not dsn:
        return None
    global _psycopg
    try:
        if _psycopg is None:
            import psycopg as _pg  # lazy import
            globals()["_psycopg"] = _pg
        return _psycopg.connect(dsn)
    except Exception:
        return None

class NullSearchService:
    def search(self, query: str, k: int = 10) -> List[dict[str, Any]]:
        return []

class PgSearchService:
    def __init__(self, conn):
        self._conn = conn
    def search(self, query: str, k: int = 10) -> List[dict[str, Any]]:
        # Placeholder – riktig implementation kan använda pg/pgvector senare.
        return []

_service_singleton: Optional[object] = None

def get_search_service():
    """Returnera singleton för söktjänst med säkert fallback-beteende."""
    global _service_singleton
    if _service_singleton is not None:
        return _service_singleton
    conn = _connect()
    _service_singleton = PgSearchService(conn) if conn is not None else NullSearchService()
    return _service_singleton
