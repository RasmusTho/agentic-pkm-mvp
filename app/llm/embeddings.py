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


def _mock_vector(text: str, *, dim: int) -> List[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    vec: list[float] = []
    for idx in range(dim):
        chunk = digest[idx % len(digest)]
        vec.append(((chunk / 255.0) * 2) - 1)  # range [-1, 1]
    return l2_normalize(vec)


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
        return tuple(l2_normalize(embedding))

    raise ValueError(f"Unsupported embedding provider: {provider}")


def embed_text(text: str) -> List[float]:
    provider = _provider()
    model = EMBED_MODEL
    dim = get_embed_dim()
    return list(_embed_single(text, provider, model, dim))


def embed_texts(texts: List[str]) -> List[List[float]]:
    return [embed_text(text) for text in texts]


__all__ = ["embed_text", "embed_texts", "EMBED_MODEL"]
