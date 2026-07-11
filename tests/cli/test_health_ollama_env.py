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
    assert result["base_url"] == "http://ollama.local:11434/v1"


def test_health_ollama_check_uses_dedicated_probe_timeout_not_llm_timeout(monkeypatch) -> None:
    """
    _check_ollama MUST use HEALTH_PROBE_TIMEOUT, never LLM_TIMEOUT.

    LLM_TIMEOUT is provisioned for real LLM generation (60-120s elsewhere in
    the codebase); reusing it for the health probe let a single unreachable
    ollama block the event loop for that long (2026-07-11 prod outage).
    """
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_URL", "http://ollama.local:11434")
    monkeypatch.setenv("LLM_TIMEOUT", "120")  # generation timeout — must be ignored here
    monkeypatch.delenv("HEALTH_PROBE_TIMEOUT", raising=False)

    seen_timeout = {}

    class DummyResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return {"models": []}

    def fake_get(url: str, timeout: float) -> DummyResponse:
        seen_timeout["value"] = timeout
        return DummyResponse()

    monkeypatch.setattr(health_module.httpx, "get", fake_get)

    health_module._check_ollama()

    assert seen_timeout["value"] == 2.0  # HEALTH_PROBE_TIMEOUT default, not LLM_TIMEOUT=120

    monkeypatch.setenv("HEALTH_PROBE_TIMEOUT", "0.5")
    health_module._check_ollama()
    assert seen_timeout["value"] == 0.5


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
