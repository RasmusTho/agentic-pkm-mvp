from __future__ import annotations

import logging
from enum import Enum
from typing import Callable

from app.components.embeddings import EmbeddingIdentity, resolve_embedding_identity
from app.components.llm.fabric import get_product_embedding_client_for_identity
from app.llm.embed_queue import EmbedDeadLetterError, embed_with_retry
from app.llm.embeddings import get_fallback_provider

logger = logging.getLogger(__name__)


class FallbackGateResult(str, Enum):
    AVAILABLE = "AVAILABLE"
    NO_FALLBACK_CONFIGURED = "NO_FALLBACK_CONFIGURED"
    DIM_MISMATCH = "DIM_MISMATCH"


def _resolve_fallback_identity(provider: str) -> EmbeddingIdentity:
    return resolve_embedding_identity(override_provider=provider)


def _checked_embed(embed_callable: Callable[[], list[float]], *, identity: EmbeddingIdentity) -> list[float]:
    vector = list(embed_callable())
    if len(vector) != identity.dim:
        raise ValueError(f"expected {identity.dim} got {len(vector)}")
    return vector


def evaluate_fallback_gate(primary_dim: int) -> FallbackGateResult:
    provider = get_fallback_provider()
    if provider != "gemini":
        return FallbackGateResult.NO_FALLBACK_CONFIGURED
    fallback_identity = _resolve_fallback_identity(provider)
    if fallback_identity.dim != primary_dim:
        return FallbackGateResult.DIM_MISMATCH
    return FallbackGateResult.AVAILABLE


def embed_with_fallback(
    text: str,
    *,
    primary_identity: EmbeddingIdentity,
    primary_embed_callable: Callable[[], list[float]],
    object_id: str | None = None,
    db_session_or_none: object | None = None,
) -> tuple[list[float], EmbeddingIdentity, bool]:
    del db_session_or_none

    try:
        vector = embed_with_retry(
            text,
            dim=primary_identity.dim,
            object_id=object_id,
            embed_callable=lambda: _checked_embed(primary_embed_callable, identity=primary_identity),
        )
        return vector, primary_identity, False
    except EmbedDeadLetterError as primary_exc:
        if primary_exc.indeterminate:
            raise
        provider = get_fallback_provider()
        gate = evaluate_fallback_gate(primary_identity.dim)
        if gate is not FallbackGateResult.AVAILABLE or provider != "gemini":
            if gate is FallbackGateResult.DIM_MISMATCH and provider == "gemini":
                fallback_dim = _resolve_fallback_identity(provider).dim
                logger.warning(
                    "embed_with_fallback: fallback gate=%s (fallback_dim=%s != primary_dim=%s), dead-lettering object_id=%s",
                    gate.value,
                    fallback_dim,
                    primary_identity.dim,
                    object_id or "-",
                )
            else:
                logger.warning(
                    "embed_with_fallback: fallback gate=%s, dead-lettering object_id=%s",
                    gate.value,
                    object_id or "-",
                )
            raise EmbedDeadLetterError(f"{primary_exc}; fallback gate={gate.value}") from primary_exc

        fallback_identity = _resolve_fallback_identity(provider)
        fallback_client = get_product_embedding_client_for_identity(fallback_identity)
        logger.warning(
            "embed_with_fallback: primary exhausted, trying fallback provider=%s object_id=%s",
            fallback_identity.provider,
            object_id or "-",
        )
        fallback_error: tuple[str, bool] | None = None
        try:
            vector = embed_with_retry(
                text,
                dim=fallback_identity.dim,
                object_id=object_id,
                embed_callable=lambda: _checked_embed(
                    lambda: fallback_client.embed_text(text),
                    identity=fallback_identity,
                ),
            )
        except Exception as fallback_exc:
            fallback_error = (
                str(fallback_exc),
                bool(getattr(fallback_exc, "indeterminate", False)),
            )
        finally:
            close = getattr(fallback_client, "close", None)
            if callable(close):
                close()
        if fallback_error is not None:
            detail, indeterminate = fallback_error
            raise EmbedDeadLetterError(
                f"{primary_exc}; fallback provider={fallback_identity.provider} failed: {detail}",
                indeterminate=indeterminate,
            )
        return vector, fallback_identity, True


__all__ = [
    "FallbackGateResult",
    "embed_with_fallback",
    "evaluate_fallback_gate",
]
