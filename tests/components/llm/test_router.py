from __future__ import annotations

import pytest

from app.components.llm.router import LLMRouter, LLMTaskIntent
from app.config import llm as llm_config
from app.settings.models import LLMRoutingSettings, SettingsBundle


@pytest.fixture(autouse=True)
def _isolate_router_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: SettingsBundle())


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("mock", "mock"),
        ("ollama", "ollama"),
        ("openai", "openai"),
        ("deepseek", "deepseek"),
    ],
)
def test_router_respects_env_defaults(clean_llm_env, provider: str, expected: str) -> None:
    """
    Router MUST select provider/model from environment variables.

    Validates: docs/LLM_ROUTING.md §Configuration precedence
    Contract: LLM_PROVIDER env → router.route() → LLMRoute.provider
    Mutation guard: hardcoded provider (always `mock`).
    """
    clean_llm_env.setenv("LLM_PROVIDER", provider)
    clean_llm_env.setenv("LLM_MODEL", "llama-test")
    clean_llm_env.setenv("EMBED_MODEL", "embed-test")

    router = LLMRouter()
    decide = router.route(LLMTaskIntent(task_kind="decide"))

    assert decide.provider == expected


def test_router_respects_model_env_defaults(clean_llm_env) -> None:
    """
    Router MUST select model defaults from environment variables.

    Validates: docs/LLM_ROUTING.md §Supported environment variables
    Contract: LLM_MODEL/EMBED_MODEL → LLMRoute.model
    """
    clean_llm_env.setenv("LLM_PROVIDER", "ollama")
    clean_llm_env.setenv("LLM_MODEL", "llama-test")
    clean_llm_env.setenv("EMBED_MODEL", "embed-test")
    clean_llm_env.setattr(llm_config, "_ACTIVE_PROVIDER", None)

    router = LLMRouter()
    decide = router.route(LLMTaskIntent(task_kind="decide"))
    embed = router.route(LLMTaskIntent(task_kind="embed", strict_identity_required=True))

    assert decide.provider == "ollama"
    assert decide.model == "llama-test"
    assert decide.mode == "chat"

    assert embed.provider == "ollama"
    assert embed.model == "embed-test"
    assert embed.mode == "embeddings"


def test_router_forces_mock_for_chat_determinism(clean_llm_env) -> None:
    """
    Router MUST force mock when determinism_required=True.

    Validates: docs/LLM_ROUTING.md §Deterministic routing
    """
    clean_llm_env.setenv("LLM_PROVIDER", "ollama")
    clean_llm_env.setenv("LLM_MODEL", "llama3.1:8b")
    clean_llm_env.setenv("EMBED_MODEL", "nomic-embed-text:latest")

    router = LLMRouter()
    embed = router.route(LLMTaskIntent(task_kind="decide", determinism_required=True))

    assert embed.provider == "mock"
    assert embed.reason == "deterministic"


def test_router_preserves_embedding_identity_when_determinism_requested(clean_llm_env) -> None:
    clean_llm_env.setenv("LLM_PROVIDER", "ollama")
    clean_llm_env.setenv("OLLAMA_EMBED_MODEL", "nomic-embed-text:latest")
    clean_llm_env.setenv("EMBED_MODEL", "nomic-embed-text:latest")
    clean_llm_env.setattr(llm_config, "_ACTIVE_PROVIDER", None)

    router = LLMRouter()
    embed = router.route(LLMTaskIntent(task_kind="embed", determinism_required=True, strict_identity_required=True))

    assert embed.provider == "ollama"
    assert embed.model == "nomic-embed-text:latest"


def test_router_force_overrides(clean_llm_env) -> None:
    """
    Router MUST honor forced provider/model overrides.

    Validates: docs/LLM_ROUTING.md §Configuration precedence
    """
    clean_llm_env.setenv("LLM_PROVIDER", "ollama")
    clean_llm_env.setenv("LLM_MODEL", "llama3.1:8b")
    clean_llm_env.setenv("LLM_FORCE_PROVIDER", "ollama")
    clean_llm_env.setenv("LLM_FORCE_MODEL", "custom-model")

    router = LLMRouter()
    route = router.route(LLMTaskIntent(task_kind="plan"))

    assert route.provider == "ollama"
    assert route.model == "custom-model"
    assert route.reason == "forced"


def test_router_force_override_beats_determinism(clean_llm_env) -> None:
    """
    Forced overrides MUST beat determinism fallback.

    Validates: docs/LLM_ROUTING.md §Configuration precedence
    """
    clean_llm_env.setenv("LLM_PROVIDER", "ollama")
    clean_llm_env.setenv("EMBED_MODEL", "nomic-embed-text:latest")
    clean_llm_env.setenv("LLM_FORCE_PROVIDER", "ollama")
    clean_llm_env.setenv("LLM_FORCE_MODEL", "forced-embed")

    router = LLMRouter()
    embed = router.route(LLMTaskIntent(task_kind="embed", determinism_required=True))

    assert embed.provider == "ollama"
    assert embed.model == "forced-embed"
    assert embed.reason == "forced"


