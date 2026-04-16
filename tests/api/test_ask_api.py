from fastapi.testclient import TestClient

from app.api.app import app
from app.retrieval.hybrid import get_store


def test_ask_endpoint_returns_sources(monkeypatch):
    monkeypatch.setattr("app.index.embeddings.embed_texts", lambda texts, **_kwargs: [[0.1, 0.1, 0.1] for _ in texts])
    monkeypatch.setattr("app.index.embeddings.embed_text", lambda text, **_kwargs: [0.1, 0.1, 0.1])
    monkeypatch.setattr("app.retrieval.hybrid.embed_text", lambda text, language=None: [0.1, 0.1, 0.1])

    def _fake_embed_batches(gen):
        docs = list(gen)
        yield [[0.1, 0.1, 0.1] for _ in docs]

    monkeypatch.setattr("app.retrieval.hybrid.embed_batches", _fake_embed_batches)
    store = get_store()
    store.set_documents(
        [
            {"doc_id": "a1", "text": "This is a vault note about testing.", "source_ref": "vault/path"},
            {"doc_id": "b2", "text": "External reference document.", "source_ref": "external/path"},
        ]
    )
    client = TestClient(app)
    resp = client.post("/api/ask", json={"question": "testing"})
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("answer")
    assert isinstance(body.get("sources"), list)
    assert body["sources"]
    first = body["sources"][0]
    assert "uuid" in first


def test_ask_payload_without_zone_does_not_fail(monkeypatch):
    """Regression test: normal ingested artifacts without payload zone should not produce misleading behavior."""
    monkeypatch.setattr("app.index.embeddings.embed_texts", lambda texts, **_kwargs: [[0.1, 0.1, 0.1] for _ in texts])
    monkeypatch.setattr("app.index.embeddings.embed_text", lambda text, **_kwargs: [0.1, 0.1, 0.1])
    monkeypatch.setattr("app.retrieval.hybrid.embed_text", lambda text, language=None: [0.1, 0.1, 0.1])

    def _fake_embed_batches(gen):
        docs = list(gen)
        yield [[0.1, 0.1, 0.1] for _ in docs]

    monkeypatch.setattr("app.retrieval.hybrid.embed_batches", _fake_embed_batches)
    store = get_store()
    # Payloads without zone field (normal ingested artifacts)
    store.set_documents(
        [
            {
                "doc_id": "normal-1",
                "text": "Normal vault note without zone payload.",
                "source_ref": "vault/normal",
                "payload": {"origin": "vault", "title": "Normal Note", "trust": "own_raw"},
            },
            {
                "doc_id": "normal-2",
                "text": "Another normal note without zone.",
                "source_ref": "vault/another",
                "payload": {"origin": "vault", "title": "Another Note"},
            },
        ]
    )
    client = TestClient(app)
    resp = client.post("/api/ask", json={"question": "normal vault note"})
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("answer")
    assert isinstance(body.get("sources"), list)
    assert body["sources"]
    # Verify zone is not returned from payloads without zone field
    for source in body["sources"]:
        assert source.get("zone") is None, "Zone should not be derived from payload for normal artifacts"
