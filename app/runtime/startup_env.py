from __future__ import annotations

from typing import Mapping, Sequence

_ANY_OF_OLLAMA = ["OLLAMA_BASE_URL", "OLLAMA_URL", "OLLAMA_HOST", "OPENAI_BASE_URL"]


def normalize_provider(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized == "llm":
        return "ollama"
    return normalized or None


def required_endpoint_vars(provider: str | None) -> list[str]:
    normalized = normalize_provider(provider)
    if normalized == "mock":
        return []
    if normalized == "ollama":
        return list(_ANY_OF_OLLAMA)
    return ["OPENAI_BASE_URL"]


def _has_any(env: Mapping[str, str], keys: Sequence[str]) -> bool:
    return any(env.get(key) for key in keys)


def validate_llm_env(env: Mapping[str, str]) -> dict[str, object]:
    provider = normalize_provider(env.get("LLM_PROVIDER"))
    missing_any_of: list[list[str]] = []
    missing_all_of: list[str] = []

    endpoints = required_endpoint_vars(provider)
    if provider == "ollama":
        if endpoints and not _has_any(env, endpoints):
            missing_any_of.append(endpoints)
    else:
        for key in endpoints:
            if not env.get(key):
                missing_all_of.append(key)

    if not env.get("LLM_MODEL"):
        missing_all_of.append("LLM_MODEL")

    ok = not missing_any_of and not missing_all_of
    return {
        "provider": provider,
        "missing_any_of": missing_any_of,
        "missing_all_of": missing_all_of,
        "ok": ok,
    }


__all__ = [
    "normalize_provider",
    "required_endpoint_vars",
    "validate_llm_env",
]
