from __future__ import annotations

import pytest

from app.retrieval import hybrid
from app.search.service import search_hybrid


def _vec(*head: float) -> list[float]:
    return list(head) + [0.0] * (8 - len(head))


@pytest.fixture
def _canonical_corpus():
    store = hybrid.get_store()
    snapshot = [
        {
            "doc_id": d.doc_id,
            "text": d.text,
            "language": d.language,
            "source_ref": d.source_ref,
            "payload": d.payload,
            "embedding": d.embedding,
        }
        for d in store.all()
    ]
    store.set_documents(
        [
            {"doc_id": "first", "text": "alpha first note", "payload": {"title": "First"}, "embedding": _vec(1.0, 0.0)},
            {"doc_id": "second", "text": "unrelated second note", "payload": {"title": "Second"}, "embedding": _vec(0.0, 1.0)},
            {"doc_id": "third", "text": "alpha third note", "payload": {"title": "Third"}, "embedding": _vec(0.5, 0.5)},
        ]
    )
    yield
    store.set_documents(snapshot)


def test_hybrid_rrf_combines_ft_and_vector(monkeypatch, _canonical_corpus) -> None:
    """Legacy ``search_hybrid`` fuses lexical and vector signals via the canonical ranking (#5707).

    It no longer returns full-text hits first: the vector-only doc competes with the lexical hits,
    and the order and scores are exactly the canonical entrypoint's.
    """
    monkeypatch.delenv("ASK_DOMAIN_SCOPE", raising=False)
    qvec = _vec(0.0, 1.0)

    results = search_hybrid("alpha", qvec, k=2)
    canonical = hybrid.hybrid_search("alpha", k=2, query_vector=qvec)

    assert [r.object_id for r in results] == [hit["doc_id"] for hit in canonical]
    assert "second" in [r.object_id for r in results]
    assert [r.score for r in results] == [hit["score"] for hit in canonical]
    assert [r.payload for r in results] == [hit["payload"] for hit in canonical]
