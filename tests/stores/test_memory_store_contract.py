from __future__ import annotations

from uuid import uuid4

import math
import pytest

from app.components.embeddings import EmbeddingIdentity
from app.stores.memory import MemoryObjectStore, MemoryVectorIndex, MemoryRelationIndex

def _test_identity(dim: int = 4) -> EmbeddingIdentity:
    return EmbeddingIdentity(provider="test", model="memory-test", dim=dim)



def test_memory_object_store_roundtrip() -> None:
    store = MemoryObjectStore()
    oid = uuid4()
    payload = {"text": "alpha", "content": "alpha"}
    store.put(oid, kind="note", source_ref="unit-test", payload=payload)

    stored = store.get(oid)
    assert stored is not None
    assert stored["payload"]["text"] == "alpha"

    listing = list(store.list_by_kind("note"))
    assert listing and listing[0]["object_id"] == oid


def test_memory_vector_index_search_order(monkeypatch) -> None:
    monkeypatch.setenv("EMBED_DIM", "4")

    idx = MemoryVectorIndex()
    oid_a = uuid4()
    oid_b = uuid4()
    idx.upsert(
        object_id=oid_a,
        kind="note",
        source_ref="unit-test",
        payload={"text": "a"},
        embedding=[1.0, 0.0, 0.0, 0.0],
        model="memory-test",
        identity=_test_identity(),
    )
    idx.upsert(
        object_id=oid_b,
        kind="note",
        source_ref="unit-test",
        payload={"text": "b"},
        embedding=[0.5, 0.5, 0.0, 0.0],
        model="memory-test",
        identity=_test_identity(),
    )

    hits = idx.search([1.0, 0.0, 0.0, 0.0], k=2, identity=_test_identity())
    assert hits and hits[0].object_id == oid_a
    assert hits[1].object_id == oid_b


def test_memory_relation_index_neighbors_unique_order() -> None:
    rel = MemoryRelationIndex()
    src = uuid4()
    dst_a = uuid4()
    dst_b = uuid4()
    rel.link(src, dst_a, rel="related_to")
    rel.link(src, dst_b, rel="related_to")
    rel.link(src, dst_a, rel="related_to")  # duplicate ignored

    assert rel.neighbors(src, rel="related_to") == [dst_a, dst_b]


def test_memory_relation_index_has_any() -> None:
    rel = MemoryRelationIndex()
    src = uuid4()
    dst = uuid4()
    rel.link(src, dst, rel="supports")
    assert rel.has_any(src) is True
    assert rel.has_any(dst) is True
    assert rel.has_any(uuid4()) is False


def test_memory_vector_index_rejects_mixed_dimensions(monkeypatch) -> None:
    monkeypatch.setenv("EMBED_DIM", "4")
    idx = MemoryVectorIndex()
    first = uuid4()
    idx.upsert(
        object_id=first,
        kind="note",
        source_ref="unit-test",
        payload={"text": "one"},
        embedding=[1.0, 0.0, 0.0, 0.0],
        model="memory-test",
        identity=_test_identity(),
    )
    with pytest.raises(ValueError):
        idx.upsert(
            object_id=uuid4(),
            kind="note",
            source_ref="unit-test",
            payload={"text": "two"},
            embedding=[0.5, 0.5, 0.5],
            model="memory-test",
            identity=_test_identity(),
        )


def test_memory_vector_index_query_dim_mismatch(monkeypatch) -> None:
    monkeypatch.setenv("EMBED_DIM", "4")
    idx = MemoryVectorIndex()
    oid = uuid4()
    idx.upsert(
        object_id=oid,
        kind="note",
        source_ref="unit-test",
        payload={"text": "alpha"},
        embedding=[1.0, 0.0, 0.0, 0.0],
        model="memory-test",
        identity=_test_identity(),
    )
    monkeypatch.setenv("EMBED_DIM", "3")
    with pytest.raises(ValueError):
        idx.search([1.0, 0.0, 0.0], k=1, identity=_test_identity())


def test_memory_vector_index_identity_mismatch(monkeypatch) -> None:
    monkeypatch.setenv("EMBED_DIM", "4")
    idx = MemoryVectorIndex()
    identity_a = EmbeddingIdentity(provider="alpha", model="memory-test", dim=4)
    idx.upsert(
        object_id=uuid4(),
        kind="note",
        source_ref="unit-test",
        payload={"text": "alpha"},
        embedding=[1.0, 0.0, 0.0, 0.0],
        model=identity_a.model,
        identity=identity_a,
    )
    with pytest.raises(ValueError):
        identity_b = EmbeddingIdentity(provider="beta", model="memory-test", dim=4)
        idx.upsert(
            object_id=uuid4(),
            kind="note",
            source_ref="unit-test",
            payload={"text": "beta"},
            embedding=[0.5, 0.5, 0.0, 0.0],
            model=identity_b.model,
            identity=identity_b,
        )


def test_memory_vector_index_identity_mismatch_on_search(monkeypatch) -> None:
    monkeypatch.setenv("EMBED_DIM", "4")
    idx = MemoryVectorIndex()
    identity = EmbeddingIdentity(provider="alpha", model="memory-test", dim=4)
    idx.upsert(
        object_id=uuid4(),
        kind="note",
        source_ref="unit-test",
        payload={"text": "alpha"},
        embedding=[1.0, 0.0, 0.0, 0.0],
        model=identity.model,
        identity=identity,
    )
    with pytest.raises(ValueError):
        bad_identity = EmbeddingIdentity(provider="beta", model="memory-test", dim=4)
        idx.search([1.0, 0.0, 0.0, 0.0], k=1, identity=bad_identity)


def test_memory_vector_index_unit_norm_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("EMBED_DIM", "3")
    idx = MemoryVectorIndex()
    identity = EmbeddingIdentity(provider="unit", model="memory-test", dim=3, normalize=True)
    oid = uuid4()
    idx.upsert(
        object_id=oid,
        kind="note",
        source_ref="unit-test",
        payload={"text": "alpha"},
        embedding=[3.0, 0.0, 0.0],
        model=identity.model,
        identity=identity,
    )
    entry = idx._entries[oid]
    norm = math.sqrt(sum((float(v) * float(v)) for v in entry.embedding))
    assert math.isclose(norm, 1.0, rel_tol=1e-6)


def test_memory_vector_index_preserves_magnitude_when_not_normalized(monkeypatch) -> None:
    monkeypatch.setenv("EMBED_DIM", "2")
    idx = MemoryVectorIndex()
    identity = EmbeddingIdentity(provider="raw", model="memory-test", dim=2, normalize=False)
    strong = uuid4()
    idx.upsert(
        object_id=strong,
        kind="note",
        source_ref="unit-test",
        payload={"text": "strong"},
        embedding=[2.0, 0.0],
        model=identity.model,
        identity=identity,
    )
    weak = uuid4()
    idx.upsert(
        object_id=weak,
        kind="note",
        source_ref="unit-test",
        payload={"text": "weak"},
        embedding=[1.0, 0.0],
        model=identity.model,
        identity=identity,
    )
    hits = idx.search([1.0, 0.0], k=2, identity=identity)
    assert [hit.object_id for hit in hits] == [strong, weak]


