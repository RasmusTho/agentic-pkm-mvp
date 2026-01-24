from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from typing import List, Mapping, Optional

import httpx

from app.embedding_config import assert_embed_dim, get_embed_dim, l2_normalize

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _extract_error_detail(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, Mapping):
        if "error" in payload:
            err = payload.get("error")
            if isinstance(err, Mapping):
                detail = err.get("message") or err.get("error")
            else:
                detail = err
        else:
            detail = payload.get("message")
    else:
        detail = None
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    text = response.text.strip()
    if text:
        return text
    return None


def _normalize_ollama_url(url: str) -> str:
    clean = (url or "").rstrip("/")
    if clean.endswith("/v1"):
        clean = clean[:-3]
    return clean


OLLAMA_URL = _normalize_ollama_url(
    os.getenv("OLLAMA_URL", os.getenv("OLLAMA_HOST", "http://localhost:11434"))
)


def _ollama_base_url() -> str:
    return _normalize_ollama_url(OLLAMA_URL)


def get_embed_model() -> str:
    """Return the currently configured embedding model name."""
    return os.getenv("OLLAMA_EMBED_MODEL", os.getenv("EMBED_MODEL", "nomic-embed-text:latest"))


EMBED_MODEL = get_embed_model()


def _provider() -> str:
    return os.getenv("LLM_PROVIDER", "ollama").lower()


def get_embedding_provider() -> str:
    """Return the configured embedding provider."""
    return _provider()


def _mock_vector(text: str, *, dim: int) -> List[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    vec: list[float] = []
    for idx in range(dim):
        chunk = digest[idx % len(digest)]
        vec.append(((chunk / 255.0) * 2) - 1)
    return vec


def _normalize_embedding_candidate(candidate: object | None) -> list[float] | None:
    if candidate is None:
        return None
    if isinstance(candidate, (list, tuple)):
        if not candidate:
            return None
        first = candidate[0]
        if isinstance(first, (list, tuple)) and len(first) > 0 and all(isinstance(x, (int, float)) for x in first):
            return [float(x) for x in first]
        if all(isinstance(x, (int, float)) for x in candidate):
            return [float(x) for x in candidate]
    return None


def _extract_vector_from_payload(payload: Mapping[str, object]) -> list[float] | None:
    for key in ("embeddings", "embedding"):
        candidate = _normalize_embedding_candidate(payload.get(key))
        if candidate:
            return candidate
    data = payload.get("data")
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, Mapping):
                candidate = _normalize_embedding_candidate(entry.get("embedding"))
                if candidate:
                    return candidate
    return None


def _ollama_include_dimensions() -> bool:
    raw = os.getenv("OLLAMA_EMBED_DIMENSIONS")
    if raw is None:
        return True
    return raw.strip().lower() in _TRUE_VALUES


def _ollama_payload(text: str, model: str, dim: int) -> dict[str, object]:
    payload: dict[str, object] = {"model": model, "prompt": text}
    if _ollama_include_dimensions():
        payload["dimensions"] = dim
    return payload


def _parse_vector(payload: Mapping[str, object], *, provider: str, model: str, expected_dim: int | None) -> tuple[float, ...]:
    vector = _extract_vector_from_payload(payload)
    if not vector:
        raise ValueError(
            f"{provider} embedding response missing vectors (model={model}, expected_dim={expected_dim})"
        )
    assert_embed_dim(vector, expected=expected_dim, name="embedding")
    return tuple(vector)


def _ollama_embed_api(text: str, model: str, dim: int, timeout: float) -> tuple[float, ...]:
    payload = _ollama_payload(text, model, dim)
    base = _ollama_base_url()
    resp = httpx.post(f"{base}/api/embeddings", json=payload, timeout=timeout)
    if resp.is_error:
        detail = _extract_error_detail(resp)
        message = f"Ollama /api/embeddings returned HTTP {resp.status_code}"
        if detail:
            message = f"{message}: {detail}"
        raise httpx.HTTPStatusError(message, request=resp.request, response=resp)
    data = resp.json()
    if not isinstance(data, Mapping):
        raise ValueError("Ollama /api/embeddings returned an unexpected payload")
    return _parse_vector(data, provider="ollama", model=model, expected_dim=dim)


def _ollama_openai_fallback(text: str, model: str, dim: int, timeout: float) -> tuple[float, ...]:
    payload = {"model": model, "input": text}
    base = _ollama_base_url()
    resp = httpx.post(f"{base}/v1/embeddings", json=payload, timeout=timeout)
    if resp.is_error:
        detail = _extract_error_detail(resp)
        message = f"Ollama /v1/embeddings returned HTTP {resp.status_code}"
        if detail:
            message = f"{message}: {detail}"
        raise httpx.HTTPStatusError(message, request=resp.request, response=resp)
    data = resp.json()
    if not isinstance(data, Mapping):
        raise ValueError("Ollama fallback embeddings endpoint returned an unexpected payload")
    return _parse_vector(data, provider="ollama", model=model, expected_dim=dim)


@lru_cache(maxsize=2048)
def _embed_single(text: str, provider: str, model: str, dim: Optional[int]) -> tuple[float, ...]:
    if dim is None:
        dim = get_embed_dim()

    if not text:
        return tuple(0.0 for _ in range(dim))

    if provider == "mock":
        return tuple(_mock_vector(text, dim=dim))

    if provider == "ollama":
        timeout = float(os.getenv("LLM_TIMEOUT", "60"))
        try:
            return _ollama_embed_api(text, model, dim, timeout)
        except httpx.HTTPError as primary_exc:
            try:
                return _ollama_openai_fallback(text, model, dim, timeout)
            except httpx.HTTPError as fallback_exc:
                raise RuntimeError(
                    f"Ollama embedding requests failed (model={model}, expected_dim={dim}). "
                    f"Primary error: {primary_exc}; fallback: {fallback_exc}"
                ) from fallback_exc
        except ValueError as exc:
            raise ValueError(
                f"Ollama embedding parsing failed (model={model}, expected_dim={dim}): {exc}"
            ) from exc

    raise ValueError(f"Unsupported embedding provider: {provider}")


def embed_text(
    text: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    dim: int | None = None,
    normalize: bool = True,
) -> List[float]:
    provider_val = provider or _provider()
    model_val = model or get_embed_model()
    dim_val = dim or get_embed_dim()
    vector = list(_embed_single(text, provider_val, model_val, dim_val))
    if normalize:
        return l2_normalize(vector)
    return vector


def embed_texts(
    texts: List[str],
    *,
    provider: str | None = None,
    model: str | None = None,
    dim: int | None = None,
    normalize: bool = True,
) -> List[List[float]]:
    return [embed_text(text, provider=provider, model=model, dim=dim, normalize=normalize) for text in texts]


__all__ = ["embed_text", "embed_texts", "EMBED_MODEL", "get_embedding_provider", "get_embed_model"]
