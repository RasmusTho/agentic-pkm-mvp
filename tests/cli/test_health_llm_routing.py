from __future__ import annotations

import importlib
from types import SimpleNamespace

from app.config import llm as llm_config
from app.settings.models import LLMRoutingSettings, SettingsBundle

health_module = importlib.import_module("app.cli.health")


def test_health_llm_router_reports_route_policies(monkeypatch) -> None:
    monkeypatch.setattr("app.config.llm._ACTIVE_PROVIDER", None)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MODEL", "llama3.1:8b")
    monkeypatch.setenv("EMBED_MODEL", "nomic-embed-text:latest")
    monkeypatch.setattr(llm_config, "_ACTIVE_PROVIDER", None)

    result = health_module._check_llm_router()

    assert result["ok"] is True
    assert "selected_defaults" in result
    assert "route_policies" in result
    assert result["route_policies"]["embed"]["effective"]["provider"] == "ollama"
    assert result["route_policies"]["embed"]["policy"]["require_compatible_identity"] is True


def test_health_llm_router_includes_configured_task_routes(monkeypatch) -> None:
    bundle = SettingsBundle(
        llm_routing=LLMRoutingSettings(
            tasks={
                "qa": LLMRoutingSettings.TaskPolicy(
                    primary=LLMRoutingSettings.RouteTarget(provider="openai", model="gpt-5.4-mini")
                )
            }
        )
    )
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: bundle)
    monkeypatch.setattr(llm_config, "_ACTIVE_PROVIDER", None)

    result = health_module._check_llm_router()

    assert "qa" in result["route_policies"]
    assert result["route_policies"]["qa"]["effective"]["provider"] == "openai"


def test_health_route_projection_preserves_reasoning_effort(monkeypatch) -> None:
    bundle = SettingsBundle(
        llm_routing=LLMRoutingSettings(
            tasks={
                "qa": LLMRoutingSettings.TaskPolicy(
                    primary=LLMRoutingSettings.RouteTarget(
                        provider="openai",
                        model="gpt-6-luna",
                        transport_id="codex_cli_tailscale",
                        reasoning_effort="high",
                    )
                )
            }
        )
    )
    seen: dict[str, str | None] = {}

    def _provider_env_check(provider, model, **kwargs):
        if model == "gpt-6-luna":
            seen["provider"] = provider
            seen["reasoning_effort"] = kwargs.get("reasoning_effort")
        return {"ok": True, "detail": "preflight passed", "status": "ok"}

    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: bundle)
    monkeypatch.setattr(llm_config, "_ACTIVE_PROVIDER", None)
    monkeypatch.setattr(health_module, "_provider_env_check", _provider_env_check)

    route_check = health_module._check_llm_router()
    qa_route = route_check["route_policies"]["qa"]["effective"]
    assert qa_route["reasoning_effort"] == "high"

    result = health_module._check_llm_task_routes(route_check)

    assert result["routes"]["qa"]["status"] == "ok"
    assert seen == {"provider": "openai", "reasoning_effort": "high"}


