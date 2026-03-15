from __future__ import annotations

import os

import pytest

from app.eval.llm_client import build_deepeval_model, configure_eval_openai_env


def test_build_deepeval_model_constructs_without_network(monkeypatch) -> None:
    monkeypatch.setenv("EVAL_LLM_MODE", "skip")
    monkeypatch.setenv("EVAL_LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("EVAL_LLM_API_KEY", "sk-local")
    monkeypatch.setenv("EVAL_LLM_MODEL", "llama3.1:8b")
    cfg = configure_eval_openai_env()
    try:
        model = build_deepeval_model(cfg)
    except (ImportError, RuntimeError):
        pytest.skip("deepeval model wrapper unavailable")
    assert model is not None
    # ensure base_url propagates
    assert getattr(model, "base_url", None) or os.getenv("OPENAI_BASE_URL")


def test_configure_eval_openai_env_allows_skip_mode_without_credentials(monkeypatch) -> None:
    monkeypatch.setenv("EVAL_LLM_MODE", "skip")
    monkeypatch.delenv("EVAL_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("EVAL_LLM_API_KEY", raising=False)
    monkeypatch.delenv("EVAL_LLM_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    cfg = configure_eval_openai_env()

    assert cfg.mode == "skip"
    assert cfg.base_url == ""
    assert cfg.api_key == ""
    assert cfg.model == ""
