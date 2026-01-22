from __future__ import annotations

from app.llm.embeddings import embed_text


def test_ollama_embedding_calls_native_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_HOST", "https://ollama.local:11434/")
    monkeypatch.setenv("EMBED_DIM", "3")
    monkeypatch.setenv("EMBED_MODEL", "nomic-embed-text:latest")

    monkeypatch.setattr("app.llm.embeddings.OLLAMA_URL", "https://ollama.local:11434")

    captured: dict[str, object] = {}

    class DummyResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return {"embeddings": [[1, 2, 3]]}

    def fake_post(url: str, json: dict[str, object], timeout: float) -> DummyResponse:
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr("app.llm.embeddings.httpx.post", fake_post)

    vector = embed_text("test input", normalize=False)

    assert vector == [1.0, 2.0, 3.0]
    assert captured["url"] == "https://ollama.local:11434/api/embeddings"
    assert captured["json"] == {
        "model": "nomic-embed-text:latest",
        "prompt": "test input",
        "dimensions": 3,
    }
    assert "input" not in captured["json"]
