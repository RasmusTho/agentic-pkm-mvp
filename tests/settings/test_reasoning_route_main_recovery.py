from __future__ import annotations

import pytest

from app.cli.settings_explain import build_settings_explain_payload
from app.components.llm.fabric import ChatClient
from app.settings.models import LLMRoutingSettings
from app.reasoning import provider as reasoning_provider
from app.reasoning.models import ReasoningMode
from app.settings import runtime
from app.settings.models import RetrievalTuning, SettingsBundle
from app.retrieval import tuning
from app.settings.reasoning_route import resolve_effective_reasoning_route


def _compiled_openai_bundle() -> SettingsBundle:
    return SettingsBundle(
        llm_routing=LLMRoutingSettings(
            default_reasoning=LLMRoutingSettings.TaskPolicy(
                primary=LLMRoutingSettings.RouteTarget(provider="openai", model="gpt-4.1")
            )
        )
    )


def test_registered_explain_and_execution_share_compiled_reasoning_route(monkeypatch) -> None:
    bundle = _compiled_openai_bundle()
    monkeypatch.setattr(runtime, "get_settings_bundle", lambda: bundle)
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: bundle)
    monkeypatch.delenv("REASONING_MODEL", raising=False)
    monkeypatch.delenv("LLM_FORCE_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_FORCE_MODEL", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setattr(ChatClient, "chat", lambda self, *args, **kwargs: "{}")

    route = resolve_effective_reasoning_route()
    payload = build_settings_explain_payload()
    _response, execution = reasoning_provider._call_chat_with_route(
        task_kind="reasoning", pack={"system": "s", "user": "u"}, agent=None, kind=None, trace_id=None
    )

    assert (route.provider, route.model) == ("openai", "gpt-4.1")
    assert payload["llm"]["reasoning_model"]["provider"] == route.provider
    assert payload["llm"]["reasoning_model"]["model"] == route.model
    assert (execution["provider"], execution["model"]) == (route.provider, route.model)


def test_model_override_trace_and_reload_generation_remain_consistent(monkeypatch) -> None:
    bundle = _compiled_openai_bundle()
    monkeypatch.setattr(runtime, "get_settings_bundle", lambda: bundle)
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: bundle)
    monkeypatch.setenv("REASONING_MODEL", "gpt-4.1-mini")
    monkeypatch.delenv("LLM_FORCE_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_FORCE_MODEL", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    route = resolve_effective_reasoning_route()
    payload = build_settings_explain_payload()["llm"]["reasoning_model"]

    assert route.provider == "openai"  # model-only compat override cannot flip provider
    assert route.model == "gpt-4.1-mini"
    assert route.reason == "legacy:REASONING_MODEL"
    assert payload["provider"] == "openai"
    assert payload["model"] == "gpt-4.1-mini"

    first = SettingsBundle(retrieval_tuning=RetrievalTuning(rerank_top_k=3))
    second = SettingsBundle(retrieval_tuning=RetrievalTuning(rerank_top_k=9))
    bundles = iter((first, second))
    monkeypatch.setattr(runtime, "_build_bundle", lambda: next(bundles))
    monkeypatch.setattr(runtime, "_CURRENT", None)
    tuning.reset_retrieval_tuning_cache()
    runtime.reload_settings_bundle(notify=False)
    assert tuning.get_retrieval_tuning().rerank_top_k == 3
    runtime.reload_settings_bundle(notify=False)
    assert tuning.get_retrieval_tuning().rerank_top_k == 9


def test_force_override_explain_reports_its_real_origin(monkeypatch) -> None:
    bundle = _compiled_openai_bundle()
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: bundle)
    monkeypatch.setenv("LLM_FORCE_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FORCE_MODEL", "gpt-4.1-mini")
    monkeypatch.delenv("REASONING_MODEL", raising=False)

    payload = build_settings_explain_payload()["llm"]["reasoning_model"]

    assert payload["origin"] == "env:LLM_FORCE_PROVIDER/LLM_FORCE_MODEL"
    assert (payload["provider"], payload["model"]) == ("openai", "gpt-4.1-mini")


def test_reasoning_execution_failure_carries_the_selected_route(monkeypatch) -> None:
    bundle = _compiled_openai_bundle()
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: bundle)
    monkeypatch.delenv("LLM_FORCE_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_FORCE_MODEL", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setattr(ChatClient, "chat", lambda self, *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(reasoning_provider.ReasoningRouteExecutionError) as exc_info:
        reasoning_provider._call_chat_with_route(
            task_kind="reasoning", pack={}, agent=None, kind=None, trace_id=None
        )

    assert (exc_info.value.route.provider, exc_info.value.route.model) == ("openai", "gpt-4.1")


def test_retrieval_cache_rechecks_bundle_identity_after_reload_race(monkeypatch) -> None:
    first = SettingsBundle(retrieval_tuning=RetrievalTuning(rerank_top_k=3))
    second = SettingsBundle(retrieval_tuning=RetrievalTuning(rerank_top_k=9))
    current = [first]
    monkeypatch.setattr("app.retrieval.tuning.get_settings_bundle", lambda: current[0])
    tuning.reset_retrieval_tuning_cache()

    assert tuning.get_retrieval_tuning().rerank_top_k == 3
    current[0] = second
    assert tuning.get_retrieval_tuning().rerank_top_k == 9


def test_ask_failure_returns_the_immutable_selected_route(monkeypatch) -> None:
    route = reasoning_provider.LLMRoute("openai", "gpt-4.1", "chat", "settings")
    monkeypatch.setattr(reasoning_provider, "_reasoning_backend", lambda: "llm")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setattr(
        reasoning_provider,
        "_call_chat_with_route",
        lambda **_kwargs: (_ for _ in ()).throw(
            reasoning_provider.ReasoningRouteExecutionError(route, RuntimeError("boom"))
        ),
    )
    logged: list[dict[str, object]] = []
    monkeypatch.setattr(reasoning_provider, "log_llm_call", lambda **kwargs: logged.append(kwargs))

    result = reasoning_provider.run_reasoning(
        ReasoningMode.ASK_ANSWER, [], question="What changed?"
    )

    assert result.status == "failed"
    assert result.llm_route == {"provider": "openai", "model": "gpt-4.1", "mode": "chat", "reason": "settings", "degraded": False}
    assert logged[0]["provider"] == "openai"
    assert logged[0]["model"] == "gpt-4.1"
