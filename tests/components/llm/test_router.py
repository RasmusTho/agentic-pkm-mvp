from __future__ import annotations

from app.components.llm.router import LLMRouter, LLMTaskIntent


def test_router_respects_env_defaults(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MODEL", "llama-test")
    monkeypatch.setenv("EMBED_MODEL", "embed-test")
    monkeypatch.delenv("LLM_FORCE_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_FORCE_MODEL", raising=False)

    router = LLMRouter()
    decide = router.route(LLMTaskIntent(task_kind="decide"))
    embed = router.route(LLMTaskIntent(task_kind="embed", determinism_required=True))

    assert decide.provider == "mock"
    assert decide.model == "llama-test"
    assert decide.mode == "chat"

    assert embed.provider == "mock"
    assert embed.model == "embed-test"
    assert embed.mode == "embeddings"


def test_router_forces_mock_for_determinism(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MODEL", "llama3.1:8b")
    monkeypatch.setenv("EMBED_MODEL", "nomic-embed-text:latest")
    monkeypatch.delenv("LLM_FORCE_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_FORCE_MODEL", raising=False)

    router = LLMRouter()
    embed = router.route(LLMTaskIntent(task_kind="embed", determinism_required=True))

    assert embed.provider == "mock"
    assert embed.reason == "deterministic"


def test_router_force_overrides(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MODEL", "llama3.1:8b")
    monkeypatch.setenv("LLM_FORCE_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_FORCE_MODEL", "custom-model")

    router = LLMRouter()
    route = router.route(LLMTaskIntent(task_kind="plan"))

    assert route.provider == "ollama"
    assert route.model == "custom-model"
    assert route.reason == "forced"


def test_router_force_override_beats_determinism(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("EMBED_MODEL", "nomic-embed-text:latest")
    monkeypatch.setenv("LLM_FORCE_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_FORCE_MODEL", "forced-embed")

    router = LLMRouter()
    embed = router.route(LLMTaskIntent(task_kind="embed", determinism_required=True))

    assert embed.provider == "ollama"
    assert embed.model == "forced-embed"
    assert embed.reason == "forced"
