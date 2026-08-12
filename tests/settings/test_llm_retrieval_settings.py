from __future__ import annotations

import json
from textwrap import dedent

import pytest
from click.testing import CliRunner

from app.retrieval.rerank import provider as rerank_provider
from app.retrieval.rerank.provider import get_reranker
from app.retrieval.tuning import get_retrieval_tuning, reset_retrieval_tuning_cache
import app.retrieval.tuning as retrieval_tuning
from app.services import llm
from app.reasoning import provider as reasoning_provider
from app.reasoning.provider import OllamaDeliberationAgent
from app.reasoning.models import ReasoningMode
from app.reasoning.schema import ReasoningInput
from app.settings import compiler
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
            default_reasoning=LLMRoutingSettings.TaskPolicy(
                primary=LLMRoutingSettings.RouteTarget(
                    provider="ollama", model="vault-reasoning-model"
                )
            ),
            default_chat=LLMRoutingSettings.TaskPolicy(
                primary=LLMRoutingSettings.RouteTarget(
                    provider="ollama", model="vault-chat-model"
                )
            ),
            configured_keys=[
                "default_chat",
                "default_reasoning",
                "temperature",
                "timeout_seconds",
            ],
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
        "LLM_PROVIDER", "LLM_MODEL", "LLM_TIMEOUT", "LLM_TEMPERATURE",
        "REASONING_MODEL", "MERGE_LLM_MODEL",
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
    monkeypatch.setattr(
        "app.components.llm.router.get_settings_bundle", lambda: bundle
    )

    assert wave_one.llm_timeout_seconds() == 17.0
    assert wave_one.llm_temperature() == 0.7
    assert wave_one.reasoning_model() == "vault-reasoning-model"
    assert llm._default_model("ollama") == "vault-chat-model"
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
    monkeypatch.setattr(
        "app.components.llm.router.get_settings_bundle", SettingsBundle
    )
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


