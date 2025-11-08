from __future__ import annotations

from uuid import uuid4

from app.stores.memory import MemoryObjectStore, MemoryVectorIndex, MemoryRelationIndex


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


def test_memory_vector_index_search_order() -> None:
    idx = MemoryVectorIndex()
    oid_a = uuid4()
    oid_b = uuid4()
    idx.upsert(
        object_id=oid_a,
        kind="note",
        source_ref="unit-test",
        payload={"text": "a"},
        embedding=[1.0, 0.0, 0.0, 0.0],
        model="test",
    )
    idx.upsert(
        object_id=oid_b,
        kind="note",
        source_ref="unit-test",
        payload={"text": "b"},
        embedding=[0.5, 0.5, 0.0, 0.0],
        model="test",
    )

    hits = idx.search([1.0, 0.0, 0.0, 0.0], k=2)
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
