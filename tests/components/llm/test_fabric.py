from __future__ import annotations

from app.components.llm.fabric import LLMRoute, LLMTaskIntent, get_embeddings_client


def test_get_embeddings_client_uses_router_route_even_when_llm_provider_is_set(monkeypatch) -> None:
    class _Router:
        def route(self, _intent: LLMTaskIntent) -> LLMRoute:
            return LLMRoute(
                provider="ollama",
                model="nomic-embed-text:latest",
                mode="embeddings",
                reason="settings",
            )

    captured: dict[str, str | None] = {}

    def _fake_get_embedding_client(*, override_provider=None, override_model=None):
        captured["provider"] = override_provider
        captured["model"] = override_model
        return object()

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("EMBED_PROVIDER", raising=False)
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    monkeypatch.setattr("app.components.llm.fabric.LLMRouter", _Router)
    monkeypatch.setattr("app.components.llm.fabric.get_embedding_client", _fake_get_embedding_client)

    get_embeddings_client(LLMTaskIntent(task_kind="embed", strict_identity_required=True))

    assert captured == {"provider": "ollama", "model": "nomic-embed-text:latest"}
