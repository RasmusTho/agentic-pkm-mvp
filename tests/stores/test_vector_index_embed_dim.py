from __future__ import annotations

import pytest

from app.components.embeddings import EmbeddingIdentity
from app.stores.memory import MemoryVectorIndex

IDENTITY = EmbeddingIdentity(provider="test", model="memory-test", dim=4)


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
            model=IDENTITY.model,
            identity=IDENTITY,
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
        model=IDENTITY.model,
        identity=IDENTITY,
    )
    with pytest.raises(ValueError, match=r"query embedding dim mismatch"):
        idx.search([1.0, 0.0, 0.0], k=1, identity=IDENTITY)
