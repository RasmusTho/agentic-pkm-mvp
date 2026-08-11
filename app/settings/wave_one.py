"""SETTINGS-07A production resolution for LLM and rerank controls.

The vault-backed bundle is the normal authority.  The named environment variables
remain deliberately narrow, one-release bootstrap overrides; keeping the precedence
in one module prevents consumers from recreating their own fallback ladders.
"""

from __future__ import annotations

import os

from app.settings.env_defaults import env_default
from app.settings.locations import CANONICAL_SETTINGS_DIR_NAME
from app.settings.runtime import get_settings_bundle
from app.settings.tiering import is_lab_profile


def _override(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


def _vault_shared_origin(relative_path: str) -> str:
    """Format canonical provenance without introducing a second path authority."""
    return f"vault-shared:{CANONICAL_SETTINGS_DIR_NAME}/{relative_path}"


def llm_timeout_seconds() -> float:
    raw = _override("LLM_TIMEOUT")
    if raw is not None:
        return float(raw)
    return get_settings_bundle().llm_routing.timeout_seconds


def llm_temperature() -> float:
    raw = _override("LLM_TEMPERATURE")
    if raw is not None:
        return float(raw)
    if not is_lab_profile():
        return float(env_default("LLM_TEMPERATURE"))
    return get_settings_bundle().llm_routing.temperature


def reasoning_model() -> str:
    raw = _override("REASONING_MODEL")
    if raw is not None:
        return raw
    configured = get_settings_bundle().llm_routing.reasoning_model
    return configured or env_default("REASONING_MODEL")


def default_chat_model() -> str:
    """Resolve the legacy service caller's model without bypassing the spine."""
    raw = _override("LLM_MODEL") or _override("MERGE_LLM_MODEL")
    if raw is not None:
        return raw
    routing = get_settings_bundle().llm_routing
    return routing.default_chat.primary.model or routing.default_chat_model or env_default("MERGE_LLM_MODEL")


def rerank_provider() -> str:
    raw = _override("RERANK_PROVIDER")
    if raw is not None:
        return raw
    if not is_lab_profile():
        return env_default("RERANK_PROVIDER")
    return get_settings_bundle().retrieval_tuning.rerank_provider


def wave_one_explain() -> dict[str, dict[str, object]]:
    """Safe, explicit origin/tier evidence for migrated SETTINGS-07A keys."""
    from app.retrieval.tuning import get_retrieval_tuning

    effective_retrieval = get_retrieval_tuning()
    return {
        "llm.timeout_seconds": {
            "value": llm_timeout_seconds(),
            "origin": "env:LLM_TIMEOUT (deprecated)" if _override("LLM_TIMEOUT") else _vault_shared_origin("llm_routing.md"),
            "tier": "operator",
        },
        "llm.temperature": {
            "value": llm_temperature(),
            "origin": "env:LLM_TEMPERATURE (deprecated)" if _override("LLM_TEMPERATURE") else (_vault_shared_origin("llm_routing.md") if is_lab_profile() else "registry default (operator profile)"),
            "tier": "lab",
        },
        "llm.reasoning_model": {
            "value": reasoning_model(),
            "origin": "env:REASONING_MODEL (deprecated)" if _override("REASONING_MODEL") else _vault_shared_origin("llm_routing.md"),
            "tier": "operator",
        },
        "llm.default_chat_model": {
            "value": default_chat_model(),
            "origin": "env:LLM_MODEL (deprecated)" if _override("LLM_MODEL") else ("env:MERGE_LLM_MODEL (deprecated)" if _override("MERGE_LLM_MODEL") else _vault_shared_origin("llm_routing.md")),
            "tier": "operator",
        },
        "retrieval.rerank.provider": {
            "value": rerank_provider(),
            "origin": "env:RERANK_PROVIDER (deprecated)" if _override("RERANK_PROVIDER") else (_vault_shared_origin("retrieval.md") if is_lab_profile() else "registry default (operator profile)"),
            "tier": "lab",
        },
        "retrieval.rerank.top_k": {
            "value": effective_retrieval.rerank_top_k,
            "origin": "env:RERANK_TOP_K (deprecated)" if _override("RERANK_TOP_K") else _vault_shared_origin("retrieval.md"),
            "tier": "lab",
        },
    }
