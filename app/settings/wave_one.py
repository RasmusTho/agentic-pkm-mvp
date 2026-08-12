"""SETTINGS-07A production resolution for LLM and rerank controls.

The vault-backed bundle is the normal authority.  The named environment variables
remain deliberately narrow, one-release bootstrap overrides; keeping the precedence
in one module prevents consumers from recreating their own fallback ladders.
"""

from __future__ import annotations

import os

from app.settings.env_defaults import env_default
from app.settings.locations import CANONICAL_SETTINGS_DIR_NAME
from app.settings.models import LLMRoutingSettings
from app.settings.runtime import get_settings_bundle
from app.settings.tiering import is_lab_profile


def _override(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


def _vault_shared_origin(relative_path: str) -> str:
    """Format canonical provenance without introducing a second path authority."""
    return f"vault-shared:{CANONICAL_SETTINGS_DIR_NAME}/{relative_path}"


def _normalized_provider(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized == "llm":
        return "ollama"
    if normalized == "fake":
        return "mock"
    return normalized


def _configured(routing: object, *keys: str) -> bool:
    configured = getattr(routing, "configured_keys", ())
    return any(key in configured for key in keys)


def llm_timeout_seconds(routing: LLMRoutingSettings | None = None) -> float:
    raw = _override("LLM_TIMEOUT")
    if raw is not None:
        return float(raw)
    effective_routing = routing or get_settings_bundle().llm_routing
    return effective_routing.timeout_seconds


def llm_temperature(routing: LLMRoutingSettings | None = None) -> float:
    raw = _override("LLM_TEMPERATURE")
    if raw is not None:
        return float(raw)
    if not is_lab_profile():
        return float(env_default("LLM_TEMPERATURE"))
    effective_routing = routing or get_settings_bundle().llm_routing
    return effective_routing.temperature


def _reasoning_resolution(
    selected_provider: str | None = None,
    routing: LLMRoutingSettings | None = None,
) -> tuple[str, str]:
    raw = _override("REASONING_MODEL")
    if raw is not None:
        return raw, "env:REASONING_MODEL (deprecated)"
    effective_routing = routing or get_settings_bundle().llm_routing
    route = effective_routing.default_reasoning.primary
    provider = _normalized_provider(selected_provider or _override("LLM_PROVIDER") or "ollama")
    route_provider = _normalized_provider(route.provider)
    if (
        route.model
        and route_provider
        and route_provider == provider
        and _configured(effective_routing, "default_reasoning")
    ):
        route_model = route.model
        return route_model, _vault_shared_origin("llm_routing.md")
    if effective_routing.reasoning_model and _configured(
        effective_routing, "reasoning_model"
    ):
        return effective_routing.reasoning_model, _vault_shared_origin("llm_routing.md")
    return env_default("REASONING_MODEL"), "registry default"


def reasoning_model(selected_provider: str | None = None) -> str:
    return _reasoning_resolution(selected_provider)[0]


def _default_chat_resolution(
    selected_provider: str | None = None,
    routing: LLMRoutingSettings | None = None,
) -> tuple[str, str]:
    """Resolve one provider-compatible model and its effective origin."""
    raw = _override("LLM_MODEL") or _override("MERGE_LLM_MODEL")
    if raw is not None:
        origin_key = "LLM_MODEL" if _override("LLM_MODEL") is not None else "MERGE_LLM_MODEL"
        return raw, f"env:{origin_key} (deprecated)"
    effective_routing = routing or get_settings_bundle().llm_routing
    route = effective_routing.default_chat.primary
    provider = _normalized_provider(selected_provider or _override("LLM_PROVIDER") or "mock")
    route_provider = _normalized_provider(route.provider)
    if route.model and route_provider and route_provider == provider:
        origin = (
            _vault_shared_origin("llm_routing.md")
            if _configured(effective_routing, "default_chat")
            else "registry default"
        )
        return route.model, origin
    configured_default_provider = _normalized_provider(effective_routing.default_provider)
    if (
        effective_routing.default_chat_model
        and _configured(effective_routing, "default_chat_model")
        and _configured(effective_routing, "default_provider")
        and configured_default_provider
        and configured_default_provider == provider
    ):
        return effective_routing.default_chat_model, _vault_shared_origin("llm_routing.md")
    return env_default("MERGE_LLM_MODEL"), "registry default"


def default_chat_model(selected_provider: str | None = None) -> str:
    """Resolve the legacy service caller's model without crossing providers."""
    return _default_chat_resolution(selected_provider)[0]


def wave_one_explain() -> dict[str, dict[str, object]]:
    """Safe, explicit origin/tier evidence for migrated SETTINGS-07A keys."""
    from app.retrieval.tuning import get_effective_retrieval_resolution

    effective_retrieval = get_effective_retrieval_resolution()
    routing = get_settings_bundle().llm_routing
    reasoning_value, reasoning_origin = _reasoning_resolution(routing=routing)
    default_chat_value, default_chat_origin = _default_chat_resolution(routing=routing)
    return {
        "llm.timeout_seconds": {
            "value": llm_timeout_seconds(routing),
            "origin": (
                "env:LLM_TIMEOUT (deprecated)"
                if _override("LLM_TIMEOUT")
                else (
                    _vault_shared_origin("llm_routing.md")
                    if _configured(routing, "timeout_seconds")
                    else "registry default"
                )
            ),
            "tier": "operator",
        },
        "llm.temperature": {
            "value": llm_temperature(routing),
            "origin": (
                "env:LLM_TEMPERATURE (deprecated)"
                if _override("LLM_TEMPERATURE")
                else (
                    _vault_shared_origin("llm_routing.md")
                    if is_lab_profile() and _configured(routing, "temperature")
                    else "registry default (operator profile)"
                    if not is_lab_profile()
                    else "registry default"
                )
            ),
            "tier": "lab",
        },
        "llm.reasoning_model": {
            "value": reasoning_value,
            "origin": reasoning_origin,
            "tier": "operator",
        },
        "llm.default_chat_model": {
            "value": default_chat_value,
            "origin": default_chat_origin,
            "tier": "operator",
        },
        "retrieval.rerank.provider": {
            "value": effective_retrieval.rerank_provider.value,
            "origin": effective_retrieval.rerank_provider.origin,
            "tier": effective_retrieval.rerank_provider.tier,
        },
        "retrieval.rerank": {
            "value": effective_retrieval.rerank.value,
            "origin": effective_retrieval.rerank.origin,
            "tier": effective_retrieval.rerank.tier,
        },
        "retrieval.rerank.top_k": {
            "value": effective_retrieval.rerank_top_k.value,
            "origin": effective_retrieval.rerank_top_k.origin,
            "tier": effective_retrieval.rerank_top_k.tier,
        },
    }