def test_provider_env_check_accepts_openai_base_url(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_BASE", raising=False)

    result = health_module._provider_env_check("openai", "gpt-5.4-mini")

    assert result["ok"] is True
    assert result["status"] == "ok"


def test_provider_env_check_openai_base_still_accepted(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_BASE", "https://api.example.invalid/v1/chat/completions")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    result = health_module._provider_env_check("openai", "gpt-5.4-mini")

    assert result["ok"] is True


def test_health_task_routes_fail_when_effective_model_missing(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_BASE", "https://api.example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    result = health_module._check_llm_task_routes(
        {
            "route_policies": {
                "qa": {
                    "effective": {"provider": "openai", "model": ""},
                }
            }
        }
    )

    assert result["ok"] is False
    assert result["routes"]["qa"]["status"] == "fail"
    assert result["routes"]["qa"]["detail"] == "route model is missing"


def test_health_codex_transport_uses_remote_preflight_not_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    seen = {}

    class _Client:
        model_access_route = SimpleNamespace(
            provider="openai",
            model="gpt-6-luna",
            transport_id="codex_cli_tailscale",
            preflight_status="passed",
        )

        def chat(self, *_args, **_kwargs):
            raise AssertionError("health must never dispatch a completion")

    def _get_chat_client_for_route(intent, *, selected_route, allow_fallback):
        seen["intent"] = intent
        seen["route"] = selected_route
        seen["allow_fallback"] = allow_fallback
        return _Client()

    monkeypatch.setattr(
        health_module, "get_chat_client_for_route", _get_chat_client_for_route
    )

    result = health_module._check_llm_task_routes(
        {
            "route_policies": {
                "qa": {
                    "effective": {
                        "provider": "openai",
                        "model": "gpt-6-luna",
                        "transport_id": "codex_cli_tailscale",
                        "reasoning_effort": "low",
                    },
                    "intent": {"json_schema_required": False},
                }
            }
        }
    )

    assert result["ok"] is True
    route = result["routes"]["qa"]
    assert route["transport_id"] == "codex_cli_tailscale"
    assert route["status"] == "ok"
    assert route["preflight_status"] == "passed"
    assert seen["intent"].task_kind == "health"
    assert seen["route"].transport_id == "codex_cli_tailscale"
    assert seen["route"].model == "gpt-6-luna"
    assert seen["route"].timeout_seconds == health_module._health_probe_timeout()
    assert seen["allow_fallback"] is False
    assert "endpoint" not in route


def test_llm_access_fails_closed_on_selected_route_preflight(monkeypatch) -> None:
    class _Client:
        model_access_route = SimpleNamespace(
            provider="openai",
            model="gpt-6-luna",
            transport_id="codex_cli_tailscale",
            preflight_status="failed",
        )

        def chat(self, *_args, **_kwargs):
            raise AssertionError("health must never dispatch a completion")

    def _get_chat_client_for_route(intent, *, selected_route, allow_fallback):
        assert intent.task_kind == "health"
        assert selected_route.model == "gpt-6-luna"
        assert allow_fallback is False
        return _Client()

    def _unexpected_ollama_probe(**_kwargs):
        raise AssertionError("an unselected embedding Ollama route must not be probed")

    monkeypatch.setattr(
        health_module, "get_chat_client_for_route", _get_chat_client_for_route
    )
    monkeypatch.setattr(health_module, "_check_ollama", _unexpected_ollama_probe)

    result = health_module._check_llm_access(
        {
            "route_policies": {
                "qa": {
                    "effective": {
                        "provider": "openai",
                        "model": "gpt-6-luna",
                        "transport_id": "codex_cli_tailscale",
                    },
                    "intent": {},
                },
                "embed": {
                    "effective": {
                        "provider": "ollama",
                        "model": "nomic-embed-text",
                        "transport_id": "ollama_http",
                    },
                    "intent": {},
                },
            }
        }
    )

    assert result["ok"] is False
    assert set(result["routes"]) == {"qa"}
    assert result["routes"]["qa"]["status"] == "fail"


def test_provider_env_check_only_exposes_endpoint_origin(monkeypatch) -> None:
    endpoint = "https://operator:password@api.example.invalid/private/path?token=secret#fragment"
    monkeypatch.setenv("OPENAI_BASE_URL", endpoint)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    result = health_module._provider_env_check("openai", "gpt-5.4-mini")

    assert result["base_url"] == "https://api.example.invalid"
    assert all(secret not in repr(result) for secret in ("operator", "password", "private", "token", "secret", "fragment"))


def test_deepseek_health_only_exposes_endpoint_origin(monkeypatch) -> None:
    endpoint = "https://operator:password@api.example.invalid/private/path?token=secret#fragment"
    monkeypatch.setenv("DEEPSEEK_BASE", endpoint)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    result = health_module._provider_env_check("deepseek", "deepseek-chat")

    assert result["base_url"] == "https://api.example.invalid"
    assert all(secret not in repr(result) for secret in ("operator", "password", "private", "token", "secret", "fragment"))


def test_selected_ollama_route_is_probed_independent_of_legacy_provider(monkeypatch) -> None:
    calls: list[str] = []

    class _Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, list[dict[str, str]]]:
            return {"models": [{"name": "qwen-local"}]}

    def _get(url: str, *, timeout: float) -> _Response:
        calls.append(url)
        assert timeout == health_module._health_probe_timeout()
        return _Response()

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.local:11434")
    monkeypatch.setattr(health_module.httpx, "get", _get)

    result = health_module._check_llm_access(
        {
            "route_policies": {
                "qa": {
                    "effective": {
                        "provider": "ollama",
                        "model": "qwen-local",
                        "transport_id": "ollama_http",
                    },
                    "intent": {},
                },
                "embed": {
                    "effective": {
                        "provider": "ollama",
                        "model": "nomic-embed-text",
                        "transport_id": "ollama_http",
                    },
                    "intent": {},
                },
            }
        }
    )

    assert result["ok"] is True
    assert set(result["routes"]) == {"qa"}
    assert result["routes"]["qa"]["provider"] == "ollama"
    assert calls == ["http://ollama.local:11434/api/tags"]


def test_skipped_eval_ollama_route_is_not_probed(monkeypatch) -> None:
    monkeypatch.setenv("EVAL_LLM_MODE", "skip")

    def _unexpected_ollama_probe(**_kwargs):
        raise AssertionError("a skipped eval route must not probe Ollama")

    monkeypatch.setattr(health_module, "_check_ollama", _unexpected_ollama_probe)

    result = health_module._check_llm_access(
        {
            "route_policies": {
                "qa": {
                    "effective": {
                        "provider": "mock",
                        "model": "deterministic",
                        "transport_id": "mock",
                    },
                    "intent": {},
                },
                "eval": {
                    "effective": {
                        "provider": "ollama",
                        "model": "qwen-local",
                        "transport_id": "ollama_http",
                    },
                    "intent": {},
                },
            }
        }
    )

    assert result["ok"] is True
    assert result["routes"]["eval"]["status"] == "skipped"
