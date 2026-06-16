from __future__ import annotations

import pytest

from app.services import llm as llm_service
from app.services.llm import LLMError, _deterministic_llm_response, call_llm


def test_ollama_provider_error_does_not_return_canned_response(monkeypatch, clean_llm_env) -> None:
    """A real-provider (ollama) HTTP error/timeout must propagate, never resolve
    to the canned deterministic blob.

    Masking a provider error with ``_deterministic_llm_response()`` manufactures
    a false-green ASK synthesis receipt and defeats the fail-loud promotion
    caution (#2108 / #1997 / #1999).
    """
    clean_llm_env.setenv("LLM_PROVIDER", "ollama")
    clean_llm_env.setenv("LLM_PROVIDER_ENFORCE", "1")
    clean_llm_env.setenv("LLM_MODEL", "llama3.1:8b")
    clean_llm_env.setenv("OLLAMA_URL", "http://127.0.0.1:11434")
    clean_llm_env.delenv("LLM_MOCK_RESPONSE", raising=False)
    # Keep the retry backoff instant for the test.
    monkeypatch.setattr(llm_service, "_DEFAULT_BASE_DELAY", 0.0)
    monkeypatch.setattr(llm_service, "_DEFAULT_MAX_RETRIES", 1)

    def _boom(*args, **kwargs):
        raise RuntimeError("ollama http 404: model 'gpt-4.1-mini' not found")

    monkeypatch.setattr(llm_service, "_ollama_chat", _boom)

    with pytest.raises(LLMError):
        call_llm("ask", {"system": "s", "user": "u"}, kind="ask.answer")


def test_deterministic_stub_confined_to_mock(monkeypatch, clean_llm_env) -> None:
    """Deterministic stub responses are reachable only when provider == 'mock'.

    A real provider returns its own output (success) or raises (failure); it is
    never silently replaced by the canned blob.
    """
    canned = _deterministic_llm_response()

    # provider == mock → the deterministic stub IS the response.
    clean_llm_env.setenv("LLM_PROVIDER", "mock")
    clean_llm_env.delenv("LLM_MOCK_RESPONSE", raising=False)
    mock_result = call_llm("decide", {"system": "s", "user": "u"}, kind="agent.decide")
    assert mock_result.strip() == canned.strip()

    # provider == ollama (real) with a successful call → the real output, never
    # the canned stub.
    clean_llm_env.setenv("LLM_PROVIDER", "ollama")
    clean_llm_env.setenv("LLM_MODEL", "llama3.1:8b")
    clean_llm_env.setenv("OLLAMA_URL", "http://127.0.0.1:11434")
    monkeypatch.setattr(llm_service, "_ollama_chat", lambda *a, **k: "a real generated answer")
    real_result = call_llm("ask", {"system": "s", "user": "u"}, kind="ask.answer")
    assert real_result == "a real generated answer"
    assert real_result.strip() != canned.strip()
