"""
Search facade for smoke/CI.

- Avoids importing Postgres-specific index on memory backend.
- Provides a NoopVectorIndex fallback so module import never fails in CI.
"""
from __future__ import annotations
import os
from typing import Any, List, Optional

# Default to None; conditionally set if backend is PG and deps exist.
PgVectorIndex: Optional[type] = None

if os.environ.get("STORE_BACKEND", "").lower() in ("pg", "postgres", "postgresql"):
    try:
        # Heavy import guarded for PG-only paths
        from .vector_index import PgVectorIndex  # type: ignore
    except Exception:
        PgVectorIndex = None  # keep import safe on CI

class NoopVectorIndex:
    """Minimal stub used by smoke/CI; keeps API surface without PG deps."""
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        return

    def upsert(self, *args: Any, **kwargs: Any) -> int:
        return 0

    def search(self, *args: Any, **kwargs: Any) -> List[dict]:
        return []

__all__ = ["PgVectorIndex", "NoopVectorIndex"]
