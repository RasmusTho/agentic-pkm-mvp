from __future__ import annotations

from app.cli.settings_explain import build_settings_explain_payload
from app.components.llm.fabric import ChatClient
from app.settings.models import LLMRoutingSettings
from app.reasoning import provider as reasoning_provider
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
