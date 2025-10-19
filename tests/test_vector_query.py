from __future__ import annotations

from uuid import uuid4

from app.search.service import search_vector
from app.settings import settings


def test_vector_query_returns_closest_match(stub_index) -> None:
    a_id = uuid4()
    b_id = uuid4()
    stub_index.upsert(
        object_id=a_id,
        kind="note",
        source_ref="A",
        payload={"title": "Doc A"},
        embedding=[1.0, 0.0, 0.0],
        model=settings.embed_model,
    )
    stub_index.upsert(
        object_id=b_id,
        kind="note",
        source_ref="B",
        payload={"title": "Doc B"},
        embedding=[0.0, 1.0, 0.0],
        model=settings.embed_model,
    )

    results = search_vector([0.9, 0.1, 0.0], k=1)
    assert results
    assert results[0].object_id == a_id
    assert results[0].payload["title"] == "Doc A"
