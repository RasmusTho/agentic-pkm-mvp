from __future__ import annotations

import importlib

health_module = importlib.import_module("app.cli.health")


def test_health_ollama_check_accepts_openai_base_url(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://ollama.local:11434/v1")

    class DummyResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return {"models": [{"name": "llama3.1:8b"}]}

    def fake_get(url: str, timeout: float) -> DummyResponse:
        assert url == "http://ollama.local:11434/v1/api/tags"
        assert timeout == 2.0
        return DummyResponse()

    monkeypatch.setattr(health_module.httpx, "get", fake_get)

    result = health_module._check_ollama()

    assert result["ok"] is True
    assert result["provider"] == "ollama"
    assert result["base_url"] == "http://ollama.local:11434"


def test_health_ollama_output_redacts_url_credentials_query_and_path(monkeypatch) -> None:
    raw_url = "http://user:password@ollama.local:11434/private/path?token=secret"
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", raw_url)

    class DummyResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return {"models": []}

    def fake_get(url: str, timeout: float) -> DummyResponse:
        assert url == f"{raw_url}/api/tags"
        return DummyResponse()

    monkeypatch.setattr(health_module.httpx, "get", fake_get)

    result = health_module._check_ollama()

    assert result["base_url"] == "http://ollama.local:11434"
    assert "password" not in str(result)
    assert "secret" not in str(result)
    assert "/private/path" not in str(result)


def test_health_ollama_check_does_not_default_to_ollama(monkeypatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    result = health_module._check_ollama()

    assert result["ok"] is True
    assert result["data"]["skipped"] is True
    assert result["provider"] == ""
