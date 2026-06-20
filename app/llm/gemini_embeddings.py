"""Google Gemini embedding adapter (EMBEDREL-04).

Implements ``embed_gemini_text`` using raw httpx (no google-generativeai SDK)
following the same HTTP call style as the Ollama adapter in ``app/llm/embeddings.py``.

The active model is ``gemini-embedding-001`` (stable, text).  It defaults to 3072
dims; this adapter requests ``output_dimensionality=768`` (camelCase, nested under
``embedContentConfig`` — the REST form, *not* the SDK snake_case which is silently
ignored by REST and would return the default 3072-dim vector).  Because the dim is
non-default the returned vector is L2-renormalized before return (required for
``gemini-embedding-001`` at non-default dims).

Secret handling (CTI-4):
  Key is resolved from ``GEMINI_API_KEY`` (preferred) then ``GOOGLE_API_KEY``.
  If neither is set the adapter raises ``GeminiUnavailableError`` *before* any
  network call.  The key is never logged, echoed, or placed in exception messages.
  Note content (the ``text`` argument) is never logged beyond existing provenance
  fields.

Error classification:
  - HTTP 429 / 5xx / network errors (ConnectError / TimeoutException):
    ``GeminiTransientError`` — retry-eligible by the queue (EMBEDREL-02).
  - HTTP 4xx (401 / 403 / 400 bad key / auth failure):
    ``GeminiAuthError`` — non-transient, do not retry.
  - No key configured:
    ``GeminiUnavailableError`` — keeps a local-only deployment fully viable.
"""

from __future__ import annotations

import logging
import os
from typing import Mapping

import httpx

from app.embedding_config import assert_embed_dim, l2_normalize

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public error hierarchy
# ---------------------------------------------------------------------------


class GeminiUnavailableError(RuntimeError):
    """Raised when no API key is configured.

    This is *not* a transient error — the adapter is simply absent in this
    deployment.  The fallback orchestrator (EMBEDREL-05) treats UNAVAILABLE as
    a no-op rather than a retryable failure.
    """

    is_transient = False


class GeminiTransientError(RuntimeError):
    """Raised for HTTP 429, 5xx, or network-level errors (retry-eligible).

    Carries the ``is_transient = True`` marker so the embedding queue's
    ``_is_transient_embed_error`` retries/backs-off these even though this is an
    app-local class with no httpx response/chain (HTTP 429/5xx path).
    """

    is_transient = True


class GeminiAuthError(RuntimeError):
    """Raised for HTTP 4xx auth / bad-key responses (non-transient)."""

    is_transient = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_GEMINI_DEFAULT_MODEL = "gemini-embedding-001"
_GEMINI_REST_BASE = "https://generativelanguage.googleapis.com"


def _resolve_api_key() -> str:
    """Return the API key from env, or raise GeminiUnavailableError."""
    key = os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()
    if not key:
        raise GeminiUnavailableError(
            "gemini unavailable: no API key configured (set GEMINI_API_KEY or GOOGLE_API_KEY)"
        )
    return key


def _get_model() -> str:
    return os.getenv("EMBED_GEMINI_MODEL", _GEMINI_DEFAULT_MODEL).strip() or _GEMINI_DEFAULT_MODEL


def _get_base_url() -> str:
    override = os.getenv("GEMINI_BASE_URL", "").strip()
    return override if override else _GEMINI_REST_BASE


def _build_endpoint(model: str, base_url: str) -> str:
    """Return the REST embedContent endpoint for *model* under *base_url*."""
    # model name is passed as-is to the URL; callers supply e.g. "gemini-embedding-001"
    base = base_url.rstrip("/")
    return f"{base}/v1beta/models/{model}:embedContent"


def _extract_gemini_error(response: httpx.Response) -> str | None:
    """Extract a human-readable error detail from a Gemini error response."""
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, Mapping):
        err = payload.get("error")
        if isinstance(err, Mapping):
            detail = err.get("message") or err.get("status")
        else:
            detail = err
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    text = (response.text or "").strip()
    return text if text else None


# ---------------------------------------------------------------------------
# Public adapter
# ---------------------------------------------------------------------------


