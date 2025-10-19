from __future__ import annotations

from uuid import uuid4

from app.search.service import search_hybrid
from app.search.vector_index import VectorResult
from app.settings import settings


def test_hybrid_rrf_combines_ft_and_vector(monkeypatch, stub_index) -> None:
    first_id = uuid4()
    second_id = uuid4()
    third_id = uuid4()

    stub_index.upsert(
        object_id=first_id,
        kind="note",
        source_ref="doc-1",
        payload={"title": "First"},
        embedding=[1.0, 0.0],
        model=settings.embed_model,
    )
    stub_index.upsert(
        object_id=second_id,
        kind="note",
        source_ref="doc-2",
        payload={"title": "Second"},
        embedding=[0.0, 1.0],
        model=settings.embed_model,
    )
    stub_index.upsert(
        object_id=third_id,
        kind="note",
        source_ref="doc-3",
        payload={"title": "Third"},
        embedding=[0.5, 0.5],
        model=settings.embed_model,
    )

    def fake_ft(query_text: str, *, k: int) -> list[VectorResult]:
        return [
            VectorResult(object_id=first_id, score=0.9, payload=stub_index.store[first_id].payload),
            VectorResult(object_id=third_id, score=0.6, payload=stub_index.store[third_id].payload),
        ]

    monkeypatch.setattr("app.search.service.search_full_text", fake_ft)

    results = search_hybrid("alpha", [0.0, 1.0], k=2)

    assert len(results) == 2
    assert results[0].object_id == first_id
    assert results[1].object_id == third_id
