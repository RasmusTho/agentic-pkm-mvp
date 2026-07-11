"""RetrievalTuning config surface: golden parity + fail-loud validation (ADR-0059 D3, #3404).

- test_default_config_ranking_parity: with no config/env override anywhere, `hybrid_search()` must
  reproduce the pre-#3404 literal formula (`0.5*bm25_norm + 0.4*emb_norm + 0.1*overlap_bonus`)
  EXACTLY. The expected scores are recomputed independently here from the store's own scoring
  primitives with the constants hardcoded — deliberately NOT read from `RetrievalTuning` defaults —
  so an accidental default change would fail this test rather than pass trivially.
- test_weight_override_and_failloud_validation: a `RETRIEVAL_LINEAR_WEIGHTS` override changes the
  fused ranking accordingly; a junk override value fails loud (raises), never silently reverts to
  the default triplet.
- test_rerank_env_compat: legacy `RERANK_ENABLE`/`RERANK_TOP_K`/`RERANK_PROVIDER` env vars still
  control rerank through the new `RetrievalTuning` surface.
- test_reserved_strategies_resolve_and_stay_non_default: selecting `fusion="rrf"` or
  `rerank="conditional"` resolves successfully (ADR-0059 D3 step 5, #3407) without changing the
  process-wide default when unset.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from app.components.retrieval import embed_query
from app.retrieval.hook_adapter import maybe_rerank
from app.retrieval.hybrid import get_store, hybrid_search
from app.retrieval.tuning import (
    RetrievalTuningError,
    get_retrieval_tuning,
    reset_retrieval_tuning_cache,
)
from app.settings import runtime

pytestmark = pytest.mark.not_pg

_TUNING_ENV_KEYS = (
    "RERANK_ENABLE",
    "RERANK_TOP_K",
    "RERANK_PROVIDER",
    "RETRIEVAL_FUSION",
    "RETRIEVAL_LINEAR_WEIGHTS",
    "RETRIEVAL_RRF_K",
    "RETRIEVAL_RRF_SIGNAL_WEIGHTS",
    "RETRIEVAL_RETRIEVE_DEPTH",
    "RETRIEVAL_RERANK",
    "RETRIEVAL_RERANK_TOP_K",
    "RETRIEVAL_RERANK_SCORE_MARGIN",
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch):
    for key in _TUNING_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    reset_retrieval_tuning_cache()
    get_store().set_documents([])
    yield
    get_store().set_documents([])
    reset_retrieval_tuning_cache()


def _seed_corpus() -> None:
    get_store().set_documents(
        [
            {
                "doc_id": "doc-alpha",
                "text": "alpha beta gamma retrieval fusion tuning",
                "payload": {},
            },
            {
                "doc_id": "doc-beta",
                "text": "beta gamma delta hybrid search weighting",
                "payload": {},
            },
            {
                "doc_id": "doc-gamma",
                "text": "gamma delta epsilon lexical semantic overlap",
                "payload": {},
            },
            {
                "doc_id": "doc-unrelated",
                "text": "completely unrelated content about gardening tomatoes",
                "payload": {},
            },
        ]
    )


def _normalize(scores: np.ndarray) -> np.ndarray:
    if not len(scores):
        return scores
    min_v = float(np.min(scores))
    max_v = float(np.max(scores))
    if math.isclose(max_v - min_v, 0.0):
        return np.zeros_like(scores)
    return (scores - min_v) / (max_v - min_v)


def _expected_order(
    query: str, *, bm25_w: float, emb_w: float, overlap_w: float
) -> list[tuple[str, float]]:
    """Independently reconstructs the fused ranking from the store's raw scoring primitives with
    explicit weights, mirroring the pre-#3404 `_rank_eligible` formula shape but never importing it
    — this is a parity oracle, not a call-through to the code under test."""
    store = get_store()
    docs = store.all()
    tokens = query.lower().split()
    bm25 = np.asarray(store.bm25_scores(tokens), dtype=np.float32)
    vec, _ = embed_query(query)
    emb = np.asarray(store.embedding_scores(np.array(vec, dtype=np.float32)), dtype=np.float32)
    bm25_norm = _normalize(bm25)
    emb_norm = _normalize(emb)
    token_set = set(tokens)
    overlap = np.zeros(len(docs), dtype=np.float32)
    for i, doc in enumerate(docs):
        doc_tokens = set(doc.text.lower().split())
        overlap[i] = len(token_set & doc_tokens) / max(1, len(token_set))
    combined = bm25_w * bm25_norm + emb_w * emb_norm + overlap_w * overlap
    pairs = [(doc.doc_id, float(np.clip(combined[i], 0.0, 1.0))) for i, doc in enumerate(docs)]
    pairs.sort(key=lambda pair: -pair[1])
    return pairs


def test_default_config_ranking_parity() -> None:
    """No config/env override anywhere -> byte-identical to the pre-#3404 literal formula."""
    _seed_corpus()
    query = "alpha beta gamma"

    # ADR-0024's ratified constants, hardcoded here (NOT read from RetrievalTuning defaults).
    expected = _expected_order(query, bm25_w=0.5, emb_w=0.4, overlap_w=0.1)
    results = hybrid_search(query, k=len(expected))

    assert [r["doc_id"] for r in results] == [doc_id for doc_id, _ in expected]
    for result, (_, expected_score) in zip(results, expected):
        assert result["score"] == pytest.approx(expected_score, abs=1e-9)

    # The resolved config itself also carries the documented defaults.
    tuning = get_retrieval_tuning()
    assert tuning.fusion == "linear"
    assert (tuning.linear_weights.bm25, tuning.linear_weights.embedding, tuning.linear_weights.overlap) == (
        0.5,
        0.4,
        0.1,
    )
    assert tuning.rerank == "off"
    assert tuning.retrieve_depth == 500


