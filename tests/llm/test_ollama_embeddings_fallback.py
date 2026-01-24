from __future__ import annotations

import httpx
import pytest

from app.llm import embeddings


def _make_payload_response(url: str, status_code: int, payload: dict) -> httpx.Response:
    return httpx.Response(status_code, json=payload, request=httpx.Request("POST", url))


def test_ollama_embed_payload_includes_text_and_dimensions(monkeypatch) -> None:
    called: list[dict] = []

    def fake_post(url: str, **kwargs) -> httpx.Response:
        called.append({"url": url, "json": kwargs.get("json")})
        return _make_payload_response(url, 200, {"embeddings": [[0.1, -0.1, 0.2, 0.3]]})

    monkeypatch.setattr(httpx, "post", fake_post)
    vector = embeddings.embed_text("payload-test", provider="ollama", model="test", dim=4, normalize=False)
    assert len(called) == 1
    assert called[0]["json"]["prompt"] == "payload-test"
    assert called[0]["json"]["dimensions"] == 4
    assert vector == [0.1, -0.1, 0.2, 0.3]


def test_ollama_embed_dimensions_flag(monkeypatch) -> None:
    called: list[dict] = []

    def fake_post(url: str, **kwargs) -> httpx.Response:
        called.append({"url": url, "json": kwargs.get("json")})
        return _make_payload_response(url, 200, {"embeddings": [[0.1, -0.1, 0.2, 0.3]]})

    monkeypatch.setenv("OLLAMA_EMBED_DIMENSIONS", "0")
    monkeypatch.setattr(httpx, "post", fake_post)
    vector = embeddings.embed_text("payload-dim", provider="ollama", model="test", dim=4, normalize=False)
    assert "dimensions" not in called[0]["json"]
    assert vector == [0.1, -0.1, 0.2, 0.3]


def test_ollama_embed_fallback_on_error(monkeypatch) -> None:
    def fake_post(url: str, **kwargs) -> httpx.Response:
        if url.endswith("/api/embeddings"):
            request = httpx.Request("POST", url)
            raise httpx.HTTPStatusError("error", request=request, response=httpx.Response(500, request=request))
        return _make_payload_response(url, 200, {"data": [{"embedding": [0.2, 0.4, -0.1, 0.0]}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    vector = embeddings.embed_text("fallback-test", provider="ollama", model="test", dim=4, normalize=False)
    assert vector == [0.2, 0.4, -0.1, 0.0]


def test_ollama_embed_dim_mismatch_raises(monkeypatch) -> None:
    def fake_post(url: str, **kwargs) -> httpx.Response:
        return _make_payload_response(url, 200, {"embeddings": [[0.1, 0.2]]})

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(ValueError) as excinfo:
        embeddings.embed_text("dim-mismatch", provider="ollama", model="test", dim=4, normalize=False)
    assert "expected_dim=4" in str(excinfo.value)


def test_ollama_embed_reports_http_errors(monkeypatch) -> None:
    def fake_post(url: str, **kwargs) -> httpx.Response:
        request = httpx.Request("POST", url)
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("not found", request=request, response=response)

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(RuntimeError) as excinfo:
        embeddings.embed_text("missing", provider="ollama", model="test", dim=4, normalize=False)
    message = str(excinfo.value)
    assert "Ollama embedding requests failed" in message
    assert "Primary error" in message
    assert "fallback" in message
