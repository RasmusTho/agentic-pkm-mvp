from __future__ import annotations

import pytest

from app.components.llm.router import LLMRouteError, LLMRouter, LLMTaskIntent
from app.settings.models import LLMRoutingSettings, SettingsBundle


def _cloud_primary_local_fallback() -> LLMRoutingSettings.TaskPolicy:
    """Mirror the offline-host policy: cloud (openai/gpt-4.1-mini) primary with a
    local (ollama/llama3.1:8b) fallback — the real ``default_chat`` / ``tasks.qa``
    shape from runtime/settings/llm_routing.yaml."""
    return LLMRoutingSettings.TaskPolicy(
        primary=LLMRoutingSettings.RouteTarget(
            model_id="openai.chat.gpt_4_1_mini",
            provider="openai",
            model="gpt-4.1-mini",
        ),
        fallback=LLMRoutingSettings.FallbackPolicy(
            mode="local",
            model_id="ollama.chat.llama3_1_8b",
            provider="ollama",
            model="llama3.1:8b",
        ),
    )


@pytest.fixture
def cloud_primary_routing(monkeypatch: pytest.MonkeyPatch) -> SettingsBundle:
    routing = LLMRoutingSettings(
        default_chat=_cloud_primary_local_fallback(),
        tasks={"qa": _cloud_primary_local_fallback()},
    )
    bundle = SettingsBundle(llm_routing=routing)
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: bundle)
    return bundle


def test_enforced_provider_uses_compatible_fallback(clean_llm_env, cloud_primary_routing) -> None:
    """Under LLM_PROVIDER_ENFORCE=1 with provider=ollama, the ask/qa route must
    resolve to an Ollama-served model (llama3.1:8b), never the incoherent
    cross-provider ``ollama`` + ``gpt-4.1-mini`` that the host Ollama 404s
    (#2109).
    """
    clean_llm_env.setenv("LLM_PROVIDER", "ollama")
    clean_llm_env.setenv("LLM_PROVIDER_ENFORCE", "1")
    clean_llm_env.setenv("LLM_MODEL", "llama3.1:8b")
    clean_llm_env.setenv("EMBED_MODEL", "nomic-embed-text:latest")

    router = LLMRouter()
    for task_kind in ("ask", "qa"):
        route = router.route(LLMTaskIntent(task_kind=task_kind, risk="high"))
        assert route.provider == "ollama", f"{task_kind}: provider was {route.provider}"
        assert route.model == "llama3.1:8b", f"{task_kind}: model was {route.model}"
        # The specific cross-provider route that caused the false-green UAT.
        assert not (route.provider == "ollama" and route.model == "gpt-4.1-mini")


def test_no_compatible_route_fails_loud(clean_llm_env, cloud_primary_routing) -> None:
    """When the enforced provider serves none of the route candidates, the
    router fails loud instead of emitting a cross-provider route (#2109).
    """
    clean_llm_env.setenv("LLM_PROVIDER", "deepseek")
    clean_llm_env.setenv("LLM_PROVIDER_ENFORCE", "1")
    clean_llm_env.setenv("LLM_MODEL", "deepseek-chat")

    router = LLMRouter()
    with pytest.raises(LLMRouteError):
        router.route(LLMTaskIntent(task_kind="ask", risk="high"))
