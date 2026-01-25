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


_KNOWN_PROVIDERS = {"mock", "ollama", "openai", "deepseek"}


def _normalize_provider(value: str | None) -> str:
    normalized = _normalize(value)
    if normalized == "llm":
        return "ollama"
    if normalized == "fake":
        return "mock"
    return normalized


def _resolve_provider(value: str | None) -> tuple[str, bool, str]:
    normalized = _normalize_provider(value)
    if not normalized:
        return "mock", False, "default"
    if normalized not in _KNOWN_PROVIDERS:
        return "mock", True, f"invalid provider: {normalized}"
    return normalized, False, "default"


def _default_chat_model() -> str:
    return os.getenv("LLM_MODEL", os.getenv("MERGE_LLM_MODEL", "llama3.1:8b"))


def _default_embed_model() -> str:
    return os.getenv("EMBED_MODEL", os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text:latest"))


def _default_mode(task_kind: str) -> str:
    return "embeddings" if task_kind == "embed" else "chat"


class LLMRouter:
    def __init__(self) -> None:
        provider, degraded, reason = _resolve_provider(os.getenv("LLM_PROVIDER"))
        self._default_provider = provider
        self._default_degraded = degraded
        self._default_reason = reason

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
            reason=self._default_reason,
            degraded=self._default_degraded,
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
        if not isinstance(intent, LLMTaskIntent):
            raise TypeError("intent must be an LLMTaskIntent")
        forced_provider = os.getenv("LLM_FORCE_PROVIDER")
        forced_model = os.getenv("LLM_FORCE_MODEL")
        if forced_provider or forced_model:
            if forced_provider:
                normalized = _normalize_provider(forced_provider)
                if normalized and normalized not in _KNOWN_PROVIDERS:
                    provider = "mock"
                    degraded = True
                    reason = f"invalid provider: {normalized}"
                else:
                    provider = normalized or self._default_provider
                    degraded = False
                    reason = "forced"
            else:
                provider = self._default_provider
                degraded = self._default_degraded
                reason = "forced" if not degraded else self._default_reason
            model = forced_model or (
                _default_embed_model() if intent.task_kind == "embed" else _default_chat_model()
            )
            return LLMRoute(
                provider=provider,
                model=model,
                mode=_default_mode(intent.task_kind),
                reason=reason,
                degraded=degraded,
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
