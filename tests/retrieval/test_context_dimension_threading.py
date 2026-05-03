from __future__ import annotations

from app.retrieval.hybrid import get_store, hybrid_search


def _patch_embeddings(monkeypatch) -> None:
    monkeypatch.setattr("app.retrieval.hybrid.embed_text", lambda text, language=None: [0.1, 0.1, 0.1])
    monkeypatch.setattr("app.retrieval.hybrid.embed_docs", lambda texts: ([[0.1, 0.1, 0.1] for _ in texts], {}))


def test_scope_flows_through_retrieval_unchanged(monkeypatch) -> None:
    _patch_embeddings(monkeypatch)
    calls: list[str] = []

    monkeypatch.setattr("app.retrieval.hybrid._resolve_domain_scope", lambda: "work")

    def _tracking_doc_in_scope(doc, scope: str) -> bool:
        calls.append(scope)
        return bool(doc.payload and doc.payload.get("domain") == scope)

    monkeypatch.setattr("app.retrieval.hybrid._doc_in_scope", _tracking_doc_in_scope)

    store = get_store()
    store.set_documents(
        [
            {"doc_id": "a", "text": "alpha", "payload": {"domain": "work"}},
            {"doc_id": "b", "text": "beta", "payload": {"domain": "personal"}},
        ]
    )
    try:
        hits = hybrid_search("alpha", k=5)
        assert [h["doc_id"] for h in hits] == ["a"]
        assert calls
        assert set(calls) == {"work"}
    finally:
        store.set_documents([])
