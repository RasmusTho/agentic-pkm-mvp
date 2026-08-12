from __future__ import annotations

import json
from dataclasses import replace
from textwrap import dedent

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.components.embeddings import EmbeddingIdentity
from app.components.llm import router as llm_router
from app.components.llm.fabric import ChatClient
from app.components.llm.router import LLMRoute
from app.reasoning import provider as reasoning_provider
from app.reasoning.models import ReasoningMode
from app.reasoning.provider import OllamaDeliberationAgent
from app.reasoning.schema import ReasoningInput
from app.retrieval import tuning as retrieval_tuning
from app.settings import compiler, wave_one
from app.settings.models import LLMRoutingSettings, SettingsBundle


pytestmark = pytest.mark.not_pg


@pytest.fixture(autouse=True)
def _clean_route_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "CI",
        "LLM_FORCE_MODEL",
        "LLM_FORCE_PROVIDER",
        "LLM_MODEL",
        "LLM_PROVIDER",
        "LLM_PROVIDER_ENFORCE",
        "MERGE_LLM_MODEL",
        "REASONING_MODEL",
        "REASONING_PROVIDER",
    ):
        monkeypatch.delenv(key, raising=False)


def _compile_openai_reasoning_bundle(tmp_path, monkeypatch: pytest.MonkeyPatch):
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
    return compiler.compile_all(vault_dir=settings_dir, auto_heal=False)


