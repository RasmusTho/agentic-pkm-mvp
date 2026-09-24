from __future__ import annotations

import json
import sys
import types

from pydantic import BaseModel
import pytest

from app.eval import llm_client
from app.eval.llm_client import (
    EvalLLMConfig,
    build_deepeval_model,
    build_ragas_model,
    configure_eval_openai_env,
)
from app.components.llm.router import LLMRouteError


def test_configure_eval_route_uses_shared_product_client(monkeypatch) -> None:
    calls = []

    class _Client:
        route = types.SimpleNamespace(model="gpt-6-luna")

    client = _Client()
    monkeypatch.setenv("EVAL_LLM_MODE", "run")
    monkeypatch.setenv("EVAL_LLM_MODEL", "llama3.1:8b")
    monkeypatch.setenv("EVAL_LLM_BASE_URL", "http://eval-only.local/v1")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://openai-fallback.local/v1")
    monkeypatch.setenv("EVAL_LLM_API_KEY", "eval-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "fallback-secret")

    def _get_chat_client(intent, **kwargs):
        calls.append((intent, kwargs))
        return client

    monkeypatch.setattr(llm_client, "get_chat_client", _get_chat_client)

    cfg = configure_eval_openai_env()

    assert len(calls) == 1
    intent, kwargs = calls[0]
    assert intent.task_kind == "eval"
    assert kwargs["model_id"] == "llama3.1:8b"
    runtime = kwargs["adapter_runtime_config"]
    assert runtime.base_url == "http://eval-only.local/v1"
    assert runtime.api_key == "eval-secret"
    assert cfg.chat_client is client
    assert cfg.model == "gpt-6-luna"
    assert cfg.base_url == "http://eval-only.local/v1"
    assert cfg.api_key == "eval-secret"
    assert "eval-secret" not in repr(cfg)
    assert "eval-only.local" not in repr(cfg)


def test_eval_env_precedence_and_private_runtime_config(monkeypatch) -> None:
    captured = {}
    client = type("Client", (), {"route": types.SimpleNamespace(model="llama3.1:8b")})()
    monkeypatch.setenv("EVAL_LLM_MODE", "run")
    monkeypatch.setenv("EVAL_LLM_MODEL", "llama3.1:8b")
    monkeypatch.delenv("EVAL_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("EVAL_LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://fallback.local/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "fallback-secret")

    def _get_chat_client(intent, **kwargs):
        captured.update(kwargs)
        captured["intent"] = intent
        return client

    monkeypatch.setattr(llm_client, "get_chat_client", _get_chat_client)
    cfg = configure_eval_openai_env()

    runtime = captured["adapter_runtime_config"]
    assert runtime.base_url == "http://fallback.local/v1"
    assert runtime.api_key == "fallback-secret"
    assert captured["intent"].task_kind == "eval"
    assert cfg.base_url == "http://fallback.local/v1"
    assert cfg.api_key == "fallback-secret"
    assert "fallback-secret" not in repr(runtime)


def test_eval_explicit_empty_key_does_not_fall_back_to_openai_key(monkeypatch) -> None:
    captured = {}
    client = type("Client", (), {"route": types.SimpleNamespace(model="llama3.1:8b")})()
    monkeypatch.setenv("EVAL_LLM_MODE", "run")
    monkeypatch.setenv("EVAL_LLM_MODEL", "llama3.1:8b")
    monkeypatch.setenv("EVAL_LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("EVAL_LLM_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-win")

    def _get_chat_client(_intent, **kwargs):
        captured.update(kwargs)
        return client

    monkeypatch.setattr(llm_client, "get_chat_client", _get_chat_client)
    configure_eval_openai_env()

    assert captured["adapter_runtime_config"].api_key == ""


def test_eval_rejects_undeclared_exact_model(monkeypatch) -> None:
    monkeypatch.setenv("EVAL_LLM_MODE", "run")
    monkeypatch.setenv("EVAL_LLM_MODEL", "not-in-product-registry")

    with pytest.raises(LLMRouteError, match="declared Product chat model"):
        configure_eval_openai_env()


def test_eval_conflicting_force_fails_before_preflight(monkeypatch) -> None:
    monkeypatch.setenv("EVAL_LLM_MODE", "run")
    monkeypatch.setenv("EVAL_LLM_MODEL", "llama3.1:8b")
    monkeypatch.setenv("LLM_FORCE_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FORCE_MODEL", "gpt-5.4")
    monkeypatch.delenv("LLM_PROVIDER_ENFORCE", raising=False)
    monkeypatch.setattr(
        "app.components.llm.fabric.CodexRemoteTransport",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("preflight started")),
    )

    with pytest.raises(LLMRouteError, match="conflicts with active global route enforcement"):
        configure_eval_openai_env()


def test_eval_skip_mode_needs_no_credentials_or_route(monkeypatch) -> None:
    monkeypatch.setenv("EVAL_LLM_MODE", "skip")
    monkeypatch.delenv("EVAL_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("EVAL_LLM_API_KEY", raising=False)
    monkeypatch.delenv("EVAL_LLM_MODEL", raising=False)
    monkeypatch.setattr(
        llm_client,
        "get_chat_client",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("route resolved")),
    )

    cfg = configure_eval_openai_env()

    assert cfg.mode == "skip"
    assert cfg.base_url == cfg.api_key == cfg.model == ""
    assert cfg.chat_client is None


def test_deepeval_wrapper_uses_chat_client_with_optional_schema(monkeypatch) -> None:
    modules = {
        "deepeval": types.ModuleType("deepeval"),
        "deepeval.models": types.ModuleType("deepeval.models"),
        "deepeval.models.base_model": types.ModuleType("deepeval.models.base_model"),
    }

    class _DeepEvalBaseLLM:
        def __init__(self):
            self.model = self.load_model()

    modules["deepeval.models.base_model"].DeepEvalBaseLLM = _DeepEvalBaseLLM
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    class _Reply(BaseModel):
        verdict: str

    class _Client:
        route = types.SimpleNamespace(model="gpt-6-luna")

        def __init__(self):
            self.calls = []

        def chat(self, name, pack, **kwargs):
            self.calls.append((name, pack, kwargs))
            return json.dumps({"verdict": "pass"})

    client = _Client()
    model = build_deepeval_model(
        EvalLLMConfig(model="gpt-6-luna", mode="run", chat_client=client)
    )

    assert model.get_model_name() == "gpt-6-luna"
    assert model.model is client
    assert model.generate("evaluate", schema=_Reply).verdict == "pass"
    name, pack, kwargs = client.calls[0]
    assert name == "eval"
    assert pack["user"] == "evaluate"
    assert kwargs["response_format"]["properties"]["verdict"]["type"] == "string"


def test_ragas_wrapper_uses_shared_chat_client() -> None:
    class _Client:
        route = types.SimpleNamespace(model="gpt-6-luna")

        def chat(self, name, pack, **kwargs):
            assert name == "eval"
            assert pack["user"] == "judge this"
            return "pass"

    model = build_ragas_model(
        EvalLLMConfig(model="gpt-6-luna", mode="run", chat_client=_Client())
    )

    assert model.invoke("judge this") == "pass"
    assert model._identifying_params == {"model": "gpt-6-luna"}