def embed_gemini_text(
    text: str,
    *,
    model: str,
    dim: int,
    timeout: float,
    base_url: str | None = None,
) -> tuple[float, ...]:
    """Embed *text* via the Gemini REST embedContent API.

    Parameters
    ----------
    text:
        The text to embed.
    model:
        Model name (e.g. ``"gemini-embedding-001"``).
    dim:
        Requested output dimensionality (passed as
        ``embedContentConfig.outputDimensionality``).
    timeout:
        httpx request timeout in seconds.
    base_url:
        Optional base URL override (for test isolation via ``GEMINI_BASE_URL``).
        When ``None`` the value of ``_get_base_url()`` is used.

    Returns
    -------
    tuple[float, ...]
        L2-normalized vector of length *dim*.

    Raises
    ------
    GeminiUnavailableError
        No API key is configured (CTI-4).
    GeminiAuthError
        HTTP 4xx response (bad key / auth failure, non-transient).
    GeminiTransientError
        HTTP 429, 5xx, or network-level error (retry-eligible).
    ValueError
        The API returned a vector whose length != *dim* (dim guardrail, CTI-1).
    """
    # Key resolution: never log or echo the key value.
    key = _resolve_api_key()

    effective_base = base_url if base_url is not None else _get_base_url()
    url = _build_endpoint(model, effective_base)

    # REST payload: camelCase outputDimensionality nested under embedContentConfig.
    # snake_case output_dimensionality is the SDK form and is silently ignored by
    # the REST API, causing the default 3072-dim vector to be returned instead.
    body = {
        "model": f"models/{model}",
        "content": {"parts": [{"text": text}]},
        "embedContentConfig": {"outputDimensionality": dim},
    }

    try:
        resp = httpx.post(
            url,
            json=body,
            headers={"x-goog-api-key": key},
            timeout=timeout,
        )
    except httpx.ConnectError as exc:
        raise GeminiTransientError(
            f"Gemini embedding network error (model={model}): connection refused"
        ) from exc
    except httpx.TimeoutException as exc:
        raise GeminiTransientError(
            f"Gemini embedding network error (model={model}): request timed out"
        ) from exc

    if not resp.is_success:
        status = resp.status_code
        detail = _extract_gemini_error(resp)
        # Keep the key out of the message; report only the HTTP status + detail.
        summary = f"Gemini embedContent HTTP {status}"
        if detail:
            summary = f"{summary}: {detail}"
        if status in (408, 429) or status >= 500:
            # 408 (request timeout) and 429 (rate limit) are retryable, matching the
            # shared transient classifier (app/workers/outbox_worker.py).
            raise GeminiTransientError(summary)
        # 401, 403, 400 (bad key), and any other 4xx → auth / config error
        raise GeminiAuthError(summary)

    try:
        data = resp.json()
    except Exception as exc:
        raise GeminiTransientError(
            f"Gemini embedding response parse error (model={model})"
        ) from exc

    if not isinstance(data, Mapping):
        raise GeminiTransientError(
            f"Gemini embedding returned unexpected payload type (model={model})"
        )

    embedding = data.get("embedding")
    if not isinstance(embedding, Mapping):
        raise GeminiTransientError(
            f"Gemini embedding response missing 'embedding' key (model={model})"
        )

    values = embedding.get("values")
    if not isinstance(values, (list, tuple)) or not values:
        raise GeminiTransientError(
            f"Gemini embedding response missing 'embedding.values' (model={model})"
        )

    vector = [float(v) for v in values]

    # CTI-1: dim guardrail — reject any vector whose length != dim, including the
    # case where the API ignored outputDimensionality and returned the default 3072.
    assert_embed_dim(vector, expected=dim, name="embedding")

    # L2-renormalize: required for gemini-embedding-001 at non-default dims.
    return tuple(l2_normalize(vector))


# ---------------------------------------------------------------------------
# PROVIDER_REGISTRY adapter wrapper
# ---------------------------------------------------------------------------


def _gemini_embed_one(text: str, *, model: str, dim: int, timeout: float) -> tuple[float, ...]:
    """ProviderAdapter-shaped wrapper for the Gemini adapter.

    The Gemini adapter must always request a **Gemini** model. When gemini is
    selected through the registry from a non-gemini profile (e.g. the default
    Ollama profile), ``_embed_single`` passes the index's generic embedding model
    (such as ``nomic-embed-text:latest``) as ``model`` — sending that to Gemini
    would target ``/models/nomic-embed-text:latest:embedContent`` and fail. So we
    honor ``model`` only when it is explicitly a Gemini model, otherwise fall back
    to the configured Gemini model (``EMBED_GEMINI_MODEL`` / ``gemini-embedding-001``).
    Registered in ``PROVIDER_REGISTRY["gemini"]`` by ``app/llm/embeddings.py``.
    """
    effective_model = model if (model and "gemini" in model.lower()) else _get_model()
    return embed_gemini_text(
        text,
        model=effective_model,
        dim=dim,
        timeout=timeout,
        base_url=_get_base_url() if os.getenv("GEMINI_BASE_URL", "").strip() else None,
    )


__all__ = [
    "embed_gemini_text",
    "GeminiUnavailableError",
    "GeminiTransientError",
    "GeminiAuthError",
    "_gemini_embed_one",
]
