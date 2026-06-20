from __future__ import annotations

import hashlib
import logging
import os
from functools import lru_cache
from typing import Callable, List, Mapping, Optional

import httpx

from app.config.llm import get_provider
from app.embedding_config import assert_embed_dim, get_embed_dim, l2_normalize
from app.llm.endpoints import require_ollama_base_url

logger = logging.getLogger(__name__)

_TRUE_VALUES = {"1", "true", "yes", "on"}
_MOCK_EMBED_MODEL = "mock-embedding"

# ProviderAdapter: a callable with the signature
#   (text: str, *, model: str, dim: int, timeout: float) -> tuple[float, ...]
ProviderAdapter = Callable[..., tuple[float, ...]]


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

def _ollama_base_url() -> str:
    return require_ollama_base_url(strip_v1=True, context="embeddings")


def get_embed_model() -> str:
    """Return the currently configured embedding model name."""
    model = os.getenv("OLLAMA_EMBED_MODEL", os.getenv("EMBED_MODEL", "")).strip()
    if not model:
        raise RuntimeError("OLLAMA_EMBED_MODEL or EMBED_MODEL is required for embeddings")
    return model


EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", os.getenv("EMBED_MODEL", "")).strip()


def _provider() -> str:
    return get_provider()


def get_embedding_provider() -> str:
    """Return the configured embedding provider."""
    return _provider()


def get_primary_provider() -> str:
    """Return the primary embedding provider.

    Precedence: EMBED_PRIMARY_PROVIDER env var > LLM_PROVIDER (via get_provider()).
    This is the provider used for normal embedding dispatch.
    """
    raw = os.getenv("EMBED_PRIMARY_PROVIDER", "").strip()
    if raw:
        return raw.lower()
    return get_provider()


def get_fallback_provider() -> str | None:
    """Return the fallback embedding provider, or None when unset.

    Reads EMBED_FALLBACK_PROVIDER env var. Returns None when unset.
    The fallback is declared here for task-5 (fallback orchestration) to read;
    this task does not invoke it at runtime.
    """
    raw = os.getenv("EMBED_FALLBACK_PROVIDER", "").strip()
    if raw:
        return raw.lower()
    return None


def _mock_vector(text: str, *, dim: int) -> List[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    vec: list[float] = []
    for idx in range(dim):
        chunk = digest[idx % len(digest)]
        vec.append(((chunk / 255.0) * 2) - 1)
    return vec


def _mock_embed_one(text: str, *, model: str, dim: int, timeout: float) -> tuple[float, ...]:
    """Provider adapter for the mock embedding provider.

    Returns a deterministic hash-derived vector. The ``model`` and ``timeout``
    parameters are accepted for API uniformity but are not used.
    """
    return tuple(_mock_vector(text, dim=dim))


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


def _embedding_max_input_chars() -> int:
    """Character budget per embedding request, bounding text to the embedding
    model's context window.

    ``nomic-embed-text`` has a ~2048-token window. Sending a whole oversized
    note returns HTTP 500 ("the input length exceeds the context length"),
    which aborts the entire embed batch and the retrieval index build for the
    whole vault (#2110). A conservative character budget keeps each request in
    window; oversized notes are split and mean-pooled rather than truncated, so
    no tail content is dropped from retrieval. Set ``EMBED_MAX_INPUT_CHARS=0``
    to disable chunking.
    """
    raw = os.getenv("EMBED_MAX_INPUT_CHARS")
    if raw is None:
        return 6000
    try:
        value = int(raw)
    except ValueError:
        return 6000
    return max(0, value)


def _chunk_for_embedding(text: str, max_chars: int) -> List[str]:
    if max_chars <= 0 or len(text) <= max_chars:
        return [text]
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]


def _mean_pool(vectors: List[tuple[float, ...]], dim: int) -> tuple[float, ...]:
    if not vectors:
        return tuple(0.0 for _ in range(dim))
    if len(vectors) == 1:
        return vectors[0]
    count = len(vectors)
    summed = [0.0] * dim
    for vec in vectors:
        for i in range(dim):
            summed[i] += vec[i]
    return tuple(value / count for value in summed)


def _ollama_embed_one(text: str, *, model: str, dim: int, timeout: float) -> tuple[float, ...]:
    """Provider adapter for the Ollama embedding provider.

    Attempts /api/embeddings first; falls back to /v1/embeddings on HTTP error.
    Matches the ProviderAdapter signature so it can be registered in PROVIDER_REGISTRY.
    """
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


