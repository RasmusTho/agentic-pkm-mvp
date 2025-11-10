from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from typing import List

import httpx

OLLAMA_URL = os.getenv("OLLAMA_URL", os.getenv("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", os.getenv("EMBED_MODEL", "nomic-embed-text:latest"))


def _provider() -> str:
    return os.getenv("LLM_PROVIDER", "ollama").lower()


def _mock_vector(text: str, dims: int = 8) -> List[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    vec = []
    for idx in range(dims):
        chunk = digest[idx % len(digest)]
        vec.append(((chunk / 255.0) * 2) - 1)  # range [-1, 1]
    return vec


@lru_cache(maxsize=512)
def _embed_single(text: str, provider: str, model: str) -> tuple[float, ...]:
    if not text:
        return tuple(0.0 for _ in range(8))
    if provider == "mock":
        return tuple(_mock_vector(text))
    if provider == "ollama":
        resp = httpx.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": model, "prompt": text},
            timeout=float(os.getenv("LLM_TIMEOUT", "60")),
        )
        resp.raise_for_status()
        data = resp.json()
        embedding = data.get("embedding") or []
        return tuple(float(x) for x in embedding)
    raise ValueError(f"Unsupported embedding provider: {provider}")


def embed_text(text: str) -> List[float]:
    prov = _provider()
    model = EMBED_MODEL
    return list(_embed_single(text, prov, model))


def embed_texts(texts: List[str]) -> List[List[float]]:
    return [embed_text(text) for text in texts]


__all__ = ["embed_text", "embed_texts"]
