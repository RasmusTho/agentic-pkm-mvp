from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

DEFAULT_DIMENSIONS = 1536


def embed_text(text: str, *, dimensions: int = DEFAULT_DIMENSIONS, normalize: bool = True) -> list[float]:
    """
    Deterministic hashing-based embedding for offline testing.
    """

    if not text.strip():
        raise ValueError("Cannot embed empty text")
    vector = [0.0] * dimensions
    for token in text.split():
        digest = hashlib.sha256(token.lower().encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % dimensions
        vector[idx] += 1.0
    if normalize:
        norm = math.sqrt(sum(val * val for val in vector))
        if norm:
            vector = [val / norm for val in vector]
    return vector


def embed_many(texts: Sequence[str], *, dimensions: int = DEFAULT_DIMENSIONS, normalize: bool = True) -> list[list[float]]:
    return [embed_text(text, dimensions=dimensions, normalize=normalize) for text in texts]

