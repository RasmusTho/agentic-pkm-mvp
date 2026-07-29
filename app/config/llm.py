from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_ACTIVE_PROVIDER: str | None = None


def _normalize_provider(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().lower()


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _log_provider_info(provider: str) -> None:
    model = os.getenv("LLM_MODEL") or os.getenv("OLLAMA_MODEL") or os.getenv("EMBED_MODEL")
    embed_model = os.getenv("EMBED_MODEL") or os.getenv("OLLAMA_EMBED_MODEL")
    embed_dim = os.getenv("EMBED_DIM")
    store_backend = os.getenv("STORE_BACKEND") or "memory"
    logger.info(
        "llm resolved provider=%s model=%s embed_model=%s embed_dim=%s store_backend=%s",
        provider,
        model or "<unset>",
        embed_model or "<unset>",
        embed_dim or "<unset>",
        store_backend,
    )


def ensure_provider() -> str:
    global _ACTIVE_PROVIDER
    candidate = _normalize_provider(os.getenv("LLM_PROVIDER"))
    enforce = _env_flag("LLM_PROVIDER_ENFORCE", default=False)

    if candidate is None:
        if enforce:
            raise RuntimeError(
                "LLM_PROVIDER is required when LLM_PROVIDER_ENFORCE=1; "
                "export LLM_PROVIDER=ollama (plus any model/endpoint vars) or LLM_PROVIDER=mock for deterministic runs."
            )
        candidate = "mock"

    if _ACTIVE_PROVIDER == candidate:
        return _ACTIVE_PROVIDER

    _ACTIVE_PROVIDER = candidate
    _log_provider_info(candidate)
    return candidate


def get_provider() -> str:
    return ensure_provider()
