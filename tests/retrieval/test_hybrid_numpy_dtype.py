from __future__ import annotations

import numpy as np

from app.retrieval import hybrid


def test_rrf_ranking_dtype_stable(monkeypatch) -> None:
    monkeypatch.delenv("ASK_DOMAIN_SCOPE", raising=False)

    store = hybrid.get_store()
    store.set_documents(
        [
            {"doc_id": "alpha", "text": "alpha retrieval vector"},
            {"doc_id": "beta", "text": "alpha retrieval archive"},
            {"doc_id": "gamma", "text": "gamma unrelated"},
        ]
    )
    try:
        store._embeddings = np.array(  # noqa: SLF001 - issue #2120 guards this math path directly.
            [
                [1.0, 0.0, 0.0],
                [0.82, 0.18, 0.0],
                [0.0, 1.0, 0.0],
            ],
            dtype=np.float32,
        )
        store._emb_norms = np.linalg.norm(store._embeddings, axis=1)  # noqa: SLF001

        query_vector = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        bm25_scores = store.bm25_scores(["alpha", "retrieval"])
        embedding_scores = store.embedding_scores(query_vector)
        bm25_norm = hybrid._normalize(bm25_scores)  # noqa: SLF001
        embedding_norm = hybrid._normalize(embedding_scores)  # noqa: SLF001
        overlap_bonus = np.array([1.0, 1.0, 0.0], dtype=np.float32)
        combined = 0.5 * bm25_norm + 0.4 * embedding_norm + 0.1 * overlap_bonus

        assert bm25_scores.dtype == np.float32
        assert embedding_scores.dtype == np.float32
        assert bm25_norm.dtype == np.float32
        assert embedding_norm.dtype == np.float32
        assert combined.dtype == np.float32
        assert np.argsort(-combined).tolist() == [0, 1, 2]

        results = hybrid.hybrid_search("alpha retrieval", k=3, query_vector=query_vector.tolist())

        assert [hit["doc_id"] for hit in results] == ["alpha", "beta", "gamma"]
    finally:
        store.set_documents([])