def test_canonical_compiled_routes_reach_real_llm_consumers(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Compile the canonical nested route shape before invoking production consumers."""
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    (settings_dir / "llm_routing.md").write_text(
        dedent(
            """
            ---
            uuid: llm-routing
            ---
            ## Routing
            ```yaml settings
            timeout_seconds: 19
            default_chat:
              primary:
                model_id: openai.chat.gpt_4_1_mini
            default_reasoning:
              primary:
                model_id: openai.chat.gpt_4_1
            ```
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(compiler, "RUNTIME", tmp_path / "runtime" / "settings")
    bundle = compiler.compile_all(vault_dir=settings_dir, auto_heal=False)
    monkeypatch.setattr(wave_one, "get_settings_bundle", lambda: bundle)

    assert bundle.llm_routing.configured_keys == [
        "default_chat",
        "default_reasoning",
        "timeout_seconds",
    ]
    captured: dict[str, object] = {}

    def fake_http_chat(**kwargs):
        captured.update(kwargs)
        return "compiled-route response", {"content": "compiled-route response"}

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://openai.test/v1")
    monkeypatch.setenv("REASONING_PROVIDER", "llm")
    monkeypatch.setattr(llm, "_http_chat", fake_http_chat)
    monkeypatch.setattr(
        "app.components.llm.router.get_settings_bundle", lambda: bundle
    )
    assert llm.call_llm("test", {"system": "s", "user": "u"}) == "compiled-route response"
    assert captured["model"] == "gpt-4.1-mini"
    assert captured["timeout"] == 19.0
    openai_agent = reasoning_provider.get_deliberation_agent()
    assert isinstance(openai_agent, OllamaDeliberationAgent)
    assert openai_agent.execution_identity() == ("openai", "gpt-4.1")

    monkeypatch.setenv("REASONING_MODEL", "legacy-reasoning")
    overridden_agent = reasoning_provider.get_deliberation_agent()
    assert isinstance(overridden_agent, OllamaDeliberationAgent)
    assert overridden_agent.execution_identity() == (
        "openai",
        "legacy-reasoning",
    )
    override_calls: list[tuple[str, str]] = []

    class SuccessfulOverrideClient:
        route = overridden_agent._client.route

        def chat(self, name, _pack, **_kwargs):
            override_calls.append((name, self.route.model))
            return '{"claims": [], "evidence": [], "inferences": []}'

    overridden_agent._client = SuccessfulOverrideClient()  # type: ignore[assignment]
    overridden_agent.reason(
        ReasoningInput(
            object_uuid="00000000-0000-0000-0000-000000000001",
            text="reason over this",
        )
    )
    assert override_calls == [("reasoning", "legacy-reasoning")]

    captured_trace: dict[str, object] = {}

    class FailingClient:
        route = overridden_agent._client.route

        def chat(self, *_args, **_kwargs):
            override_calls.append(("failure", self.route.model))
            raise RuntimeError("provider unavailable")

    overridden_agent._client = FailingClient()  # type: ignore[assignment]
    monkeypatch.setattr(
        reasoning_provider, "get_deliberation_agent", lambda: overridden_agent
    )
    monkeypatch.setattr(
        reasoning_provider,
        "_load_object_text",
        lambda _object_id: ("reason over this", {}),
    )
    monkeypatch.setattr(
        reasoning_provider,
        "log_llm_call",
        lambda **kwargs: captured_trace.update(kwargs),
    )
    result = reasoning_provider.run_reasoning(
        ReasoningMode.CLAIMS,
        ["00000000-0000-0000-0000-000000000001"],
        trace_id="trace-route-identity",
    )
    assert result.status == "failed"
    assert override_calls[-1] == ("failure", "legacy-reasoning")
    assert captured_trace["provider"] == "openai"
    assert captured_trace["model"] == "legacy-reasoning"
    monkeypatch.delenv("REASONING_MODEL")

    routing_path = settings_dir / "llm_routing.md"
    routing_path.write_text(
        routing_path.read_text(encoding="utf-8").replace(
            "model_id: openai.chat.gpt_4_1_mini",
            "model_id: ollama.chat.llama3_1_8b",
        ).replace(
            "model_id: openai.chat.gpt_4_1",
            "model_id: ollama.chat.llama3_1_8b",
        ),
        encoding="utf-8",
    )
    bundle = compiler.compile_all(vault_dir=settings_dir, auto_heal=False)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    assert bundle.llm_routing.default_reasoning.primary.provider == "ollama"
    ollama_agent = OllamaDeliberationAgent()
    assert ollama_agent.execution_identity() == ("ollama", "llama3.1:8b")


def test_reasoning_model_preserves_provider_model_identity_and_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routing = LLMRoutingSettings(
        default_reasoning=LLMRoutingSettings.TaskPolicy(
            primary=LLMRoutingSettings.RouteTarget(
                provider="openai", model="gpt-reasoning"
            )
        ),
        configured_keys=["default_reasoning"],
    )
    bundle = SettingsBundle(llm_routing=routing)
    monkeypatch.setattr(wave_one, "get_settings_bundle", lambda: bundle)
    monkeypatch.setattr(
        "app.components.llm.router.get_settings_bundle", lambda: bundle
    )

    assert wave_one.reasoning_model() == "gpt-reasoning"
    assert OllamaDeliberationAgent().execution_identity() == (
        "openai",
        "gpt-reasoning",
    )

    monkeypatch.setenv("REASONING_MODEL", "legacy-reasoning")
    assert wave_one.reasoning_model() == "legacy-reasoning"
    assert OllamaDeliberationAgent().execution_identity() == (
        "openai",
        "legacy-reasoning",
    )
    monkeypatch.delenv("REASONING_MODEL")



def test_default_chat_model_never_crosses_selected_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routing = LLMRoutingSettings(
        default_chat=LLMRoutingSettings.TaskPolicy(
            primary=LLMRoutingSettings.RouteTarget(
                provider="openai", model="gpt-vault"
            )
        ),
        configured_keys=["default_chat"],
    )
    bundle = SettingsBundle(llm_routing=routing)
    monkeypatch.setattr(wave_one, "get_settings_bundle", lambda: bundle)

    captured: dict[str, str] = {}

    def fake_ollama(_system, _user, model, _temperature, **_kwargs):
        captured["ollama_model"] = model
        return "local response"

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setattr(llm, "_ollama_chat", fake_ollama)
    assert llm.call_llm("test", {"system": "s", "user": "u"}) == "local response"
    assert captured["ollama_model"] == "llama3.1:8b"

    def fake_http_chat(**kwargs):
        captured["openai_model"] = str(kwargs["model"])
        return "cloud response", {"content": "cloud response"}

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://openai.test/v1")
    monkeypatch.setattr(llm, "_http_chat", fake_http_chat)
    assert llm.call_llm("test", {"system": "s", "user": "u"}) == "cloud response"
    assert captured["openai_model"] == "gpt-vault"


@pytest.mark.parametrize(
    ("key", "bundle", "environment", "expected_origin"),
    [
        ("llm.timeout_seconds", SettingsBundle(), {}, "registry default"),
        (
            "llm.reasoning_model",
            _bundle(),
            {"PKM_SETTINGS_PROFILE": "lab"},
            "vault-shared:settings/llm_routing.md",
        ),
        (
            "llm.temperature",
            _bundle(),
            {},
            "registry default (operator profile)",
        ),
        (
            "llm.timeout_seconds",
            SettingsBundle(),
            {"LLM_TIMEOUT": "23"},
            "env:LLM_TIMEOUT (deprecated)",
        ),
    ],
)
def test_registered_cli_reports_effective_llm_provenance(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    bundle: SettingsBundle,
    environment: dict[str, str],
    expected_origin: str,
) -> None:
    monkeypatch.setattr(wave_one, "get_settings_bundle", lambda: bundle)
    monkeypatch.setattr(retrieval_tuning, "get_settings_bundle", lambda: bundle)
    monkeypatch.setattr(
        "app.components.llm.router.get_settings_bundle", lambda: bundle
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    result = CliRunner().invoke(cli, ["settings", "explain", key])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload[key]["origin"] == expected_origin


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
