from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from typing import List

import httpx

from app.embedding_config import assert_embed_dim, get_embed_dim, l2_normalize

OLLAMA_URL = os.getenv("OLLAMA_URL", os.getenv("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", os.getenv("EMBED_MODEL", "nomic-embed-text:latest"))


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


@lru_cache(maxsize=2048)
def _embed_single(text: str, provider: str, model: str, dim: int) -> tuple[float, ...]:
    if not text:
        return tuple(0.0 for _ in range(dim))

    if provider == "mock":
        return tuple(_mock_vector(text, dim=dim))

    if provider == "ollama":
        resp = httpx.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": model, "prompt": text},
            timeout=float(os.getenv("LLM_TIMEOUT", "60")),
        )
        resp.raise_for_status()
        data = resp.json()
        embedding = [float(x) for x in (data.get("embedding") or [])]
        assert_embed_dim(embedding, name="embedding")
        return tuple(embedding)

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
    model_val = model or EMBED_MODEL
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


__all__ = ["embed_text", "embed_texts", "EMBED_MODEL", "get_embedding_provider"]
