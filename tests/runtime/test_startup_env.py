from __future__ import annotations

from app.runtime.startup_env import validate_llm_env


def test_mock_provider_requires_no_endpoints() -> None:
    env = {"LLM_PROVIDER": "mock", "LLM_MODEL": "mock-model"}
    result = validate_llm_env(env)
    assert result["ok"] is True
    assert result["missing_any_of"] == []
    assert result["missing_all_of"] == []


def test_ollama_provider_accepts_ollama_url_only() -> None:
    env = {
        "LLM_PROVIDER": "ollama",
        "LLM_MODEL": "llama3.1:8b",
        "OLLAMA_URL": "http://ollama:11434",
    }
    result = validate_llm_env(env)
    assert result["ok"] is True


def test_ollama_provider_accepts_openai_base_url_only() -> None:
    env = {
        "LLM_PROVIDER": "ollama",
        "LLM_MODEL": "llama3.1:8b",
        "OPENAI_BASE_URL": "http://ollama:11434/v1",
    }
    result = validate_llm_env(env)
    assert result["ok"] is True


def test_ollama_provider_requires_any_endpoint() -> None:
    env = {"LLM_PROVIDER": "ollama", "LLM_MODEL": "llama3.1:8b"}
    result = validate_llm_env(env)
    assert result["ok"] is False
    assert result["missing_any_of"] == [["OLLAMA_URL", "OPENAI_BASE_URL"]]


def test_openai_provider_requires_openai_base_url() -> None:
    env = {"LLM_PROVIDER": "openai", "LLM_MODEL": "gpt-4.1"}
    result = validate_llm_env(env)
    assert result["ok"] is False
    assert result["missing_all_of"] == ["OPENAI_BASE_URL"]


def test_missing_llm_model_fails() -> None:
    env = {"LLM_PROVIDER": "mock"}
    result = validate_llm_env(env)
    assert result["ok"] is False
    assert "LLM_MODEL" in result["missing_all_of"]
