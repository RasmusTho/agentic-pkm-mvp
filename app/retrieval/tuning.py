"""Retrieval tuning config resolution (ADR-0059 D3, issue #3404).

Resolves the typed, settings-backed :class:`app.settings.models.RetrievalTuning` surface ONCE per
process: :func:`get_retrieval_tuning` reads the settings-bundle default, applies env-var overrides,
validates (fail-loud, never a silent fallback), and caches the result. Callers on the retrieval hot
path (``app/retrieval/hybrid.py``, ``app/retrieval/hook_adapter.py``,
``app/retrieval/hybrid_rerank_hook.py``) call this function instead of reading ``os.getenv`` per
query.

Existing ``RERANK_ENABLE``/``RERANK_TOP_K``/``RERANK_PROVIDER`` env vars keep working as overrides
into this surface (compat). ``RERANK_PROVIDER`` selects the reranker *implementation*
(`app/retrieval/rerank/provider.py`), which is unrelated to the D3 config shape and stays read
directly at reranker-construction time — untouched by this module.

``fusion="rrf"`` (weighted RRF, ``app/retrieval/hybrid.py::_rank_eligible``) and
``rerank="conditional"`` (deterministic BM25-margin gate, ``app/retrieval/hook_adapter.py``) are
implemented (ADR-0059 D3 step 5, issue #3407). Both resolve successfully and ship dark: the
defaults stay ``fusion="linear"`` / ``rerank="off"``, and flipping either default is a separate
owner call gated on eval evidence, recorded against ADR-0059 — never a silent behavior change from
this module.
"""

from __future__ import annotations

import os

from pydantic import ValidationError

from app.settings.models import RetrievalTuning
from app.settings.runtime import get_settings_bundle

_TRUE_VALUES = {"1", "true", "yes", "on"}

_CACHED: RetrievalTuning | None = None


class RetrievalTuningError(ValueError):
    """Raised when retrieval tuning config resolution encounters an invalid override.

    Fail-loud by design (#3404 AC2): a junk override value must never be silently dropped or
    reverted to the default.
    """


class RetrievalStrategyNotImplementedError(RetrievalTuningError):
    """Historical marker type (ADR-0059 D3 step 5, issue #3407).

    Before #3407, selecting ``fusion="rrf"`` or ``rerank="conditional"`` raised this at resolution
    time because the strategies did not exist yet. Both are now implemented and resolve
    successfully; this class is kept (unused by this module) only so any external code that still
    references it by name does not break on import. Do not raise it for new not-implemented
    strategies — use :class:`RetrievalTuningError` directly.
    """


def reset_retrieval_tuning_cache() -> None:
    """Test-only: force the next :func:`get_retrieval_tuning` call to re-resolve.

    Production code resolves once per process and never calls this. Tests reset between cases (see
    the autouse fixture in ``tests/conftest.py``) so a monkeypatched env var in one test never leaks
    a stale resolution into the next.
    """
    global _CACHED
    _CACHED = None


def _base_tuning() -> RetrievalTuning:
    try:
        return get_settings_bundle().retrieval_tuning
    except Exception:
        return RetrievalTuning()


