from __future__ import annotations

import pytest

from app.components.llm.router import LLMRouter, LLMTaskIntent
from app.retrieval import tuning
from app.settings import runtime
from app.settings.models import LLMRoutingSettings, RetrievalTuning, SettingsBundle
from app.settings.tiering import resolve_dev_lab_env_value


def _bundle(*, rerank: str = "off", top_k: int = 100) -> SettingsBundle:
    return SettingsBundle(
        llm_routing=LLMRoutingSettings(
            timeout_seconds=12,
            temperature=0.2,
            default_reasoning=LLMRoutingSettings.TaskPolicy(
                primary=LLMRoutingSettings.RouteTarget(provider="openai", model="gpt-4.1")
            )
        ),
        retrieval_tuning=RetrievalTuning(rerank=rerank, rerank_top_k=top_k),
    )


def test_vault_settings_reach_model_reasoning_and_rerank_consumers_with_one_generation(monkeypatch) -> None:
    bundle = _bundle(rerank="always", top_k=7)
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: bundle)
    monkeypatch.setattr("app.retrieval.tuning.get_settings_bundle", lambda: bundle)
    monkeypatch.delenv("LLM_FORCE_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_FORCE_MODEL", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    tuning.reset_retrieval_tuning_cache()

    route = LLMRouter().route(LLMTaskIntent(task_kind="reasoning"))
    retrieval = tuning.get_retrieval_tuning()

    assert (route.provider, route.model) == ("openai", "gpt-4.1")
    assert (route.timeout_seconds, route.temperature) == (12, 0.2)
    assert (retrieval.rerank, retrieval.rerank_top_k) == ("always", 7)


def test_empty_settings_and_legacy_env_preserve_behavior_without_provider_flip(monkeypatch) -> None:
    bundle = SettingsBundle()
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: bundle)
    monkeypatch.setattr("app.retrieval.tuning.get_settings_bundle", lambda: bundle)
    monkeypatch.delenv("LLM_FORCE_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_FORCE_MODEL", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("REASONING_MODEL", "compat-model")
    monkeypatch.setenv("RERANK_ENABLE", "1")
    monkeypatch.setenv("RERANK_TOP_K", "3")
    tuning.reset_retrieval_tuning_cache()

    route = LLMRouter().route(LLMTaskIntent(task_kind="reasoning"))
    retrieval = tuning.get_retrieval_tuning()

    assert route.provider == "mock"
    assert route.model == "llama3.1:8b"  # only the shared resolver applies REASONING_MODEL
    assert (retrieval.rerank, retrieval.rerank_top_k) == ("always", 3)


def test_operator_tier_and_last_valid_bundle_fail_closed(monkeypatch, tmp_path) -> None:
    assert resolve_dev_lab_env_value(
        "LAB_ONLY_MODEL", default="operator-model", env={"LAB_ONLY_MODEL": "lab-model"}
    ) == "operator-model"

    runtime_dir = tmp_path / "runtime" / "settings"
    runtime_dir.mkdir(parents=True)
    for name, payload in (("global.yaml", {}), ("providers.yaml", {}), ("llm_routing.yaml", {})):
        (runtime_dir / name).write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(runtime, "RUNTIME", runtime_dir)
    monkeypatch.setattr(runtime, "_CURRENT", None)
    runtime.reload_settings_bundle(notify=False)
    before = runtime.get_settings_bundle()
    (runtime_dir / "retrieval_tuning.yaml").write_text("rerank_top_k: invalid\n", encoding="utf-8")

    with pytest.raises(Exception):
        runtime.reload_settings_bundle(notify=False)
    assert runtime.get_settings_bundle() is before
