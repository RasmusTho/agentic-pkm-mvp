from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional, Tuple

import psycopg

from app.db.dsn import resolve_dsn

from .memory import MemoryObjects, MemoryDecisions
from .postgres import PgObjects, PgDecisions
from .base import ObjectsStore, DecisionsStore


def _dsn() -> str:
    return resolve_dsn()


_ALLOWED_BACKENDS = {"memory", "pg"}


@lru_cache(maxsize=8)
def _resolved_backend(explicit: Optional[str], dsn: str) -> str:
    if explicit and explicit.strip():
        normalized = explicit.strip().lower()
        # Fail-loud contract (KERNEL-03 / I-S4): an explicit but unknown backend
        # value must never silently route to the volatile in-memory store.
        if normalized not in _ALLOWED_BACKENDS:
            raise RuntimeError(
                f"Store backend '{normalized}' is not supported: set STORE_BACKEND to "
                "'pg' or 'memory' (explicit opt-in to volatile state), or unset it to "
                "resolve from DATABASE_URL/DB_DSN."
            )
        return normalized

    if not dsn:
        raise RuntimeError(
            "No store backend configured: set STORE_BACKEND=memory explicitly for the "
            "volatile in-memory backend, or configure DATABASE_URL/DB_DSN for Postgres."
        )

    # Fail-loud contract (KERNEL-03 / audit invariant I-S4): a configured but
    # unreachable database must never silently degrade to in-memory state.
    try:
        conn = psycopg.connect(dsn, connect_timeout=1)
    except Exception as exc:
        raise RuntimeError(
            "Store backend resolution failed: Postgres is configured "
            "(DATABASE_URL/DB_DSN) but unreachable. Refusing to fall back to a "
            f"volatile in-memory store. Underlying error: {exc}"
        ) from exc
    else:
        conn.close()
        return "pg"


def get_stores() -> Tuple[ObjectsStore, DecisionsStore]:
    backend = _resolved_backend(os.getenv("STORE_BACKEND"), _dsn())
    if backend == "pg":
        return PgObjects(), PgDecisions()
    return _memory_stores()

@lru_cache(maxsize=1)
def _memory_stores():
    # Återanvänd samma in-memory-instanser i processen
    return (MemoryObjects(), MemoryDecisions())

def reset_memory_stores() -> None:
    """Test-hjälpare: nollställ de cacheade in-memory-stores."""
    try:
        _memory_stores.cache_clear()
    except Exception:
        pass
