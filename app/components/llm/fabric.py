from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.components.embeddings import EmbeddingClientProtocol, get_embedding_client
from app.components.llm.router import LLMRouter, LLMRoute, LLMTaskIntent
from app.services.llm import call_llm


@dataclass(frozen=True)
class ChatClient:
    route: LLMRoute

    def chat(
        self,
        name: str,
        pack: dict[str, Any],
        *,
        agent: str | None = None,
        kind: str | None = None,
        trace_id: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        return call_llm(
            name,
            pack,
            agent=agent,
            kind=kind,
            trace_id=trace_id,
            provider_override=self.route.provider,
            model_override=self.route.model,
            max_tokens=max_tokens,
        )


def get_chat_client(intent: LLMTaskIntent) -> ChatClient:
    router = LLMRouter()
    route = router.route(intent)
    return ChatClient(route=route)


def get_embeddings_client(intent: LLMTaskIntent) -> EmbeddingClientProtocol:
    router = LLMRouter()
    route = router.route(intent)
    return get_embedding_client(override_model=route.model, override_provider=route.provider)


def describe_default_routes() -> dict[str, dict[str, str]]:
    router = LLMRouter()
    intents = [
        LLMTaskIntent(task_kind="embed", determinism_required=True),
        LLMTaskIntent(task_kind="decide"),
        LLMTaskIntent(task_kind="plan"),
    ]
    routes = router.default_routes(intents)
    return {
        key: {
            "provider": route.provider,
            "model": route.model,
            "mode": route.mode,
            "reason": route.reason,
            "degraded": str(route.degraded),
        }
        for key, route in routes.items()
    }


__all__ = ["LLMTaskIntent", "LLMRoute", "ChatClient", "get_chat_client", "get_embeddings_client", "describe_default_routes"]