def test_weight_override_and_failloud_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_corpus()
    query = "alpha beta gamma"

    monkeypatch.setenv("RETRIEVAL_LINEAR_WEIGHTS", "1,0,0")
    reset_retrieval_tuning_cache()

    tuning = get_retrieval_tuning()
    assert (tuning.linear_weights.bm25, tuning.linear_weights.embedding, tuning.linear_weights.overlap) == (
        1.0,
        0.0,
        0.0,
    )

    expected = _expected_order(query, bm25_w=1.0, emb_w=0.0, overlap_w=0.0)
    results = hybrid_search(query, k=len(expected))
    assert [r["doc_id"] for r in results] == [doc_id for doc_id, _ in expected]
    for result, (_, expected_score) in zip(results, expected):
        assert result["score"] == pytest.approx(expected_score, abs=1e-9)

    # Junk value: fails loud at resolution, never silently reverts to the default triplet.
    monkeypatch.setenv("RETRIEVAL_LINEAR_WEIGHTS", "not,a,number")
    reset_retrieval_tuning_cache()
    with pytest.raises(RetrievalTuningError):
        get_retrieval_tuning()
    # Still raises on a second call (no silent fallback got cached).
    with pytest.raises(RetrievalTuningError):
        get_retrieval_tuning()

    monkeypatch.setenv("RETRIEVAL_LINEAR_WEIGHTS", "0.5,0.4")  # wrong arity
    reset_retrieval_tuning_cache()
    with pytest.raises(RetrievalTuningError):
        get_retrieval_tuning()


def test_rerank_env_compat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RERANK_ENABLE", "1")
    monkeypatch.setenv("RERANK_PROVIDER", "mock_ce")
    monkeypatch.setenv("RERANK_TOP_K", "2")
    reset_retrieval_tuning_cache()

    tuning = get_retrieval_tuning()
    assert tuning.rerank == "always"
    assert tuning.rerank_top_k == 2

    items = [
        {"id": "a", "text": "alpha beta"},
        {"id": "b", "text": "beta gamma"},
        {"id": "c", "text": "gamma delta"},
    ]
    out = maybe_rerank("beta gamma", items)
    assert [o["id"] for o in out][:2] == ["b", "a"]
    assert {o["id"] for o in out} == {"a", "b", "c"}

    # RERANK_ENABLE absent/false-y -> rerank stays "off" (today's behavior), items untouched.
    monkeypatch.delenv("RERANK_ENABLE", raising=False)
    reset_retrieval_tuning_cache()
    assert get_retrieval_tuning().rerank == "off"
    out_default = maybe_rerank("beta gamma", items)
    assert [o["id"] for o in out_default] == ["a", "b", "c"]


def test_reserved_strategies_resolve_and_stay_non_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-0059 D3 step 5 (#3407): fusion='rrf' and rerank='conditional' are implemented and
    resolve like any other valid config value — no more not-implemented raise. Selecting either is
    an explicit override; leaving both unset still resolves to the 'linear'/'off' defaults."""
    monkeypatch.setenv("RETRIEVAL_FUSION", "rrf")
    reset_retrieval_tuning_cache()
    tuning = get_retrieval_tuning()
    assert tuning.fusion == "rrf"

    monkeypatch.delenv("RETRIEVAL_FUSION", raising=False)
    reset_retrieval_tuning_cache()
    monkeypatch.setenv("RETRIEVAL_RERANK", "conditional")
    reset_retrieval_tuning_cache()
    tuning = get_retrieval_tuning()
    assert tuning.rerank == "conditional"

    monkeypatch.delenv("RETRIEVAL_RERANK", raising=False)
    reset_retrieval_tuning_cache()
    tuning = get_retrieval_tuning()
    assert tuning.fusion == "linear"
    assert tuning.rerank == "off"


def test_invalid_runtime_tuning_yaml_fails_loud(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A typed runtime file is configuration authority, not an optional hint.

    This proves the startup path itself rejects invalid YAML instead of quietly
    constructing default retrieval tuning and serving an unintended strategy.
    """
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    (runtime_root / "retrieval_tuning.yaml").write_text("fusion: not-a-strategy\n", encoding="utf-8")
    monkeypatch.setattr(runtime, "RUNTIME", runtime_root)
    monkeypatch.setattr(runtime, "_CURRENT", None)

    with pytest.raises(Exception, match="fusion"):
        runtime.get_settings_bundle()
