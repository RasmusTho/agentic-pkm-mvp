from __future__ import annotations

from app.cli import llm_doctor


def test_llm_doctor_ollama_prefers_ollama_url(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_URL", "http://ollama:11434/")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://openai.local/v1")

    base, provider = llm_doctor._resolve_endpoint()

    assert base == "http://ollama:11434"
    assert provider == "ollama"


def test_llm_doctor_ollama_falls_back_to_openai(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://openai.local/v1/")

    base, provider = llm_doctor._resolve_endpoint()

    assert base == "http://openai.local/v1"
    assert provider == "openai_compat"


def test_llm_doctor_non_ollama_prefers_openai_base(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OLLAMA_URL", "http://ollama:11434/")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://openai.local/v1/")

    base, provider = llm_doctor._resolve_endpoint()

    assert base == "http://openai.local/v1"
    assert provider == "openai_compat"


def test_llm_doctor_mock_short_circuits(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("OLLAMA_URL", "http://ollama:11434/")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://openai.local/v1/")

    def _boom(*_args, **_kwargs):
        raise AssertionError("_ping_endpoint should not be called for mock provider")

    monkeypatch.setattr(llm_doctor, "_ping_endpoint", _boom)

    result = llm_doctor.run_llm_check()

    assert result["ok"] is True
    assert result["provider"] == "mock"
    assert result["error"] is None
