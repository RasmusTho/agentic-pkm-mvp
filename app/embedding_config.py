from __future__ import annotations

import math
import os
from typing import Iterable, Sequence

from app.settings import settings

DEFAULT_EMBED_DIM = 1536


def get_embed_dim() -> int:
    raw = os.getenv("EMBED_DIM")
    if raw is None:
        raw = str(getattr(settings, "embed_dim", DEFAULT_EMBED_DIM))
    raw = str(raw).strip()
    try:
        dim = int(raw)
    except Exception:
        dim = DEFAULT_EMBED_DIM
    if dim <= 0:
        dim = DEFAULT_EMBED_DIM
    return dim


def l2_normalize(values: Sequence[float]) -> list[float]:
    vec = [float(v) for v in values]
    if not vec:
        return []
    norm = math.sqrt(sum(v * v for v in vec))
    if not norm:
        return [0.0 for _ in vec]
    return [v / norm for v in vec]


def assert_embed_dim(values: Sequence[float], *, name: str = "embedding") -> None:
    expected = get_embed_dim()
    actual = len(values)
    if actual != expected:
        raise ValueError(f"{name} dim mismatch: expected {expected}, got {actual}")


def coerce_floats(values: Iterable[object]) -> list[float]:
    return [float(v) for v in values]
