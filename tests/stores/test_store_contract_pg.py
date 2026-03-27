from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest

from app.components.embeddings import EmbeddingIdentity
from app.db.dsn import resolve_dsn
from app.stores import reset_store_backends, get_object_store, get_vector_index, get_relation_index

TEST_PG_IDENTITY = EmbeddingIdentity(provider="test", model="pg-test", dim=4)

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
    if backend == "pg":
        monkeypatch.setenv("DATABASE_URL", resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app"))
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
    if backend == "pg":
        monkeypatch.setenv("DATABASE_URL", resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app"))
    monkeypatch.setenv("STORE_BACKEND", backend)
    monkeypatch.setenv("EMBED_DIM", "4")

    idx = get_vector_index()
    a, b = uuid4(), uuid4()
    idx.upsert(object_id=a, kind="note", source_ref="unit-test", payload={"text": "a"}, embedding=[1, 0, 0, 0], model=TEST_PG_IDENTITY.model, identity=TEST_PG_IDENTITY)
    idx.upsert(object_id=b, kind="note", source_ref="unit-test", payload={"text": "b"}, embedding=[0.5, 0.5, 0, 0], model=TEST_PG_IDENTITY.model, identity=TEST_PG_IDENTITY)
    hits = idx.search([1, 0, 0, 0], k=2, identity=TEST_PG_IDENTITY)
    assert [h.object_id for h in hits] == [a, b]


@pytest.mark.parametrize("backend", BACKENDS)
def test_relation_neighbors_unique_order(monkeypatch, backend):
    if backend == "pg" and not _pg_available():
        pytest.skip("Postgres backend not available")
    if backend == "pg":
        monkeypatch.setenv("DATABASE_URL", resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app"))
    monkeypatch.setenv("STORE_BACKEND", backend)
    rel = get_relation_index()
    src = uuid4()
    a = uuid4()
    b = uuid4()
    rel.link(src, a, rel="related_to")
    rel.link(src, b, rel="related_to")
    rel.link(src, a, rel="related_to")
    assert rel.neighbors(src, rel="related_to") == [a, b]


@pytest.mark.parametrize("backend", BACKENDS)
def test_relation_memberships_roundtrip_multi_value(monkeypatch, backend):
    if backend == "pg" and not _pg_available():
        pytest.skip("Postgres backend not available")
    if backend == "pg":
        monkeypatch.setenv("DATABASE_URL", resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app"))
    monkeypatch.setenv("STORE_BACKEND", backend)
    rel = get_relation_index()
    src = uuid4()

    rel.add_membership(src, rel="sphere_membership", value="work")
    rel.add_membership(src, rel="sphere_membership", value="creative", payload={"source": "test"})

    memberships = rel.memberships(src, rel="sphere_membership")
    assert [(entry.relation_type, entry.value) for entry in memberships] == [
        ("sphere_membership", "work"),
        ("sphere_membership", "creative"),
    ]
    assert memberships[1].payload == {"source": "test"}


@pytest.mark.parametrize("backend", BACKENDS)
def test_relation_memberships_are_optional_and_empty_by_default(monkeypatch, backend):
    if backend == "pg" and not _pg_available():
        pytest.skip("Postgres backend not available")
    if backend == "pg":
        monkeypatch.setenv("DATABASE_URL", resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app"))
    monkeypatch.setenv("STORE_BACKEND", backend)
    rel = get_relation_index()

    assert rel.memberships(uuid4(), rel="sphere_membership") == []


def test_pg_vector_index_query_dim_mismatch(monkeypatch):
    if not _pg_available():
        pytest.skip("Postgres backend not available")
    monkeypatch.setenv("DATABASE_URL", resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app"))
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("EMBED_DIM", "4")
    idx = get_vector_index()
    oid = uuid4()
    idx.upsert(object_id=oid, kind="note", source_ref="unit-test", payload={"text": "alpha"}, embedding=[1, 0, 0, 0], model=TEST_PG_IDENTITY.model, identity=TEST_PG_IDENTITY)
    monkeypatch.setenv("EMBED_DIM", "3")
    with pytest.raises(ValueError, match="dim mismatch"):
        idx.search([0.5, 0.5, 0.5], k=1, identity=TEST_PG_IDENTITY)


def test_pg_vector_index_detects_mixed_dims(monkeypatch):
    if not _pg_available():
        pytest.skip("Postgres backend not available")
    monkeypatch.setenv("DATABASE_URL", resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app"))
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("EMBED_DIM", "4")
    idx = get_vector_index()
    primary = uuid4()
    secondary = uuid4()
    idx.upsert(object_id=primary, kind="note", source_ref="unit-test", payload={"text": "alpha"}, embedding=[1, 0, 0, 0], model=TEST_PG_IDENTITY.model, identity=TEST_PG_IDENTITY)
    idx.upsert(object_id=secondary, kind="note", source_ref="unit-test", payload={"text": "beta"}, embedding=[0.5, 0.5, 0, 0], model=TEST_PG_IDENTITY.model, identity=TEST_PG_IDENTITY)
    url = resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE store_vector_index SET dim = %s WHERE object_id = %s", (8, secondary))
    with pytest.raises(RuntimeError, match="mixed embedding dimensions"):
        idx.search([1, 0, 0, 0], k=1, identity=TEST_PG_IDENTITY)


def test_pg_vector_index_identity_mismatch(monkeypatch):
    if not _pg_available():
        pytest.skip("Postgres backend not available")
    monkeypatch.setenv("DATABASE_URL", resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app"))
    monkeypatch.setenv("STORE_BACKEND", "pg")
    idx = get_vector_index()
    primary = uuid4()
    identity_a = EmbeddingIdentity(provider="provider-a", model="model-a", dim=4)
    idx.upsert(
        object_id=primary,
        kind="note",
        source_ref="unit-test",
        payload={"text": "alpha"},
        embedding=[1, 0, 0, 0],
        model=identity_a.model,
        identity=identity_a,
    )
    with pytest.raises(RuntimeError):
        identity_b = EmbeddingIdentity(provider="provider-b", model="model-b", dim=4)
        idx.upsert(
            object_id=uuid4(),
            kind="note",
            source_ref="unit-test",
            payload={"text": "beta"},
            embedding=[0.5, 0.5, 0, 0],
            model=identity_b.model,
            identity=identity_b,
        )
    with pytest.raises(RuntimeError):
        identity_c = EmbeddingIdentity(provider="provider-b", model="model-b", dim=4)
        idx.search([1, 0, 0, 0], k=1, identity=identity_c)
