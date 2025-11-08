from __future__ import annotations

import os
from functools import lru_cache
from typing import Tuple

from app.settings import settings

from .base import ObjectStore, RelationIndex, VectorIndex
from .memory import MemoryObjectStore, MemoryRelationIndex, MemoryVectorIndex


def _resolve_backend() -> str:
    override = os.getenv("STORE_BACKEND")
    if override:
        return override.lower()
    return getattr(settings, "store_backend", "memory").lower()


@lru_cache(maxsize=1)
def _memory_instances() -> Tuple[ObjectStore, VectorIndex, RelationIndex]:
    return (MemoryObjectStore(), MemoryVectorIndex(), MemoryRelationIndex())


@lru_cache(maxsize=1)
def _pg_instances() -> Tuple[ObjectStore, VectorIndex, RelationIndex]:
    from .pg import PgObjectStore, PgVectorIndex, PgRelationIndex

    return (PgObjectStore(), PgVectorIndex(), PgRelationIndex())


def _store_instances() -> Tuple[ObjectStore, VectorIndex, RelationIndex]:
    backend = _resolve_backend()
    if backend == "memory":
        return _memory_instances()
    if backend == "pg":
        return _pg_instances()
    raise RuntimeError(f"Store backend '{backend}' is not supported yet")


def get_object_store() -> ObjectStore:
    return _store_instances()[0]


def get_vector_index() -> VectorIndex:
    return _store_instances()[1]


def get_relation_index() -> RelationIndex:
    return _store_instances()[2]


def reset_store_backends() -> None:
    for cache in (_memory_instances, _pg_instances):
        try:
            cache.cache_clear()
        except Exception:
            pass
    try:
        from .pg import truncate_pg_tables

        truncate_pg_tables()
    except Exception:
        pass
