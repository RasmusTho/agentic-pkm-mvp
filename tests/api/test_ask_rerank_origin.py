from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import ask as ask_module
from app.retrieval.hybrid import get_store


def _stub_embeddings(monkeypatch) -> None:
    monkeypatch.setattr("app.index.embeddings.embed_texts", lambda texts, **_kwargs: [[0.1, 0.1, 0.1] for _ in texts])
    monkeypatch.setattr("app.index.embeddings.embed_text", lambda text, **_kwargs: [0.1, 0.1, 0.1])
    monkeypatch.setattr("app.retrieval.hybrid.embed_text", lambda text, language=None: [0.1, 0.1, 0.1])

    def _fake_embed_batches(gen):
        docs = list(gen)
        yield [[0.1, 0.1, 0.1] for _ in docs]

    monkeypatch.setattr("app.retrieval.hybrid.embed_batches", _fake_embed_batches)


def test_rerank_prefers_vault_origin(monkeypatch) -> None:
    _stub_embeddings(monkeypatch)
    hybrid = get_store()
    hybrid.set_documents(
        [
            {
                "doc_id": "vault-1",
                "text": "Vault note about rerank preference and scoring origin boost.",
                "source_ref": "vault/path",
                "payload": {"origin": "vault", "title": "Vault Note"},
            },
            {
                "doc_id": "external-1",
                "text": "External article about rerank preference and scoring origin boost.",
                "source_ref": "external/path",
                "payload": {"origin": "external_article", "title": "External Article"},
            },
        ]
    )
    ask_module._HYBRID_WARMED = True
    client = TestClient(app)
    try:
        resp = client.post("/api/ask", json={"question": "rerank preference"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["sources"], "Expected at least one source"
        assert data["sources"][0]["origin"] == "vault"
        assert "vault note" in data["answer"].lower()
    finally:
        hybrid.set_documents([])
        ask_module._HYBRID_WARMED = False


def test_rerank_ignores_payload_zone(monkeypatch) -> None:
    """Zone should not be read from payload; it is derived, not stored artifact truth."""
    _stub_embeddings(monkeypatch)
    hybrid = get_store()
    hybrid.set_documents(
        [
            {
                "doc_id": "hot-1",
                "text": "Hot zone note sharing equal base relevance.",
                "source_ref": "hot/path",
                "payload": {"origin": "external_article", "zone": "hot", "title": "Hot Note"},
            },
            {
                "doc_id": "cold-1",
                "text": "Cold zone note sharing equal base relevance.",
                "source_ref": "cold/path",
                "payload": {"origin": "external_article", "zone": "cold", "title": "Cold Note"},
            },
        ]
    )
    ask_module._HYBRID_WARMED = True
    client = TestClient(app)
    try:
        resp = client.post("/api/ask", json={"question": "equal base relevance"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["sources"], "Expected at least one source"
        # Zone should not be read from payload; all sources should have zone=None
        for source in data["sources"]:
            assert source.get("zone") is None, "Zone should not be derived from artifact payload"
    finally:
        hybrid.set_documents([])
        ask_module._HYBRID_WARMED = False