def _parse_int(raw: str, *, env_key: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise RetrievalTuningError(f"{env_key} must be an integer, got: {raw!r}") from exc


def _parse_float(raw: str, *, env_key: str) -> float:
    try:
        return float(raw)
    except ValueError as exc:
        raise RetrievalTuningError(f"{env_key} must be a float, got: {raw!r}") from exc


def _parse_float_tuple(raw: str, *, env_key: str, count: int) -> tuple[float, ...]:
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != count:
        raise RetrievalTuningError(
            f"{env_key} must be {count} comma-separated floats, got: {raw!r}"
        )
    try:
        return tuple(float(p) for p in parts)
    except ValueError as exc:
        raise RetrievalTuningError(f"{env_key} must be numeric floats, got: {raw!r}") from exc


def _env(key: str) -> str:
    return os.getenv(key, "").strip()


def _resolve_retrieval_tuning() -> RetrievalTuning:
    base = _base_tuning()
    data = base.model_dump()

    fusion_raw = _env("RETRIEVAL_FUSION")
    if fusion_raw:
        data["fusion"] = fusion_raw.lower()

    weights_raw = _env("RETRIEVAL_LINEAR_WEIGHTS")
    if weights_raw:
        bm25, embedding, overlap = _parse_float_tuple(
            weights_raw, env_key="RETRIEVAL_LINEAR_WEIGHTS", count=3
        )
        data["linear_weights"] = {"bm25": bm25, "embedding": embedding, "overlap": overlap}

    rrf_k_raw = _env("RETRIEVAL_RRF_K")
    if rrf_k_raw:
        data["rrf_k"] = _parse_int(rrf_k_raw, env_key="RETRIEVAL_RRF_K")

    rrf_weights_raw = _env("RETRIEVAL_RRF_SIGNAL_WEIGHTS")
    if rrf_weights_raw:
        lexical, dense = _parse_float_tuple(
            rrf_weights_raw, env_key="RETRIEVAL_RRF_SIGNAL_WEIGHTS", count=2
        )
        data["rrf_signal_weights"] = {"lexical": lexical, "dense": dense}

    depth_raw = _env("RETRIEVAL_RETRIEVE_DEPTH")
    if depth_raw:
        data["retrieve_depth"] = _parse_int(depth_raw, env_key="RETRIEVAL_RETRIEVE_DEPTH")

    rerank_raw = _env("RETRIEVAL_RERANK")
    if rerank_raw:
        data["rerank"] = rerank_raw.lower()
    else:
        # Back-compat (#3404 AC3): RERANK_ENABLE truthy maps to the new surface's "always" when the
        # new explicit knob is not set. RERANK_ENABLE has no "off" spelling distinct from unset in
        # today's behavior (app/retrieval/hook_adapter.py), so it is only ever a one-way promotion.
        if _env("RERANK_ENABLE").lower() in _TRUE_VALUES:
            data["rerank"] = "always"

    # RETRIEVAL_RERANK_TOP_K (new) wins over legacy RERANK_TOP_K when both are set.
    rerank_top_k_raw = _env("RETRIEVAL_RERANK_TOP_K") or _env("RERANK_TOP_K")
    if rerank_top_k_raw:
        data["rerank_top_k"] = _parse_int(
            rerank_top_k_raw, env_key="RETRIEVAL_RERANK_TOP_K/RERANK_TOP_K"
        )

    margin_raw = _env("RETRIEVAL_RERANK_SCORE_MARGIN")
    if margin_raw:
        data["rerank_score_margin"] = _parse_float(
            margin_raw, env_key="RETRIEVAL_RERANK_SCORE_MARGIN"
        )

    try:
        resolved = RetrievalTuning(**data)
    except ValidationError as exc:
        raise RetrievalTuningError(f"invalid retrieval tuning config: {exc}") from exc

    # fusion="rrf" and rerank="conditional" are implemented (ADR-0059 D3 step 5, #3407) and resolve
    # like any other valid config value. Neither is the shipped default; a default flip is a
    # separate owner call gated on eval evidence, recorded against ADR-0059 — not enforced here.
    return resolved


def get_retrieval_tuning() -> RetrievalTuning:
    """Return the process-cached, env-overridden :class:`RetrievalTuning`.

    Resolves once and caches; an invalid or unimplemented resolution is never cached (so a fixed
    override on the next call re-resolves rather than staying stuck raising).
    """
    global _CACHED
    if _CACHED is None:
        _CACHED = _resolve_retrieval_tuning()
    return _CACHED


__all__ = [
    "RetrievalTuningError",
    "RetrievalStrategyNotImplementedError",
    "get_retrieval_tuning",
    "reset_retrieval_tuning_cache",
]
