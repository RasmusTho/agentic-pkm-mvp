from __future__ import annotations

import pytest

from app.retrieval.hybrid import get_store, hybrid_search


def test_hybrid_search_ranks_expected_doc(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    store = get_store()
    store.set_documents(
        [
            {"doc_id": "doc-alpha", "text": "Alpha beta gamma delta", "source_ref": "alpha.md"},
            {"doc_id": "doc-beta", "text": "Completely unrelated text"},
            {"doc_id": "doc-gamma", "text": "Alpha token only once"},
        ]
    )
    results = hybrid_search("alpha beta", k=3)
    assert results
    assert results[0]["doc_id"] == "doc-alpha"
    assert 0.0 <= results[0]["score"] <= 1.0
    assert results[0]["snippet"]

def test_hybrid_search_fails_on_dimension_mismatch(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    def _fake_embed_batches(texts, batch_size=32):
        rows = [[0.1, 0.2, 0.3, 0.4] for _ in texts]
        yield rows

    def _fake_embed_text(text, language=None):
        return [0.9, 0.9]

    monkeypatch.setattr("app.retrieval.hybrid.embed_batches", _fake_embed_batches)
    monkeypatch.setattr("app.retrieval.hybrid.embed_text", _fake_embed_text)
    store = get_store()
    store.set_documents([{"doc_id": "doc-1", "text": "alpha beta"}])
    try:
        with pytest.raises(ValueError):
            hybrid_search("alpha")
    finally:
        store.set_documents([])
