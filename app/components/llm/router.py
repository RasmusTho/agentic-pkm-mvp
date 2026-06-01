from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from functools import lru_cache
from typing import Any, Iterable

from app.components.embeddings import EmbeddingIdentity, resolve_embedding_identity
from app.components.settings.models_loader import load_models
from app.settings.models import LLMRoutingSettings
from app.settings.runtime import get_settings_bundle


@dataclass(frozen=True)
class LLMTaskIntent:
    task_kind: str
    complexity_hint: str | None = None
    risk: str | None = None
    budget: str | None = None
    determinism_required: bool = False
    json_schema_required: bool = False
    latency_target_ms: int | None = None
    strict_identity_required: bool = False


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


@lru_cache(maxsize=1)
def _model_registry() -> dict[str, Any]:
    return load_models()


def _resolve_target_model_id(
    target: LLMRoutingSettings.RouteTarget | None,
    *,
    expected_kind: str,
) -> tuple[str | None, str | None]:
    if target is None or not target.model_id:
        return None, None
    descriptor = _model_registry().get(target.model_id)
    if descriptor is None or descriptor.kind != expected_kind:
        return None, None
    return descriptor.provider, descriptor.model


class LLMRouter:
    def __init__(self) -> None:
        self._llm_provider_env = os.getenv("LLM_PROVIDER") if "LLM_PROVIDER" in os.environ else None
        provider, degraded, reason = _resolve_provider(self._llm_provider_env)
        self._default_provider = provider
        self._default_degraded = degraded
        self._default_reason = reason
        try:
            self._settings = get_settings_bundle()
        except Exception:
            self._settings = None

    def _task_policy(self, intent: LLMTaskIntent) -> LLMRoutingSettings.TaskPolicy | None:
        if self._settings is None:
            return None
        routing = getattr(self._settings, "llm_routing", None)
        if routing is None:
            return None
        explicit = routing.tasks.get(intent.task_kind)
        if explicit is not None:
            return explicit
        if intent.task_kind == "embed":
            return routing.default_embedding
        if intent.task_kind in {"eval", "deepeval", "ragas"}:
            return routing.default_eval
        if "reason" in intent.task_kind or intent.task_kind in {"plan"}:
            return routing.default_reasoning
        return routing.default_chat

    @staticmethod
    def _route_to_dict(route: LLMRoute) -> dict[str, Any]:
        return {
            "provider": route.provider,
            "model": route.model,
            "mode": route.mode,
            "reason": route.reason,
            "degraded": route.degraded,
        }

    @staticmethod
    def _target_to_dict(target: LLMRoutingSettings.RouteTarget | None) -> dict[str, Any]:
        if target is None:
            return {}
        return {
            "model_id": target.model_id or "",
            "provider": target.provider or "",
            "model": target.model or "",
            "profile": target.profile or "",
        }

    @staticmethod
    def _fallback_to_dict(fallback: LLMRoutingSettings.FallbackPolicy | None) -> dict[str, Any]:
        if fallback is None:
            return {}
        return {
            "mode": fallback.mode,
            "model_id": fallback.model_id or "",
            "provider": fallback.provider or "",
            "model": fallback.model or "",
            "profile": fallback.profile or "",
        }

    def _resolve_chat_route(
        self,
        target: LLMRoutingSettings.RouteTarget | None,
        *,
        degraded: bool,
        reason: str,
    ) -> LLMRoute:
        target_provider, target_model = _resolve_target_model_id(target, expected_kind="chat")
        provider_source = None
        model_source = None
        routing = getattr(self._settings, "llm_routing", None) if self._settings is not None else None
        if target is not None:
            provider_source = target.provider or target_provider
            model_source = target.model or target_model
        provider_candidate = provider_source or self._llm_provider_env or getattr(routing, "default_provider", None)
        provider, provider_degraded, provider_reason = _resolve_provider(provider_candidate)
        model = (
            model_source
            or getattr(routing, "default_chat_model", None)
            or _default_chat_model()
        )
        return LLMRoute(
            provider=provider,
            model=model,
            mode="chat",
            reason=provider_reason if provider_degraded else reason,
            degraded=degraded or provider_degraded,
        )

    def _resolve_embedding_route(
        self,
        target: LLMRoutingSettings.RouteTarget | None,
        *,
        degraded: bool,
        reason: str,
    ) -> tuple[LLMRoute, EmbeddingIdentity]:
        routing = getattr(self._settings, "llm_routing", None) if self._settings is not None else None
        profile = None
        override_provider = None
        override_model = None
        target_provider, target_model = _resolve_target_model_id(target, expected_kind="embedding")
        if target is not None:
            profile = target.profile
            override_provider = target.provider or target_provider
            override_model = target.model or target_model
        if override_model is None and routing is not None:
            override_model = routing.default_embed_model
        if override_model is None:
            override_model = _default_embed_model()
        identity = resolve_embedding_identity(
            profile=profile,
            override_model=override_model,
            override_provider=override_provider,
        )
        return (
            LLMRoute(
                provider=identity.provider,
                model=override_model or identity.model,
                mode="embeddings",
                reason=reason,
                degraded=degraded,
            ),
            identity,
        )

    @staticmethod
    def _compatible_embedding_identity(primary: EmbeddingIdentity, fallback: EmbeddingIdentity) -> bool:
        return (
            primary.provider == fallback.provider
            and primary.model == fallback.model
            and primary.dim == fallback.dim
            and primary.normalize == fallback.normalize
        )

    def _default_fallback_target(
        self,
        intent: LLMTaskIntent,
        policy: LLMRoutingSettings.TaskPolicy | None,
    ) -> LLMRoutingSettings.RouteTarget | None:
        if policy is None:
            return None
        fallback = policy.fallback
        if fallback.mode == "never" or fallback.mode == "skip":
            return None
        if fallback.model_id or fallback.provider or fallback.model or fallback.profile:
            return LLMRoutingSettings.RouteTarget(
                model_id=fallback.model_id,
                provider=fallback.provider,
                model=fallback.model,
                profile=fallback.profile,
            )
        if intent.task_kind == "embed":
            return None
        if fallback.mode == "local":
            return LLMRoutingSettings.RouteTarget(provider="ollama")
        return LLMRoutingSettings.RouteTarget(provider="mock", model="mock")

    def _route_candidates(self, intent: LLMTaskIntent) -> list[LLMRoute]:
        policy = self._task_policy(intent)
        if intent.task_kind == "embed":
            primary_route, primary_identity = self._resolve_embedding_route(
                getattr(policy, "primary", None),
                degraded=self._default_degraded,
                reason="settings" if policy is not None else self._default_reason,
            )
            candidates = [primary_route]
            fallback_target = self._default_fallback_target(intent, policy)
            if fallback_target is not None:
                fallback_route, fallback_identity = self._resolve_embedding_route(
                    fallback_target,
                    degraded=True,
                    reason="fallback",
                )
                require_compatibility = bool(
                    intent.strict_identity_required or (policy and policy.require_compatible_identity)
                )
                if not require_compatibility or self._compatible_embedding_identity(primary_identity, fallback_identity):
                    candidates.append(fallback_route)
            return candidates

        primary_route = self._resolve_chat_route(
            getattr(policy, "primary", None),
            degraded=self._default_degraded,
            reason="settings" if policy is not None else self._default_reason,
        )
        candidates = [primary_route]
        fallback_target = self._default_fallback_target(intent, policy)
        if fallback_target is not None:
            candidates.append(
                self._resolve_chat_route(
                    fallback_target,
                    degraded=True,
                    reason="fallback",
                )
            )
        elif primary_route.provider != "mock":
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
        if intent.determinism_required and candidates and intent.task_kind != "embed":
            for cand in candidates:
                if cand.provider == "mock":
                    return LLMRoute(
                        provider=cand.provider,
                        model=cand.model,
                        mode=cand.mode,
                        reason="deterministic",
                        degraded=cand.degraded,
                    )
        routing = getattr(self._settings, "llm_routing", None) if self._settings is not None else None
        has_explicit_task_policy = bool(routing and intent.task_kind in routing.tasks)
        if self._llm_provider_env is not None and intent.task_kind != "embed" and not has_explicit_task_policy:
            provider, degraded, reason = _resolve_provider(self._llm_provider_env)
            selected = candidates[0]
            return LLMRoute(
                provider=provider,
                model=selected.model,
                mode=selected.mode,
                reason=reason if degraded else selected.reason,
                degraded=selected.degraded or degraded,
            )
        return candidates[0]

    def default_routes(self, intents: Iterable[LLMTaskIntent]) -> dict[str, LLMRoute]:
        routes: dict[str, LLMRoute] = {}
        for intent in intents:
            routes[intent.task_kind] = self.route(intent)
        return routes

    def verification_intents(self) -> list[LLMTaskIntent]:
        task_kinds: list[str] = ["embed", "decide", "plan", "eval"]
        routing = getattr(self._settings, "llm_routing", None) if self._settings is not None else None
        if routing is not None:
            for task_kind in routing.tasks.keys():
                if task_kind not in task_kinds:
                    task_kinds.append(task_kind)
        intents: list[LLMTaskIntent] = []
        for task_kind in task_kinds:
            policy = None
            if routing is not None:
                policy = routing.tasks.get(task_kind)
            strict_identity_required = bool(
                task_kind == "embed"
                or (policy is not None and policy.require_compatible_identity)
                or ("embed" in task_kind)
            )
            intents.append(
                LLMTaskIntent(
                    task_kind=task_kind,
                    strict_identity_required=strict_identity_required,
                )
            )
        return intents

    def describe_intent(self, intent: LLMTaskIntent) -> dict[str, Any]:
        policy = self._task_policy(intent)
        effective = self.route(intent)
        payload: dict[str, Any] = {
            "task_kind": intent.task_kind,
            "intent": asdict(intent),
            "effective": self._route_to_dict(effective),
            "configured_via": "settings" if policy is not None else "env",
        }

        if policy is None:
            payload["preferred"] = self._route_to_dict(effective)
            return payload

        if intent.task_kind == "embed":
            preferred_route, preferred_identity = self._resolve_embedding_route(
                policy.primary,
                degraded=self._default_degraded,
                reason="settings",
            )
            payload["preferred"] = self._route_to_dict(preferred_route)
            payload["embedding_identity"] = {
                "provider": preferred_identity.provider,
                "model": preferred_identity.model,
                "dim": preferred_identity.dim,
                "normalize": preferred_identity.normalize,
            }
        else:
            preferred_route = self._resolve_chat_route(
                policy.primary,
                degraded=self._default_degraded,
                reason="settings",
            )
            payload["preferred"] = self._route_to_dict(preferred_route)

        payload["policy"] = {
            "primary": self._target_to_dict(policy.primary),
            "fallback": self._fallback_to_dict(policy.fallback),
            "require_compatible_identity": bool(policy.require_compatible_identity),
        }
        return payload

    def describe_routes(self, intents: Iterable[LLMTaskIntent]) -> dict[str, dict[str, Any]]:
        return {intent.task_kind: self.describe_intent(intent) for intent in intents}


__all__ = ["LLMTaskIntent", "LLMRoute", "LLMRouter"]
