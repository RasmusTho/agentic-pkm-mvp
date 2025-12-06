from __future__ import annotations

import os

from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import ask as ask_module
from app.retrieval.hybrid import get_store


def _stub_embeddings(monkeypatch) -> None:
    monkeypatch.setattr("app.index.embeddings.embed_texts", lambda texts: [[0.1, 0.1, 0.1] for _ in texts])
    monkeypatch.setattr("app.index.embeddings.embed_text", lambda text: [0.1, 0.1, 0.1])
    monkeypatch.setattr("app.retrieval.hybrid.embed_text", lambda text, language=None: [0.1, 0.1, 0.1])

    def _fake_embed_batches(gen):
        docs = list(gen)
        yield [[0.1, 0.1, 0.1] for _ in docs]

    monkeypatch.setattr("app.retrieval.hybrid.embed_batches", _fake_embed_batches)


def test_ask_uses_llm_when_enabled(monkeypatch) -> None:
    _stub_embeddings(monkeypatch)
    monkeypatch.setenv("REASONING_ENABLE", "1")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("REASONING_PROVIDER", "mock")
    hybrid = get_store()
    hybrid.set_documents(
        [
            {
                "doc_id": "vault-llm",
                "text": "Vault note about llm composed answers and hot bias.",
                "source_ref": "vault/path",
                "payload": {"origin": "vault", "zone": "hot", "title": "Vault LLM"},
            },
            {
                "doc_id": "external-llm",
                "text": "External document also about llm composed answers.",
                "source_ref": "external/path",
                "payload": {"origin": "external_article", "title": "External LLM"},
            },
        ]
    )
    ask_module._HYBRID_WARMED = True
    client = TestClient(app)
    try:
        resp = client.post("/api/ask", json={"question": "llm composed answers"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["sources"], "Expected sources from hybrid store"
        assert "MOCK_ASK_ANSWER" in data["answer"]
        assert len(data["sources"]) <= 10
    finally:
        hybrid.set_documents([])
        ask_module._HYBRID_WARMED = False
        os.environ.pop("REASONING_ENABLE", None)
        os.environ.pop("LLM_PROVIDER", None)
        os.environ.pop("REASONING_PROVIDER", None)


def test_ask_falls_back_when_reasoning_disabled(monkeypatch) -> None:
    _stub_embeddings(monkeypatch)
    os.environ.pop("REASONING_ENABLE", None)
    hybrid = get_store()
    hybrid.set_documents(
        [
            {
                "doc_id": "vault-fallback",
                "text": "Vault fallback snippet should be used when llm is off.",
                "source_ref": "vault/path",
                "payload": {"origin": "vault", "zone": "hot", "title": "Vault Fallback"},
            },
            {
                "doc_id": "external-fallback",
                "text": "External doc should not override vault when llm is off.",
                "source_ref": "external/path",
                "payload": {"origin": "external_article", "title": "External Fallback"},
            },
        ]
    )
    ask_module._HYBRID_WARMED = True
    client = TestClient(app)
    try:
        resp = client.post("/api/ask", json={"question": "fallback snippet"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["sources"], "Expected sources from hybrid store"
        assert "mock_ask_answer" not in data["answer"].lower()
        assert "vault fallback snippet" in data["answer"].lower()
    finally:
        hybrid.set_documents([])
        ask_module._HYBRID_WARMED = False


def test_ask_no_hits_returns_empty_sources(monkeypatch) -> None:
    _stub_embeddings(monkeypatch)
    hybrid = get_store()
    hybrid.set_documents([])
    ask_module._HYBRID_WARMED = True
    client = TestClient(app)
    try:
        resp = client.post("/api/ask", json={"question": "no hits expected"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["answer"] == "No results found."
        assert data["sources"] == []
    finally:
        ask_module._HYBRID_WARMED = False
