from __future__ import annotations

import pytest
from click.testing import CliRunner

from app.retrieval.rerank import provider as rerank_provider
from app.retrieval.rerank.provider import get_reranker
from app.retrieval.tuning import get_retrieval_tuning, reset_retrieval_tuning_cache
import app.retrieval.tuning as retrieval_tuning
from app.services import llm
from app.reasoning.provider import OllamaDeliberationAgent
from app.settings import runtime as settings_runtime
from app.settings import wave_one
from app.settings.models import LLMRoutingSettings, RetrievalTuning, SettingsBundle
from app.cli import cli


pytestmark = pytest.mark.not_pg


def _bundle() -> SettingsBundle:
    return SettingsBundle(
        llm_routing=LLMRoutingSettings(
            timeout_seconds=17.0,
            temperature=0.7,
            reasoning_model="vault-reasoning-model",
            default_chat_model="vault-chat-model",
        ),
        retrieval_tuning=RetrievalTuning(
            rerank="always",
            rerank_provider="mock_ce",
            rerank_top_k=7,
            configured_keys=["rerank", "rerank_provider", "rerank_top_k"],
        ),
    )


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    for key in (
        "LLM_TIMEOUT", "LLM_TEMPERATURE", "REASONING_MODEL", "MERGE_LLM_MODEL",
        "RERANK_ENABLE", "RERANK_PROVIDER", "RERANK_TOP_K", "RETRIEVAL_RERANK", "RETRIEVAL_RERANK_TOP_K", "PKM_SETTINGS_PROFILE",
    ):
        monkeypatch.delenv(key, raising=False)
    reset_retrieval_tuning_cache()
    yield
    reset_retrieval_tuning_cache()


def test_vault_settings_reach_model_and_rerank_production_consumers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Covers the real resolver calls used by LLM, reasoning, and rerank production paths."""
    bundle = _bundle()
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setattr(wave_one, "get_settings_bundle", lambda: bundle)
    monkeypatch.setattr(retrieval_tuning, "get_settings_bundle", lambda: bundle)

    assert wave_one.llm_timeout_seconds() == 17.0
    assert wave_one.llm_temperature() == 0.7
    assert wave_one.reasoning_model() == "vault-reasoning-model"
    assert llm._default_model() == "vault-chat-model"
    captured: dict[str, float | str] = {}

    def fake_ollama(_system, _user, model, temperature, *, timeout, **_kwargs):
        captured["model"] = model
        captured["temperature"] = temperature
        captured["timeout"] = timeout
        return "vault-backed response"

    monkeypatch.setattr(llm, "_ollama_chat", fake_ollama)
    assert llm.call_llm("test", {"system": "s", "user": "u"}, provider_override="ollama") == "vault-backed response"
    assert captured == {
        "model": "vault-chat-model",
        "temperature": 0.7,
        "timeout": 17.0,
    }
    assert OllamaDeliberationAgent().model == "vault-reasoning-model"
    # The dedicated reranker-provider suite reloads this module. Resolve the
    # current module class here so this integration assertion remains about the
    # production selection, not a stale imported class identity.
    assert type(get_reranker()) is rerank_provider.MockCrossEncoderReranker
    assert get_retrieval_tuning().rerank_top_k == 7
    explained = wave_one.wave_one_explain()
    assert explained["retrieval.rerank.top_k"]["origin"] == "vault-shared:settings/retrieval.md"
    assert explained["retrieval.rerank.top_k"]["tier"] == "lab"
    assert explained["retrieval.rerank"] == {
        "value": "always", "origin": "vault-shared:settings/retrieval.md", "tier": "lab"
    }


def test_empty_settings_and_legacy_env_preserve_llm_and_rerank_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setattr(wave_one, "get_settings_bundle", SettingsBundle)
    monkeypatch.setattr(retrieval_tuning, "get_settings_bundle", SettingsBundle)
    assert wave_one.llm_timeout_seconds() == 60.0
    assert wave_one.llm_temperature() == 0.0
    assert wave_one.reasoning_model() == "llama3.1:8b"
    monkeypatch.setenv("LLM_TIMEOUT", "31")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.25")
    monkeypatch.setenv("REASONING_MODEL", "legacy-reasoning")
    monkeypatch.setenv("RERANK_PROVIDER", "mock_ce")
    monkeypatch.setenv("RERANK_TOP_K", "9")
    monkeypatch.setenv("RERANK_ENABLE", "1")
    assert wave_one.llm_timeout_seconds() == 31.0
    assert wave_one.llm_temperature() == 0.25
    assert wave_one.reasoning_model() == "legacy-reasoning"
    assert type(get_reranker()) is rerank_provider.MockCrossEncoderReranker
    assert get_retrieval_tuning().rerank_top_k == 9
    assert "deprecated" in str(wave_one.wave_one_explain()["retrieval.rerank.provider"]["origin"])
    assert wave_one.wave_one_explain()["retrieval.rerank"] == {
        "value": "always", "origin": "env:RERANK_ENABLE (deprecated)", "tier": "lab"
    }
    monkeypatch.setenv("RETRIEVAL_RERANK_TOP_K", "8")
    reset_retrieval_tuning_cache()
    assert wave_one.wave_one_explain()["retrieval.rerank.top_k"] == {
        "value": 8, "origin": "env:RETRIEVAL_RERANK_TOP_K", "tier": "lab"
    }


def test_llm_and_rerank_lab_keys_are_inert_for_operator_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wave_one, "get_settings_bundle", _bundle)
    monkeypatch.setattr(retrieval_tuning, "get_settings_bundle", _bundle)
    assert wave_one.llm_temperature() == 0.0
    assert get_retrieval_tuning().rerank_top_k == 100
    assert get_retrieval_tuning().rerank_provider == "none"
    assert wave_one.wave_one_explain()["retrieval.rerank.provider"]["origin"] == "registry default (operator profile)"
    assert get_retrieval_tuning().rerank == "off"


def test_retrieval_tuning_cache_tracks_bundle_identity_across_reload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    first = _bundle()
    second = first.model_copy(
        update={
            "retrieval_tuning": first.retrieval_tuning.model_copy(
                update={"rerank_top_k": 11}
            )
        }
    )
    monkeypatch.setattr(settings_runtime, "_CURRENT", None)
    monkeypatch.setattr(settings_runtime, "_build_bundle", lambda: first)

    settings_runtime.reload_settings_bundle(notify=False)
    assert get_retrieval_tuning().rerank_top_k == 7

    def invalid_bundle() -> SettingsBundle:
        raise ValueError("invalid replacement bundle")

    monkeypatch.setattr(settings_runtime, "_build_bundle", invalid_bundle)
    with pytest.raises(ValueError, match="invalid replacement bundle"):
        settings_runtime.reload_settings_bundle(notify=False)
    assert get_retrieval_tuning().rerank_top_k == 7

    monkeypatch.setattr(settings_runtime, "_build_bundle", lambda: second)
    settings_runtime.reload_settings_bundle(notify=False)
    assert get_retrieval_tuning().rerank_top_k == 11


def test_settings_explain_key_reports_effective_origin_and_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.cli.build_settings_explain_payload",
        lambda: {"settings": {"retrieval.rerank.top_k": {"value": 7, "origin": "vault", "tier": "lab"}}},
    )
    result = CliRunner().invoke(
        cli, ["settings", "explain", "retrieval.rerank.top_k"]
    )
    assert result.exit_code == 0
    assert '"tier": "lab"' in result.output
