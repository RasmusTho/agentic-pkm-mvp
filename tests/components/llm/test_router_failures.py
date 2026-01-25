from __future__ import annotations

import pytest

from app.components.llm.router import LLMRouter, LLMTaskIntent


def test_router_degrades_to_mock_on_invalid_provider(clean_llm_env) -> None:
    """
    Router MUST degrade to mock when provider is invalid.

    See: docs/LLM_ROUTING.md §Future: task-aware routing
    """
    clean_llm_env.setenv("LLM_PROVIDER", "nonexistent-provider")
    router = LLMRouter()
    route = router.route(LLMTaskIntent(task_kind="decide"))

    assert route.provider == "mock", "Should degrade to mock"
    assert route.degraded is True, "Should flag degradation"
    assert "invalid" in route.reason.lower() or "unknown" in route.reason.lower()


def test_router_handles_empty_provider_env(clean_llm_env) -> None:
    """Router MUST handle empty string provider gracefully.

    See: docs/LLM_ROUTING.md §Supported environment variables
    """
    clean_llm_env.setenv("LLM_PROVIDER", "")
    router = LLMRouter()
    route = router.route(LLMTaskIntent(task_kind="decide"))
    assert route.provider == "mock"
    assert route.degraded is False


def test_router_handles_malformed_intent() -> None:
    """Router MUST validate LLMTaskIntent structure.

    See: docs/LLM_ROUTING.md §Configuration precedence
    """
    router = LLMRouter()
    with pytest.raises((ValueError, TypeError)):
        router.route(None)  # type: ignore[arg-type]
