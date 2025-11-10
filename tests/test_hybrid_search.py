from __future__ import annotations

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