# Registry mapping provider name -> adapter callable.
# Each adapter has signature: (text: str, *, model: str, dim: int, timeout: float) -> tuple[float, ...]
# To add a new provider, register it here — no changes to _embed_single required.
PROVIDER_REGISTRY: dict[str, ProviderAdapter] = {
    "mock": _mock_embed_one,
    "ollama": _ollama_embed_one,
    # Gemini adapter registered here by EMBEDREL-04:
    # "gemini": _gemini_embed_one,
}


@lru_cache(maxsize=2048)
def _embed_single(text: str, provider: str, model: str, dim: Optional[int]) -> tuple[float, ...]:
    if dim is None:
        dim = get_embed_dim()

    if not text:
        return tuple(0.0 for _ in range(dim))

    adapter = PROVIDER_REGISTRY.get(provider)
    if adapter is None:
        raise ValueError(f"Unsupported embedding provider: {provider!r}")

    timeout = float(os.getenv("LLM_TIMEOUT", "60"))

    if provider == "ollama":
        # Oversized note: embed each in-window chunk and mean-pool so a single
        # long note cannot 500 the request and abort the whole index build (#2110).
        chunks = _chunk_for_embedding(text, _embedding_max_input_chars())
        if len(chunks) == 1:
            return adapter(text, model=model, dim=dim, timeout=timeout)
        vectors = [adapter(chunk, model=model, dim=dim, timeout=timeout) for chunk in chunks]
        return _mean_pool(vectors, dim)

    result = adapter(text, model=model, dim=dim, timeout=timeout)
    # CTI-1: dim guardrail — every registered adapter must return a vector of the
    # configured dim; a wrong-dim result is a provider contract violation, not a
    # caller error. Checked here so even adapters that bypass _parse_vector are
    # covered by the invariant.
    assert_embed_dim(result, expected=dim, name=f"{provider} embedding (expected_dim={dim})")
    return result


def embed_text(
    text: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    dim: int | None = None,
    normalize: bool = True,
) -> List[float]:
    # Default dispatch honors EMBED_PRIMARY_PROVIDER (falling back to LLM_PROVIDER);
    # otherwise setting EMBED_PRIMARY_PROVIDER while LLM_PROVIDER=mock would still
    # embed via mock (Codex P2). Explicit provider= callers are unaffected.
    provider_val = provider or get_primary_provider()
    if model:
        model_val = model
    elif provider_val == "mock":
        model_val = _MOCK_EMBED_MODEL
    else:
        model_val = get_embed_model()
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
    dim_val = dim or get_embed_dim()
    vectors: List[List[float]] = []
    degraded_indices: list[int] = []
    embeddable_count = 0
    for index, text in enumerate(texts):
        # Empty inputs deterministically embed to a zero vector (see
        # _embed_single); they are not provider failures and must not count
        # toward outage detection.
        if text:
            embeddable_count += 1
        try:
            vectors.append(
                embed_text(text, provider=provider, model=model, dim=dim_val, normalize=normalize)
            )
        except (httpx.HTTPError, RuntimeError) as exc:
            # Chunking keeps each request in-window, but degrade any still-failing
            # item to a zero vector instead of aborting the whole batch, so one
            # bad note cannot take down the entire retrieval index build (#2110).
            # The zero vector preserves expected_dim and contributes no similarity
            # signal.
            logger.warning(
                "embedding skipped for item %d (len=%d): %s; substituting zero vector",
                index,
                len(text),
                exc,
            )
            if text:
                degraded_indices.append(index)
            vectors.append([0.0 for _ in range(dim_val)])

    # Per-item degradation tolerates the occasional un-embeddable note. But when
    # every embeddable item in the batch degrades, the failure is provider-wide
    # (missing OLLAMA_HOST, Ollama down, model unavailable), not a per-note
    # context-length problem. Silently returning an all-zero batch would let the
    # caller build a semantically dead retrieval index (#2190). Fail loud so the
    # outage surfaces instead of being absorbed into zero vectors.
    if embeddable_count and len(degraded_indices) == embeddable_count:
        raise RuntimeError(
            "embedding provider degraded every embeddable item in the batch "
            f"({len(degraded_indices)}/{embeddable_count}); refusing to return an "
            "all-zero semantic index. Check provider availability (OLLAMA_HOST / "
            "Ollama reachability / embedding model)."
        )
    return vectors


__all__ = [
    "embed_text",
    "embed_texts",
    "EMBED_MODEL",
    "get_embedding_provider",
    "get_embed_model",
    "get_primary_provider",
    "get_fallback_provider",
    "PROVIDER_REGISTRY",
    "ProviderAdapter",
]
