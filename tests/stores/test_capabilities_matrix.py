from __future__ import annotations

import pytest

from app.stores.memory import MemoryObjectStore, MemoryRelationIndex, MemoryVectorIndex

try:
    from app.stores.pg import PgObjectStore, PgRelationIndex, PgVectorIndex, pg_available
except Exception:  # pragma: no cover - optional dependency
    PgObjectStore = PgVectorIndex = PgRelationIndex = None  # type: ignore
    pg_available = lambda: False  # type: ignore


CONTRACTS = {
    "ObjectStore": ("get", "put", "list_by_kind"),
    "VectorIndex": ("upsert", "search"),
    "RelationIndex": ("link", "neighbors", "has_any"),
}


def _assert_methods(obj, methods):
    for method in methods:
        assert hasattr(obj, method), f"{obj.__class__.__name__} missing {method}"


def test_memory_store_capabilities() -> None:
    _assert_methods(MemoryObjectStore(), CONTRACTS["ObjectStore"])
    _assert_methods(MemoryVectorIndex(), CONTRACTS["VectorIndex"])
    _assert_methods(MemoryRelationIndex(), CONTRACTS["RelationIndex"])


@pytest.mark.skipif(PgObjectStore is None or not pg_available(), reason="Postgres backend not available")
def test_pg_store_capabilities() -> None:
    assert PgObjectStore is not None
    assert PgVectorIndex is not None
    assert PgRelationIndex is not None
    _assert_methods(PgObjectStore(), CONTRACTS["ObjectStore"])
    _assert_methods(PgVectorIndex(), CONTRACTS["VectorIndex"])
    _assert_methods(PgRelationIndex(), CONTRACTS["RelationIndex"])
