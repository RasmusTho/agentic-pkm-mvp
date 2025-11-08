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
def _store_instances() -> Tuple[ObjectStore, VectorIndex, RelationIndex]:
    backend = _resolve_backend()
    if backend == "memory":
        return (MemoryObjectStore(), MemoryVectorIndex(), MemoryRelationIndex())
    raise RuntimeError(f"Store backend '{backend}' is not supported yet")


def get_object_store() -> ObjectStore:
    return _store_instances()[0]


def get_vector_index() -> VectorIndex:
    return _store_instances()[1]


def get_relation_index() -> RelationIndex:
    return _store_instances()[2]


def reset_store_backends() -> None:
    try:
        _store_instances.cache_clear()
    except Exception:
        pass
