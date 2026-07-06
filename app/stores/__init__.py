from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from functools import lru_cache
from typing import Literal, Tuple

from app.db.dsn import resolve_dsn

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


def _require_pg_reachable(dsn: str) -> None:
    """Raise when the configured Postgres DSN cannot be reached.

    Fail-loud contract (KERNEL-03 / audit invariant I-S4): a configured but
    unreachable database must never silently degrade to a volatile in-memory
    store.
    """
    normalized = resolve_dsn(dsn)
    if not normalized:
        raise RuntimeError(
            "Store backend resolution failed: the configured Postgres DSN is empty "
            "after normalization. Fix DATABASE_URL/DB_DSN or set STORE_BACKEND explicitly."
        )
    try:
        import psycopg

        conn = psycopg.connect(normalized, connect_timeout=1)
        conn.close()
    except Exception as exc:
        logger.error("Postgres configured but unreachable during store resolution: %s", exc)
        raise RuntimeError(
            "Store backend resolution failed: Postgres is configured "
            "(DATABASE_URL/DB_DSN) but unreachable. Refusing to fall back to a "
            f"volatile in-memory store. Underlying error: {exc}"
        ) from exc


def _resolve_backend() -> str:
    global _LAST_RESOLVED_BACKEND
    override = os.getenv("STORE_BACKEND")
    normalized_override = (override or "").strip().lower()
    dsn = resolve_dsn()
    if normalized_override:
        # Fail-loud contract (KERNEL-03 / I-S4): validate the override at the
        # resolution seam so a typo'd backend ('postgres', 'pgvector') raises
        # here — never a silent memory route, and never a bogus label reported
        # by resolve_store_backend() consumers (e.g. index-rebuild receipts).
        if normalized_override not in {"memory", "pg"}:
            raise RuntimeError(
                f"Store backend '{normalized_override}' is not supported: set STORE_BACKEND "
                "to 'pg' or 'memory' (explicit opt-in to volatile state), or unset it to "
                "resolve from DATABASE_URL/DB_DSN."
            )
        _LAST_RESOLVED_BACKEND = (normalized_override, dsn, normalized_override)
        return normalized_override

    if not dsn:
        raise RuntimeError(
            "No store backend configured: set STORE_BACKEND=memory explicitly for the "
            "volatile in-memory backend, or configure DATABASE_URL/DB_DSN for Postgres."
        )

    _require_pg_reachable(dsn)
    _LAST_RESOLVED_BACKEND = (normalized_override, dsn, "pg")
    return "pg"


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
    dsn = resolve_dsn()
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


def reset_memory_store_backend() -> None:
    """Drop only the in-process MEMORY store singletons (object/vector/relation).

    DB-SAFE: unlike ``reset_store_backends``, this never calls
    ``truncate_pg_tables`` and never touches any Postgres backend, so it is safe
    to call from a production code path even when a real DB is reachable. It only
    clears the ``lru_cache`` holding the in-memory instances so the next
    ``get_vector_index()`` / ``get_object_store()`` builds a fresh memory store
    with no leaked embedding identity from an earlier occupant of the same
    interpreter (see ``app/cli/smoke.py`` — the smoke commands seed their own
    corpus into a fresh in-memory store and must not inherit an ambient
    singleton's identity).
    """
    try:
        _memory_instances.cache_clear()
    except Exception:
        pass
