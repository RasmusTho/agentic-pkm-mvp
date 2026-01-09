from __future__ import annotations

import os
import httpx
import pytest

from app.llm import embeddings


@pytest.fixture(autouse=True)
def ensure_embed_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_URL", "http://ollama.test")
    monkeypatch.setenv("EMBED_DIM", "4")
    monkeypatch.delenv("OLLAMA_EMBED_DIMENSIONS", raising=False)



def _make_payload_response(url: str, status_code: int, payload: dict) -> httpx.Response:
    return httpx.Response(status_code, json=payload, request=httpx.Request("POST", url))


def test_ollama_embed_payload_uses_list(monkeypatch) -> None:
    called: list[dict] = []

    def fake_post(url: str, **kwargs) -> httpx.Response:
        called.append({"url": url, "json": kwargs.get("json")})
        return _make_payload_response(url, 200, {"embeddings": [[0.1, -0.1, 0.2, 0.3]]})

    monkeypatch.setattr(httpx, "post", fake_post)
    vector = embeddings.embed_text("payload-test", provider="ollama", model="test", dim=4, normalize=False)
    assert len(called) == 1
    assert called[0]["json"]["input"] == ["payload-test"]
    assert "dimensions" not in called[0]["json"]
    assert vector == [0.1, -0.1, 0.2, 0.3]


def test_ollama_embed_fallback_on_error(monkeypatch) -> None:
    responses = [
        _make_payload_response("http://ollama.test/api/embed", 500, {}),
        _make_payload_response("http://ollama.test/v1/embeddings", 200, {"data": [{"embedding": [0.2, 0.4, -0.1, 0.0]}]})
    ]

    def fake_post(url: str, **kwargs) -> httpx.Response:
        if not responses:
            raise RuntimeError("No more fake responses")
        return responses.pop(0)

    monkeypatch.setattr(httpx, "post", fake_post)
    vector = embeddings.embed_text("fallback-test", provider="ollama", model="test", dim=4, normalize=False)
    assert vector == [0.2, 0.4, -0.1, 0.0]
