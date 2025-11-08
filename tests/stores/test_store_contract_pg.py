from __future__ import annotations

import os
from uuid import uuid4

import pytest
import psycopg

from app.db.dsn import resolve_dsn
from app.stores import reset_store_backends, get_object_store, get_vector_index, get_relation_index

BACKENDS = [
    pytest.param("memory", id="memory"),
    pytest.param("pg", id="pg"),
]


def _pg_available() -> bool:
    url = resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")
    try:
        conn = psycopg.connect(url, connect_timeout=1)
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _reset_between_tests():
    reset_store_backends()
    yield
    reset_store_backends()


@pytest.mark.parametrize("backend", BACKENDS)
def test_object_store_roundtrip(monkeypatch, backend):
    if backend == "pg" and not _pg_available():
        pytest.skip("Postgres backend not available")
    monkeypatch.setenv("STORE_BACKEND", backend)
    store = get_object_store()
    oid = uuid4()
    store.put(oid, kind="note", source_ref="unit-test", payload={"text": "alpha", "content": "alpha"})
    rec = store.get(oid)
    assert rec and rec["object_id"] == oid
    xs = list(store.list_by_kind("note", limit=1))
    assert xs and xs[0]["object_id"] == oid


@pytest.mark.parametrize("backend", BACKENDS)
def test_vector_index_search_order(monkeypatch, backend):
    if backend == "pg" and not _pg_available():
        pytest.skip("Postgres backend not available")
    monkeypatch.setenv("STORE_BACKEND", backend)
    idx = get_vector_index()
    a, b = uuid4(), uuid4()
    idx.upsert(object_id=a, kind="note", source_ref="unit-test", payload={"text": "a"}, embedding=[1, 0, 0, 0], model="test")
    idx.upsert(object_id=b, kind="note", source_ref="unit-test", payload={"text": "b"}, embedding=[0.5, 0.5, 0, 0], model="test")
    hits = idx.search([1, 0, 0, 0], k=2)
    assert [h.object_id for h in hits] == [a, b]


@pytest.mark.parametrize("backend", BACKENDS)
def test_relation_neighbors_unique_order(monkeypatch, backend):
    if backend == "pg" and not _pg_available():
        pytest.skip("Postgres backend not available")
    monkeypatch.setenv("STORE_BACKEND", backend)
    rel = get_relation_index()
    src = uuid4()
    a = uuid4()
    b = uuid4()
    rel.link(src, a, rel="related_to")
    rel.link(src, b, rel="related_to")
    rel.link(src, a, rel="related_to")
    assert rel.neighbors(src, rel="related_to") == [a, b]