def _compile_openai_task_reasoning_bundle(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
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
            tasks:
              reasoning:
                primary:
                  model_id: openai.chat.gpt_4_1
            ```
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(compiler, "RUNTIME", tmp_path / "runtime" / "settings")
    return compiler.compile_all(vault_dir=settings_dir, auto_heal=False)


def test_registered_cli_and_execution_share_compiled_no_env_reasoning_route(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _compile_openai_reasoning_bundle(tmp_path, monkeypatch)
    monkeypatch.setattr(llm_router, "get_settings_bundle", lambda: bundle)
    monkeypatch.setattr(wave_one, "get_settings_bundle", lambda: bundle)
    monkeypatch.setattr(retrieval_tuning, "get_settings_bundle", lambda: bundle)

    resolver_calls: list[tuple[str, str]] = []
    original_resolver = llm_router.resolve_effective_reasoning_route

    def recording_resolver(*args, **kwargs):
        resolved = original_resolver(*args, **kwargs)
        resolver_calls.append((resolved.route.provider, resolved.route.model))
        return resolved

    monkeypatch.setattr(
        llm_router,
        "resolve_effective_reasoning_route",
        recording_resolver,
    )

    def unexpected_execution(*_args, **_kwargs):
        raise AssertionError("settings explain must not execute a provider")

    monkeypatch.setattr(ChatClient, "chat", unexpected_execution)
    result = CliRunner().invoke(
        cli,
        ["settings", "explain", "llm.reasoning_model"],
    )

    assert result.exit_code == 0, result.output
    explained = json.loads(result.output)["llm.reasoning_model"]
    assert explained == {
        "origin": "vault-shared:settings/llm_routing.md",
        "tier": "operator",
        "value": "gpt-4.1",
    }

    agent = OllamaDeliberationAgent()
    assert agent.execution_identity() == ("openai", "gpt-4.1")

    executed_routes: list[LLMRoute] = []

    def successful_chat(self, *_args, **_kwargs):
        executed_routes.append(self.route)
        return '{"claims": [], "evidence": [], "inferences": []}'

    monkeypatch.setattr(ChatClient, "chat", successful_chat)
    agent.reason(
        ReasoningInput(
            object_uuid="00000000-0000-0000-0000-000000000001",
            text="reason over this",
        )
    )

    assert [(route.provider, route.model) for route in executed_routes] == [
        ("openai", "gpt-4.1")
    ]
    assert resolver_calls == [
        ("openai", "gpt-4.1"),
        ("openai", "gpt-4.1"),
    ]


def test_reasoning_explain_reports_force_model_origin(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _compile_openai_reasoning_bundle(tmp_path, monkeypatch)
    monkeypatch.setattr(llm_router, "get_settings_bundle", lambda: bundle)
    monkeypatch.setattr(wave_one, "get_settings_bundle", lambda: bundle)
    monkeypatch.setattr(retrieval_tuning, "get_settings_bundle", lambda: bundle)
    monkeypatch.setenv("LLM_FORCE_MODEL", "forced-reasoning-model")

    explained = wave_one.wave_one_explain()["llm.reasoning_model"]

    assert explained == {
        "origin": "env:LLM_FORCE_MODEL",
        "tier": "operator",
        "value": "forced-reasoning-model",
    }


def test_task_specific_reasoning_route_preserves_vault_origin(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _compile_openai_task_reasoning_bundle(tmp_path, monkeypatch)
    monkeypatch.setattr(llm_router, "get_settings_bundle", lambda: bundle)
    monkeypatch.setattr(wave_one, "get_settings_bundle", lambda: bundle)
    monkeypatch.setattr(retrieval_tuning, "get_settings_bundle", lambda: bundle)

    result = CliRunner().invoke(
        cli,
        ["settings", "explain", "llm.reasoning_model"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["llm.reasoning_model"] == {
        "origin": "vault-shared:settings/llm_routing.md",
        "tier": "operator",
        "value": "gpt-4.1",
    }
    assert OllamaDeliberationAgent().execution_identity() == ("openai", "gpt-4.1")


def test_reasoning_route_preserves_override_execution_and_trace_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    embedding_identity = EmbeddingIdentity(
        provider="openai",
        model="unused-embedding-model",
        dim=3,
    )
    selected_route = LLMRoute(
        provider="openai",
        model="gpt-4.1",
        mode="chat",
        reason="settings",
        degraded=True,
        embedding_identity=embedding_identity,
        model_origin="vault-shared:settings/llm_routing.md",
    )
    original_route = replace(selected_route)

    resolved = llm_router.resolve_effective_reasoning_route(
        selected_route,
        model_override=" legacy-reasoning ",
    )

    assert selected_route == original_route
    assert resolved.route == replace(
        selected_route,
        model="legacy-reasoning",
        model_origin="env:REASONING_MODEL (deprecated)",
    )
    assert resolved.model_origin == "env:REASONING_MODEL (deprecated)"

    monkeypatch.setenv("REASONING_MODEL", "legacy-reasoning")
    monkeypatch.setattr(
        llm_router.LLMRouter,
        "route",
        lambda _self, _intent: selected_route,
    )
    agent = OllamaDeliberationAgent()
    assert agent.execution_identity() == ("openai", "legacy-reasoning")
    assert agent._client.route == resolved.route

    successful_routes: list[LLMRoute] = []

    def successful_chat(self, *_args, **_kwargs):
        successful_routes.append(self.route)
        return '{"claims": [], "evidence": [], "inferences": []}'

    monkeypatch.setattr(ChatClient, "chat", successful_chat)
    agent.reason(
        ReasoningInput(
            object_uuid="00000000-0000-0000-0000-000000000001",
            text="reason over this",
        )
    )
    assert successful_routes == [resolved.route]

    def failing_chat(_self, *_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    traced: dict[str, object] = {}
    monkeypatch.setattr(ChatClient, "chat", failing_chat)
    monkeypatch.setattr(
        reasoning_provider,
        "get_deliberation_agent",
        lambda: agent,
    )
    monkeypatch.setattr(
        reasoning_provider,
        "_load_object_text",
        lambda _object_id: ("reason over this", {}),
    )
    monkeypatch.setattr(
        reasoning_provider,
        "log_llm_call",
        lambda **kwargs: traced.update(kwargs),
    )

    result = reasoning_provider.run_reasoning(
        ReasoningMode.CLAIMS,
        ["00000000-0000-0000-0000-000000000001"],
        trace_id="trace-effective-route",
    )

    assert result.status == "failed"
    assert traced["provider"] == "openai"
    assert traced["model"] == "legacy-reasoning"


def test_routing_failure_keeps_provider_failure_trace_non_throwing(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _compile_openai_reasoning_bundle(tmp_path, monkeypatch)
    monkeypatch.setattr(llm_router, "get_settings_bundle", lambda: bundle)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_PROVIDER_ENFORCE", "1")
    monkeypatch.setenv("REASONING_MODEL", "declared-reasoning-model")
    monkeypatch.setattr(
        reasoning_provider,
        "_load_object_text",
        lambda _object_id: ("reason over this", {}),
    )
    traced: dict[str, object] = {}
    monkeypatch.setattr(
        reasoning_provider,
        "log_llm_call",
        lambda **kwargs: traced.update(kwargs),
    )

    result = reasoning_provider.run_reasoning(
        ReasoningMode.CLAIMS,
        ["00000000-0000-0000-0000-000000000001"],
        trace_id="trace-routing-failure",
    )

    assert result.status == "failed"
    assert "no routing candidate" in (result.error or "")
    assert traced["provider"] == "ollama"
    assert traced["model"] == "declared-reasoning-model"


def test_route_failure_keeps_registered_settings_explain_serializable(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _compile_openai_reasoning_bundle(tmp_path, monkeypatch)
    monkeypatch.setattr(llm_router, "get_settings_bundle", lambda: bundle)
    monkeypatch.setattr(wave_one, "get_settings_bundle", lambda: bundle)
    monkeypatch.setattr(retrieval_tuning, "get_settings_bundle", lambda: bundle)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_PROVIDER_ENFORCE", "1")

    retrieval_result = CliRunner().invoke(
        cli,
        ["settings", "explain", "retrieval.rerank.top_k"],
    )
    reasoning_result = CliRunner().invoke(
        cli,
        ["settings", "explain", "llm.reasoning_model"],
    )

    assert retrieval_result.exit_code == 0, retrieval_result.output
    assert "retrieval.rerank.top_k" in json.loads(retrieval_result.output)
    assert reasoning_result.exit_code == 0, reasoning_result.output
    explained = json.loads(reasoning_result.output)["llm.reasoning_model"]
    assert explained["value"] is None
    assert explained["origin"] == "unresolved:routing-error"
    assert explained["status"] == "error"
    assert "no routing candidate" in explained["error"]


def test_wave_one_explain_uses_one_captured_llm_bundle_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def bundle(label: str, timeout: float) -> SettingsBundle:
        return SettingsBundle(
            llm_routing=LLMRoutingSettings(
                timeout_seconds=timeout,
                default_reasoning=LLMRoutingSettings.TaskPolicy(
                    primary=LLMRoutingSettings.RouteTarget(
                        provider="openai",
                        model=f"reasoning-{label}",
                    )
                ),
                default_chat=LLMRoutingSettings.TaskPolicy(
                    primary=LLMRoutingSettings.RouteTarget(
                        provider="mock",
                        model=f"chat-{label}",
                    )
                ),
                configured_keys=[
                    "default_chat",
                    "default_reasoning",
                    "timeout_seconds",
                ],
            )
        )

    old_bundle = bundle("old", 17.0)
    new_bundle = bundle("new", 29.0)
    bundle_reads: list[SettingsBundle] = []
    available = iter((old_bundle, new_bundle))

    def sequenced_bundle() -> SettingsBundle:
        selected = next(available)
        bundle_reads.append(selected)
        return selected

    def unexpected_router_reload() -> SettingsBundle:
        raise AssertionError("captured-bundle explain must not reload settings")

    monkeypatch.setattr(wave_one, "get_settings_bundle", sequenced_bundle)
    monkeypatch.setattr(llm_router, "get_settings_bundle", unexpected_router_reload)
    monkeypatch.setattr(retrieval_tuning, "get_settings_bundle", lambda: old_bundle)

    explained = wave_one.wave_one_explain()

    assert bundle_reads == [old_bundle]
    assert explained["llm.timeout_seconds"]["value"] == 17.0
    assert explained["llm.default_chat_model"]["value"] == "chat-old"
    assert explained["llm.reasoning_model"] == {
        "origin": "vault-shared:settings/llm_routing.md",
        "tier": "operator",
        "value": "reasoning-old",
    }
