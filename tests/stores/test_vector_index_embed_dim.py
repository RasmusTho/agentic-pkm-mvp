from __future__ import annotations

import pytest

from app.stores.memory import MemoryVectorIndex


def test_vector_index_upsert_rejects_dim_mismatch(monkeypatch) -> None:
    monkeypatch.setenv("EMBED_DIM", "4")
    idx = MemoryVectorIndex()
    with pytest.raises(ValueError, match=r"dim mismatch"):
        idx.upsert(
            object_id=__import__("uuid").uuid4(),
            kind="note",
            source_ref="unit-test",
            payload={"text": "a"},
            embedding=[1.0, 0.0, 0.0],
            model="test",
        )


def test_vector_index_search_rejects_dim_mismatch(monkeypatch) -> None:
    monkeypatch.setenv("EMBED_DIM", "4")
    idx = MemoryVectorIndex()
    oid = __import__("uuid").uuid4()
    idx.upsert(
        object_id=oid,
        kind="note",
        source_ref="unit-test",
        payload={"text": "a"},
        embedding=[1.0, 0.0, 0.0, 0.0],
        model="test",
    )
    with pytest.raises(ValueError, match=r"query embedding dim mismatch"):
        idx.search([1.0, 0.0, 0.0], k=1)