def test_router_uses_settings_task_policy(monkeypatch, clean_llm_env) -> None:
    clean_llm_env.delenv("LLM_PROVIDER", raising=False)
    bundle = SettingsBundle(
        llm_routing=LLMRoutingSettings(
            default_chat=LLMRoutingSettings.TaskPolicy(
                primary=LLMRoutingSettings.RouteTarget(
                    model_id="openai.chat.gpt_4_1_mini", provider="openai", model="gpt-chat"
                ),
                fallback=LLMRoutingSettings.FallbackPolicy(
                    mode="local", model_id="ollama.chat.llama3_1_8b", provider="ollama", model="llama-local"
                ),
            ),
            tasks={
                "plan": LLMRoutingSettings.TaskPolicy(
                    primary=LLMRoutingSettings.RouteTarget(
                        model_id="openai.chat.gpt_4_1", provider="openai", model="gpt-4.1"
                    ),
                    fallback=LLMRoutingSettings.FallbackPolicy(
                        mode="local", model_id="ollama.chat.llama3_1_8b", provider="ollama", model="llama-local"
                    ),
                )
            },
        )
    )
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: bundle)

    router = LLMRouter()
    route = router.route(LLMTaskIntent(task_kind="plan"))

    assert route.provider == "openai"
    assert route.model == "gpt-4.1"
    assert route.reason == "settings"

    described = router.describe_intent(LLMTaskIntent(task_kind="plan"))
    assert described["policy"]["primary"]["model_id"] == "openai.chat.gpt_4_1"
    assert described["policy"]["fallback"]["model_id"] == "ollama.chat.llama3_1_8b"


def test_router_rejects_incompatible_embedding_fallback(monkeypatch, clean_llm_env) -> None:
    clean_llm_env.setenv("LLM_PROVIDER", "ollama")
    clean_llm_env.setenv("EMBED_MODEL", "nomic-embed-text:latest")
    clean_llm_env.setenv("EMBED_DIM", "768")
    bundle = SettingsBundle(
        llm_routing=LLMRoutingSettings(
            default_embedding=LLMRoutingSettings.TaskPolicy(
                primary=LLMRoutingSettings.RouteTarget(provider="ollama", model="nomic-embed-text:latest"),
                fallback=LLMRoutingSettings.FallbackPolicy(mode="allowed", provider="mock", model="mock"),
                require_compatible_identity=True,
            )
        )
    )
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: bundle)

    router = LLMRouter()
    route = router.route(LLMTaskIntent(task_kind="embed", strict_identity_required=True))

    assert route.provider == "ollama"
    assert route.model == "nomic-embed-text:latest"


def test_router_honors_model_id_only_chat_fallback(monkeypatch, clean_llm_env) -> None:
    bundle = SettingsBundle(
        llm_routing=LLMRoutingSettings(
            tasks={
                "plan": LLMRoutingSettings.TaskPolicy(
                    primary=LLMRoutingSettings.RouteTarget(provider="openai", model="gpt-4.1"),
                    fallback=LLMRoutingSettings.FallbackPolicy(
                        mode="allowed",
                        model_id="mock.chat",
                    ),
                )
            }
        )
    )
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: bundle)

    router = LLMRouter()
    described = router.describe_intent(LLMTaskIntent(task_kind="plan"))

    assert described["policy"]["fallback"]["model_id"] == "mock.chat"
    candidates = router._route_candidates(LLMTaskIntent(task_kind="plan"))
    assert any(route.provider == "mock" and route.model == "mock-chat" for route in candidates)


def test_router_honors_model_id_only_embedding_fallback(monkeypatch, clean_llm_env) -> None:
    clean_llm_env.setenv("EMBED_DIM", "8")
    bundle = SettingsBundle(
        llm_routing=LLMRoutingSettings(
            default_embedding=LLMRoutingSettings.TaskPolicy(
                primary=LLMRoutingSettings.RouteTarget(
                    model_id="mock.embed",
                ),
                fallback=LLMRoutingSettings.FallbackPolicy(
                    mode="allowed",
                    model_id="mock.embed",
                ),
                require_compatible_identity=True,
            )
        )
    )
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: bundle)

    router = LLMRouter()
    route = router.route(LLMTaskIntent(task_kind="embed", strict_identity_required=True))

    assert route.provider == "mock"
    assert route.model == "mock-embed"


def test_router_verification_intents_include_configured_tasks(monkeypatch, clean_llm_env) -> None:
    bundle = SettingsBundle(
        llm_routing=LLMRoutingSettings(
            tasks={
                "qa": LLMRoutingSettings.TaskPolicy(
                    primary=LLMRoutingSettings.RouteTarget(provider="openai", model="gpt-4.1-mini")
                )
            }
        )
    )
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: bundle)

    router = LLMRouter()
    intents = router.verification_intents()

    assert any(intent.task_kind == "qa" for intent in intents)
