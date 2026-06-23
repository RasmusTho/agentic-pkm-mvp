from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from functools import lru_cache
from typing import Literal, Tuple

from app.db.dsn import resolve_dsn
from app.settings import settings

from .base import ObjectStore, RelationIndex, VectorIndex
from .memory import MemoryObjectStore, MemoryRelationIndex, MemoryVectorIndex

logger = logging.getLogger(__name__)

StoreClassification = Literal["durable", "rebuildable"]

_OBJECT_STORE_REBUILD_SOURCE = "vault notes + companion notes via vault ingest/runtime projection"
_LAST_RESOLVED_BACKEND: tuple[str, str, str] | None = None


@dataclass(frozen=True)
class StorePortBinding:
    name: str
    backend: str
    store: ObjectStore
    classification: StoreClassification
    rebuild_source: str
    owner_subsystem: str = "PDM"
    contract: str = "StorePort"


def _pg_reachable(dsn: str) -> bool:
    if not dsn:
        return False
    normalized = resolve_dsn(dsn)
    if not normalized:
        return False
    try:
        import psycopg

        conn = psycopg.connect(normalized, connect_timeout=1)
        conn.close()
        return True
    except Exception as exc:
        logger.warning("Postgres unreachable during store auto-detect: %s", exc)
        return False


def _resolve_backend() -> str:
    global _LAST_RESOLVED_BACKEND
    override = os.getenv("STORE_BACKEND")
    normalized_override = (override or "").strip().lower()
    dsn = os.getenv("DATABASE_URL", "").strip()
    if override:
        _LAST_RESOLVED_BACKEND = (normalized_override, dsn, normalized_override)
        return normalized_override

    if _pg_reachable(dsn):
        _LAST_RESOLVED_BACKEND = (normalized_override, dsn, "pg")
        return "pg"

    backend = getattr(settings, "store_backend", "memory").lower()
    _LAST_RESOLVED_BACKEND = (normalized_override, dsn, backend)
    return backend


@lru_cache(maxsize=1)
def _memory_instances() -> Tuple[ObjectStore, VectorIndex, RelationIndex]:
    return (MemoryObjectStore(), MemoryVectorIndex(), MemoryRelationIndex())


@lru_cache(maxsize=1)
def _pg_instances() -> Tuple[ObjectStore, VectorIndex, RelationIndex]:
    from .pg import PgObjectStore, PgVectorIndex, PgRelationIndex

    return (PgObjectStore(), PgVectorIndex(), PgRelationIndex())


def _store_instances_for_backend(backend: str) -> Tuple[ObjectStore, VectorIndex, RelationIndex]:
    if backend == "memory":
        return _memory_instances()
    if backend == "pg":
        return _pg_instances()
    raise RuntimeError(f"Store backend '{backend}' is not supported yet")


def _store_instances() -> Tuple[ObjectStore, VectorIndex, RelationIndex]:
    return _store_instances_for_backend(_resolve_backend())


def resolve_store_backend() -> str:
    return _resolve_backend()


def resolved_store_backend_hint() -> str | None:
    """Return the current store backend only if it is already known without probing."""
    override = (os.getenv("STORE_BACKEND") or "").strip().lower()
    dsn = os.getenv("DATABASE_URL", "").strip()
    if _LAST_RESOLVED_BACKEND is None:
        return None
    cached_override, cached_dsn, backend = _LAST_RESOLVED_BACKEND
    if (cached_override, cached_dsn) != (override, dsn):
        return None
    return backend


def get_object_store() -> ObjectStore:
    return _store_instances()[0]


def resolve_object_store_port() -> StorePortBinding:
    """Resolve the current object-store binding through the PDM StorePort seam."""
    backend = _resolve_backend()
    store = _store_instances_for_backend(backend)[0]
    rebuild_source = str(getattr(store, "rebuild_source", _OBJECT_STORE_REBUILD_SOURCE))
    return StorePortBinding(
        name="object_store",
        backend=backend,
        store=store,
        classification="rebuildable",
        rebuild_source=rebuild_source,
    )


def get_vector_index() -> VectorIndex:
    return _store_instances()[1]


def get_relation_index() -> RelationIndex:
    return _store_instances()[2]


def reset_store_backends() -> None:
    global _LAST_RESOLVED_BACKEND
    _LAST_RESOLVED_BACKEND = None
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
