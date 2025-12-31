from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Iterable


@dataclass(frozen=True)
class LLMTaskIntent:
    task_kind: str
    complexity_hint: str | None = None
    risk: str | None = None
    budget: str | None = None
    determinism_required: bool = False
    json_schema_required: bool = False
    latency_target_ms: int | None = None


@dataclass(frozen=True)
class LLMRoute:
    provider: str
    model: str
    mode: str
    reason: str
    degraded: bool = False


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lower()


def _default_provider() -> str:
    raw = os.getenv("LLM_PROVIDER")
    value = _normalize(raw)
    if not value:
        return "mock"
    if value == "llm":
        return "ollama"
    return value


def _default_chat_model() -> str:
    return os.getenv("LLM_MODEL", os.getenv("MERGE_LLM_MODEL", "llama3.1:8b"))


def _default_embed_model() -> str:
    return os.getenv("EMBED_MODEL", os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text:latest"))


def _default_mode(task_kind: str) -> str:
    return "embeddings" if task_kind == "embed" else "chat"


class LLMRouter:
    def __init__(self) -> None:
        self._default_provider = _default_provider()

    def _route_candidates(self, intent: LLMTaskIntent) -> list[LLMRoute]:
        provider = self._default_provider
        if intent.task_kind == "embed":
            model = _default_embed_model()
        else:
            model = _default_chat_model()
        route = LLMRoute(
            provider=provider,
            model=model,
            mode=_default_mode(intent.task_kind),
            reason="default",
            degraded=False,
        )
        candidates = [route]
        if provider != "mock":
            candidates.append(
                LLMRoute(
                    provider="mock",
                    model="mock",
                    mode=_default_mode(intent.task_kind),
                    reason="fallback",
                    degraded=True,
                )
            )
        return candidates

    def route(self, intent: LLMTaskIntent) -> LLMRoute:
        forced_provider = os.getenv("LLM_FORCE_PROVIDER")
        forced_model = os.getenv("LLM_FORCE_MODEL")
        if forced_provider or forced_model:
            provider = _normalize(forced_provider) or self._default_provider
            model = forced_model or (
                _default_embed_model() if intent.task_kind == "embed" else _default_chat_model()
            )
            return LLMRoute(
                provider=provider,
                model=model,
                mode=_default_mode(intent.task_kind),
                reason="forced",
                degraded=False,
            )

        candidates = self._route_candidates(intent)
        if intent.determinism_required and candidates:
            for cand in candidates:
                if cand.provider == "mock":
                    return LLMRoute(
                        provider=cand.provider,
                        model=cand.model,
                        mode=cand.mode,
                        reason="deterministic",
                        degraded=cand.degraded,
                    )
        return candidates[0]

    def default_routes(self, intents: Iterable[LLMTaskIntent]) -> dict[str, LLMRoute]:
        routes: dict[str, LLMRoute] = {}
        for intent in intents:
            routes[intent.task_kind] = self.route(intent)
        return routes


__all__ = ["LLMTaskIntent", "LLMRoute", "LLMRouter"]
