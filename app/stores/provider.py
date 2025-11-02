from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional, Tuple

import psycopg

from .memory import MemoryObjects, MemoryDecisions
from .postgres import PgObjects, PgDecisions
from .base import ObjectsStore, DecisionsStore


def _dsn() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return ""
    return url.replace("+psycopg", "")


@lru_cache(maxsize=8)
def _resolved_backend(explicit: Optional[str], dsn: str) -> str:
    if explicit:
        return explicit.lower()

    if not dsn:
        return "memory"

    try:
        conn = psycopg.connect(dsn, connect_timeout=1)
    except Exception:
        return "memory"
    else:
        conn.close()
        return "pg"


def get_stores() -> Tuple[ObjectsStore, DecisionsStore]:
    backend = _resolved_backend(os.getenv("STORE_BACKEND"), _dsn())
    if backend == "pg":
        return PgObjects(), PgDecisions()
    return MemoryObjects(), MemoryDecisions()
