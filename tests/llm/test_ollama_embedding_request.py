from __future__ import annotations

from app.llm.embeddings import embed_text


def test_ollama_embedding_calls_native_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_HOST", "https://ollama.local:11434/")
    monkeypatch.setenv("EMBED_DIM", "3")
    monkeypatch.setenv("EMBED_MODEL", "nomic-embed-text:latest")

    captured: dict[str, object] = {}

    class DummyResponse:
        is_error = False
        status_code = 200

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

    from app.llm.embeddings import _embed_single

    _embed_single.cache_clear()
    vector = embed_text("test input", provider="ollama", normalize=False)

    assert vector == [1.0, 2.0, 3.0]
    assert captured["url"] == "https://ollama.local:11434/api/embeddings"
    assert captured["json"] == {
        "model": "nomic-embed-text:latest",
        "prompt": "test input",
        "dimensions": 3,
    }
    assert "input" not in captured["json"]


def test_ollama_embedding_accepts_openai_base_url(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://ollama.local:11434/v1/")
    monkeypatch.setenv("EMBED_DIM", "3")
    monkeypatch.setenv("EMBED_MODEL", "nomic-embed-text:latest")

    captured: dict[str, object] = {}

    class DummyResponse:
        is_error = False
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return {"embeddings": [[1, 2, 3]]}

    def fake_post(url: str, json: dict[str, object], timeout: float) -> DummyResponse:
        captured["url"] = url
        return DummyResponse()

    monkeypatch.setattr("app.llm.embeddings.httpx.post", fake_post)

    from app.llm.embeddings import _embed_single

    _embed_single.cache_clear()
    vector = embed_text("test input", provider="ollama", normalize=False)

    assert vector == [1.0, 2.0, 3.0]
    assert captured["url"] == "https://ollama.local:11434/api/embeddings"
