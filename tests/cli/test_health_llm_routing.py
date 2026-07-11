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


def test_check_llm_task_routes_reuses_precomputed_ollama_check(monkeypatch) -> None:
    """
    _check_llm_task_routes MUST reuse a precomputed ollama check instead of
    re-probing per ollama task-route.

    Regression for the 2026-07-11 prod outage: with N ollama-provider task
    routes, run_health() made 1 (top-level) + N (per-route) blocking httpx
    calls to Ollama, each up to HEALTH_PROBE_TIMEOUT seconds, serialized
    inside a single request. Reusing the top-level result caps it at 1 call
    regardless of how many task routes use ollama.
    """
    call_count = 0

    def _fake_check_ollama() -> dict:
        nonlocal call_count
        call_count += 1
        return {"ok": True, "detail": "Ollama nåddes (fake)", "provider": "ollama", "base_url": "http://fake"}

    monkeypatch.setattr(health_module, "_check_ollama", _fake_check_ollama)

    precomputed = health_module._check_ollama()  # the one call run_health() makes directly
    assert call_count == 1

    router_check = {
        "route_policies": {
            "embed": {"effective": {"provider": "ollama", "model": "nomic-embed-text:latest"}},
            "decide": {"effective": {"provider": "ollama", "model": "llama3.1:8b"}},
            "plan": {"effective": {"provider": "ollama", "model": "llama3.1:8b"}},
            "eval": {"effective": {"provider": "ollama", "model": "llama3.1:8b"}},
        }
    }
    monkeypatch.setenv("EVAL_LLM_MODE", "real")  # avoid the eval-skip branch

    result = health_module._check_llm_task_routes(router_check, ollama_check=precomputed)

    # No additional _check_ollama() calls beyond the one made before invoking
    # _check_llm_task_routes — the 4 ollama task routes above must all reuse
    # `precomputed` rather than re-probing.
    assert call_count == 1
    assert result["ok"] is True
    for task_kind in ("embed", "decide", "plan", "eval"):
        assert result["routes"][task_kind]["ok"] is True
