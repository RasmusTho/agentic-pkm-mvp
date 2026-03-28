from __future__ import annotations

import importlib

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
