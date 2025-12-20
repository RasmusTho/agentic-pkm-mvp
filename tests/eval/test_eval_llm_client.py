from __future__ import annotations

import os

import pytest

from app.eval.llm_client import build_deepeval_model, configure_eval_openai_env


def test_build_deepeval_model_constructs_without_network(monkeypatch) -> None:
    monkeypatch.setenv("EVAL_LLM_MODE", "skip")
    cfg = configure_eval_openai_env()
    try:
        model = build_deepeval_model(cfg)
    except (ImportError, RuntimeError):
        pytest.skip("deepeval model wrapper unavailable")
    assert model is not None
    # ensure base_url propagates
    assert getattr(model, "base_url", None) or os.getenv("OPENAI_BASE_URL")
