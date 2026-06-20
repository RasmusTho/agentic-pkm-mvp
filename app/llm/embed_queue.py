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
from typing import Callable, List

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
    embed_callable: "Callable[[], List[float]] | None" = None,
    dead_letter_on_exhaustion: bool = True,
    _sleep: bool = True,
) -> List[float]:
    """Embed ``text`` with exponential backoff on transient failures.

    Two embed routes:

    - **Injected callable** (``embed_callable``) — used by the worker/runtime call
      sites (``handle_ingest_object_created``, consumer ``process_event``) so the
      configured/injected embedding client (and test doubles) stay on the path. The
      callable owns normalization; its result is returned verbatim.
    - **Batch route** (``embed_callable=None``) — wraps ``_embed_single`` directly
      (which already handles oversized-note chunking + mean-pooling per #2110) and
      applies ``normalize``. Used by the batch CLI (``index rebuild``).

    Exhaustion behavior is path-dependent:

    - ``dead_letter_on_exhaustion=True`` (default, **batch** path): after all
      transient retries fail, raise ``EmbedDeadLetterError`` so the caller can skip
      the object and continue the batch (CTI-6) — there is no worker to retry it.
    - ``dead_letter_on_exhaustion=False`` (**worker/consumer** path): after all
      transient retries fail, re-raise the *original* transient error so it
      propagates to the outbox worker, which keeps the row pending and retries
      later. This preserves at-least-once durability — a brief Ollama outage must
      defer objects until the provider recovers, not permanently drop them.

    Non-transient errors (``ValueError`` dim mismatch, unsupported provider, etc.)
    are re-raised immediately on the first attempt — no sleep, no retry — regardless
    of ``dead_letter_on_exhaustion``.
    """
    from app.embedding_config import l2_normalize  # local import to avoid circulars

    def _embed_once() -> List[float]:
        if embed_callable is not None:
            return list(embed_callable())
        provider_val = provider or _provider()
        if model:
            model_val = model
        elif provider_val == "mock":
            model_val = "mock-embedding"
        else:
            model_val = get_embed_model()
        dim_val = dim or get_embed_dim()
        vector = list(_embed_single(text, provider_val, model_val, dim_val))
        return l2_normalize(vector) if normalize else vector

    retry_max = _get_retry_max()
    base_backoff = _get_base_backoff()
    max_backoff = _get_max_backoff()

    last_exc: Exception | None = None

    for attempt in range(1, retry_max + 1):
        try:
            return _embed_once()
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

    if dead_letter_on_exhaustion:
        raise EmbedDeadLetterError(
            f"embed exhausted after {retry_max} attempts (transient): {last_exc}"
        ) from last_exc
    # Worker/consumer path: propagate the original transient so the outbox worker
    # keeps the row pending and retries when the provider recovers (at-least-once).
    assert last_exc is not None
    raise last_exc


__all__ = [
    "embed_with_retry",
    "EmbedDeadLetterError",
    "_get_retry_max",
    "_get_base_backoff",
    "_get_max_backoff",
    "_get_concurrency",
]
