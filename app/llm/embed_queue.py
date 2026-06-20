"""Embedding execution queue: bounded-concurrency, retry-with-backoff, per-object dead-letter.

This module provides ``embed_with_retry`` — the single-object embed call that wraps
``_embed_single`` (which already handles chunking + mean-pooling per #2110) with
exponential backoff on transient failures.  Transient classification reuses the same
predicate and sets as ``_is_transient_dispatch_error`` in
``app/workers/outbox_worker.py`` — the logic is imported, not duplicated.

Env vars (identical in dev/test/prod — no environment-conditional branching):
    EMBED_RETRY_MAX          — max attempts per object (default 3)
    EMBED_RETRY_BASE_BACKOFF_S — base sleep seconds (default 1.0)
    EMBED_RETRY_MAX_BACKOFF_S  — cap on backoff sleep (default 30.0)
    EMBED_QUEUE_CONCURRENCY  — ThreadPoolExecutor bound for batch callers (default 1)

On exhaustion after all transient retries, ``EmbedDeadLetterError`` (a subclass of
``RuntimeError``) is raised instead of the raw provider error.  Non-transient errors
(e.g. ``ValueError`` from dimension mismatch, unsupported provider) are re-raised
immediately — no retry, no sleep.
"""
from __future__ import annotations

import logging
import os
import time
from typing import List

from app.llm.embeddings import _embed_single, get_embed_dim, get_embed_model, _provider

logger = logging.getLogger(__name__)


def _is_transient_embed_error(exc: BaseException) -> bool:
    """Delegate to the worker's transient classification without a module-level import.

    The import is deferred to avoid the circular dependency:
    embed_queue → outbox_worker → consumer → embed_queue.
    The logic is never duplicated — we always call the worker's predicate.
    """
    from app.workers.outbox_worker import _is_transient_dispatch_error  # noqa: PLC0415
    return _is_transient_dispatch_error(exc)


# ---------------------------------------------------------------------------
# Dead-letter sentinel
# ---------------------------------------------------------------------------

class EmbedDeadLetterError(RuntimeError):
    """Raised when all retry attempts for a single embed call are exhausted.

    Callers can catch this specifically to dead-letter the object and continue
    the ingest batch without inspecting exception strings.
    """


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _get_retry_max() -> int:
    raw = os.getenv("EMBED_RETRY_MAX")
    if raw is None:
        return 3
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 3
    return max(value, 1)


def _get_base_backoff() -> float:
    raw = os.getenv("EMBED_RETRY_BASE_BACKOFF_S")
    if raw is None:
        return 1.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 1.0
    return max(value, 0.0)


def _get_max_backoff() -> float:
    raw = os.getenv("EMBED_RETRY_MAX_BACKOFF_S")
    if raw is None:
        return 30.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 30.0
    return max(value, 0.0)


def _get_concurrency() -> int:
    raw = os.getenv("EMBED_QUEUE_CONCURRENCY")
    if raw is None:
        return 1
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 1
    return max(value, 1)


def _backoff_seconds(attempt: int, base: float, cap: float) -> float:
    """Exponential backoff: base * 2^(attempt-1), capped at cap.

    For attempt=1 returns base; attempt=2 returns base*2; etc.
    """
    return min(base * (2 ** (attempt - 1)), cap)


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def embed_with_retry(
    text: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    dim: int | None = None,
    normalize: bool = True,
    object_id: str | None = None,
    _sleep: bool = True,
) -> List[float]:
    """Embed ``text`` with exponential backoff on transient failures.

    Wraps ``_embed_single`` (which already handles oversized-note chunking +
    mean-pooling per #2110).  The ``normalize`` parameter is handled by the caller
    via ``embed_text`` contract; ``_embed_single`` itself does not normalize.

    On exhaustion of all retry attempts (all of which were transient), raises
    ``EmbedDeadLetterError``.

    Non-transient errors (``ValueError``, unsupported provider, etc.) are re-raised
    immediately on the first attempt — no sleep, no retry.

    Args:
        text: Text to embed.
        provider: Embedding provider (default: resolved from env).
        model: Model name (default: resolved from env).
        dim: Expected vector dimension (default: resolved from env).
        normalize: Whether to L2-normalise the resulting vector.
        object_id: Optional identifier for log context.
        _sleep: Internal toggle — set to False in tests to skip actual sleep.

    Returns:
        Embedding vector as a list of floats.

    Raises:
        EmbedDeadLetterError: All retry attempts exhausted on a transient error.
        ValueError: Non-transient dimension mismatch or unsupported provider (no retry).
        Exception: Any other non-transient error (no retry).
    """
    from app.embedding_config import l2_normalize  # local import to avoid circulars

    provider_val = provider or _provider()
    if model:
        model_val = model
    elif provider_val == "mock":
        model_val = "mock-embedding"
    else:
        model_val = get_embed_model()
    dim_val = dim or get_embed_dim()

    retry_max = _get_retry_max()
    base_backoff = _get_base_backoff()
    max_backoff = _get_max_backoff()

    last_exc: Exception | None = None

    for attempt in range(1, retry_max + 1):
        try:
            vector = list(_embed_single(text, provider_val, model_val, dim_val))
            if normalize:
                return l2_normalize(vector)
            return vector
        except Exception as exc:
            if not _is_transient_embed_error(exc):
                # Non-transient: re-raise immediately, no retry, no sleep.
                raise

            last_exc = exc
            if attempt < retry_max:
                sleep_s = _backoff_seconds(attempt, base_backoff, max_backoff)
                logger.warning(
                    "embed_with_retry attempt=%d/%d backoff_s=%.1f error=%s object_id=%s",
                    attempt,
                    retry_max,
                    sleep_s,
                    exc,
                    object_id or "-",
                )
                if _sleep:
                    time.sleep(sleep_s)
            else:
                logger.warning(
                    "embed_with_retry attempt=%d/%d (final) error=%s object_id=%s",
                    attempt,
                    retry_max,
                    exc,
                    object_id or "-",
                )

    raise EmbedDeadLetterError(
        f"embed exhausted after {retry_max} attempts (transient): {last_exc}"
    ) from last_exc


__all__ = [
    "embed_with_retry",
    "EmbedDeadLetterError",
    "_get_retry_max",
    "_get_base_backoff",
    "_get_max_backoff",
    "_get_concurrency",
]
