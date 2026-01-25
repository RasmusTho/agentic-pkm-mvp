from __future__ import annotations

import pytest

from app.components.llm.router import LLMRouter, LLMTaskIntent


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
    clean_llm_env.setenv("LLM_PROVIDER", "mock")
    clean_llm_env.setenv("LLM_MODEL", "llama-test")
    clean_llm_env.setenv("EMBED_MODEL", "embed-test")

    router = LLMRouter()
    decide = router.route(LLMTaskIntent(task_kind="decide"))
    embed = router.route(LLMTaskIntent(task_kind="embed", determinism_required=True))

    assert decide.provider == "mock"
    assert decide.model == "llama-test"
    assert decide.mode == "chat"

    assert embed.provider == "mock"
    assert embed.model == "embed-test"
    assert embed.mode == "embeddings"


def test_router_forces_mock_for_determinism(clean_llm_env) -> None:
    """
    Router MUST force mock when determinism_required=True.

    Validates: docs/LLM_ROUTING.md §Deterministic routing
    """
    clean_llm_env.setenv("LLM_PROVIDER", "ollama")
    clean_llm_env.setenv("LLM_MODEL", "llama3.1:8b")
    clean_llm_env.setenv("EMBED_MODEL", "nomic-embed-text:latest")

    router = LLMRouter()
    embed = router.route(LLMTaskIntent(task_kind="embed", determinism_required=True))

    assert embed.provider == "mock"
    assert embed.reason == "deterministic"


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
