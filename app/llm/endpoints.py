from __future__ import annotations

import os


_OLLAMA_ENV_KEYS = ("OLLAMA_BASE_URL", "OLLAMA_URL", "OLLAMA_HOST")
_OLLAMA_FALLBACK_ENV_KEYS = _OLLAMA_ENV_KEYS + ("OPENAI_BASE_URL",)


def normalize_ollama_url(url: str) -> str:
    clean = (url or "").rstrip("/")
    if clean.endswith("/v1"):
        clean = clean[:-3]
    return clean


def resolve_ollama_base_url(*, strip_v1: bool = False, include_openai_fallback: bool = True) -> str:
    base_url = ""
    keys = _OLLAMA_FALLBACK_ENV_KEYS if include_openai_fallback else _OLLAMA_ENV_KEYS
    for key in keys:
        value = os.getenv(key, "").strip()
        if value:
            base_url = value
            break
    if strip_v1:
        return normalize_ollama_url(base_url)
    return base_url.rstrip("/")


def require_ollama_base_url(
    *, strip_v1: bool = False, include_openai_fallback: bool = True, context: str = "ollama"
) -> str:
    base_url = resolve_ollama_base_url(strip_v1=strip_v1, include_openai_fallback=include_openai_fallback)
    if base_url:
        return base_url
    keys = ", ".join(_OLLAMA_FALLBACK_ENV_KEYS if include_openai_fallback else _OLLAMA_ENV_KEYS)
    raise RuntimeError(f"{keys} is required for {context}")


__all__ = ["normalize_ollama_url", "resolve_ollama_base_url", "require_ollama_base_url"]
