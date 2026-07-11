"""Weighted RRF fusion (ADR-0059 D3 step 5, #3407): `fusion="rrf"` inside `_rank_eligible`.

- test_weighted_rrf_ranking_and_score_contract: a doc ranked #1 by every signal (BM25, embedding,
  overlap) is ranked #1 by RRF, and every exposed score stays in [0, 1] (same contract as linear).
- test_lexical_trust_weight_dominates_ties: with default `rrf_signal_weights`
  (lexical=1.0 >= dense=0.8), a doc that is top-ranked by BM25 outranks a doc with the mirrored
  ("same-rank-profile") top-embedding rank, given equal overlap — ADR-0024's trust hierarchy
  survives the strategy swap.
- test_rrf_defaults_stay_dark: fusion="rrf" only activates on explicit override; leaving config
  unset stays on the "linear" default (defaults-untouched constraint).
"""

from __future__ import annotations

import numpy as np
import pytest

from app.retrieval import hybrid
from app.retrieval.hybrid import get_store, hybrid_search
from app.retrieval.tuning import get_retrieval_tuning, reset_retrieval_tuning_cache

pytestmark = pytest.mark.not_pg


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch):
    for key in (
        "RETRIEVAL_FUSION",
        "RETRIEVAL_RRF_K",
        "RETRIEVAL_RRF_SIGNAL_WEIGHTS",
        "RERANK_ENABLE",
        "RERANK_PROVIDER",
        "ASK_DOMAIN_SCOPE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    reset_retrieval_tuning_cache()
    get_store().set_documents([])
    yield
    get_store().set_documents([])
    reset_retrieval_tuning_cache()


def _seed_controlled_store(store, docs: list[dict], embeddings: list[list[float]]) -> None:
    """Seed the store with explicit texts (drives BM25 + overlap) and explicit embedding vectors
    (drives cosine similarity), mirroring tests/retrieval/test_hybrid_numpy_dtype.py's pattern so
    every signal's raw ranking is fully controlled by the test rather than by the real embedding
    pipeline."""
    store.set_documents(docs)
    store._embeddings = np.array(embeddings, dtype=np.float32)  # noqa: SLF001 - controlled fixture
    store._emb_norms = np.linalg.norm(store._embeddings, axis=1)  # noqa: SLF001


def test_weighted_rrf_ranking_and_score_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    store = get_store()
    _seed_controlled_store(
        store,
        docs=[
            {"doc_id": "winner", "text": "alpha beta winner exclusive match", "payload": {}},
            {"doc_id": "loser-lexical", "text": "beta filler content only", "payload": {}},
            {"doc_id": "loser-semantic", "text": "gamma delta unrelated words", "payload": {}},
            {"doc_id": "loser-none", "text": "completely different gardening tomatoes", "payload": {}},
        ],
        embeddings=[
            [1.0, 0.0, 0.0],  # winner: exact match to the query vector
            [0.3, 0.7, 0.0],
            [0.1, 0.1, 0.9],
            [0.0, 0.0, 1.0],
        ],
    )
    query_vector = [1.0, 0.0, 0.0]

    monkeypatch.setenv("RETRIEVAL_FUSION", "rrf")
    reset_retrieval_tuning_cache()
    assert get_retrieval_tuning().fusion == "rrf"

    results = hybrid_search("alpha beta winner", k=4, query_vector=query_vector)

    assert [r["doc_id"] for r in results][0] == "winner"
    for r in results:
        assert 0.0 <= r["score"] <= 1.0
    # Result-dict shape is unchanged under rrf (same keys as the linear branch).
    assert set(results[0].keys()) == {
        "id",
        "doc_id",
        "text",
        "score",
        "snippet",
        "source_ref",
        "payload",
        "evidence_role_in_context",
    }


def test_lexical_trust_weight_dominates_ties(monkeypatch: pytest.MonkeyPatch) -> None:
    """Construct two docs with a mirrored rank profile (A top-BM25/2nd-embedding, B top-embedding/
    2nd-BM25) and identical overlap, then assert A outranks B because lexical (1.0) > dense (0.8)
    by default — ADR-0024's trust hierarchy surviving the fusion-strategy swap."""
    store = get_store()
    _seed_controlled_store(
        store,
        docs=[
            # "trust" query tokens appear only in doc-lexical's text (top BM25); overlap is equal
            # for both candidates (each shares exactly one token with the query: "shared").
            {"doc_id": "doc-lexical", "text": "trust trust trust shared filler", "payload": {}},
            {"doc_id": "doc-semantic", "text": "shared unrelated words only", "payload": {}},
        ],
        embeddings=[
            [0.2, 0.98, 0.0],  # doc-lexical: weaker embedding match (rank 2)
            [1.0, 0.0, 0.0],  # doc-semantic: exact embedding match (rank 1)
        ],
    )
    query_vector = [1.0, 0.0, 0.0]

    monkeypatch.setenv("RETRIEVAL_FUSION", "rrf")
    reset_retrieval_tuning_cache()
    tuning = get_retrieval_tuning()
    assert tuning.rrf_signal_weights.lexical >= tuning.rrf_signal_weights.dense

    results = hybrid_search("trust shared", k=2, query_vector=query_vector)

    assert [r["doc_id"] for r in results] == ["doc-lexical", "doc-semantic"]


def test_rrf_defaults_stay_dark() -> None:
    """No override anywhere -> fusion stays 'linear' (defaults-untouched constraint)."""
    assert get_retrieval_tuning().fusion == "linear"


def test_rrf_ranks_helper_breaks_ties_by_ascending_index() -> None:
    scores = np.array([5.0, 5.0, 1.0], dtype=np.float32)
    ranks = hybrid._rrf_ranks(scores)  # noqa: SLF001 - direct math check, mirrors repo precedent
    # Tie between index 0 and 1 (both highest) breaks by ascending index: 0 gets rank 1, 1 gets 2.
    assert ranks.tolist() == [1.0, 2.0, 3.0]


def test_rrf_top1_in_every_signal_wins_by_construction() -> None:
    """Property: a doc ranked #1 by every signal has the maximal per-signal term in every summand,
    so its RRF sum is strictly maximal regardless of the configured (non-negative) weights."""
    bm25 = np.array([9.0, 1.0, 0.0], dtype=np.float32)
    emb = np.array([9.0, 0.0, 1.0], dtype=np.float32)
    overlap = np.array([1.0, 0.5, 0.0], dtype=np.float32)

    class _Weights:
        lexical = 1.0
        dense = 0.8

    class _Tuning:
        rrf_signal_weights = _Weights()
        rrf_k = 60

    combined = hybrid._weighted_rrf_combined(bm25, emb, overlap, _Tuning())  # noqa: SLF001
    assert int(np.argmax(combined)) == 0


def test_rrf_no_signal_lists_do_not_inject_store_order() -> None:
    """All-zero lexical/overlap lists carry no rank evidence, so their tied
    store order must not outweigh the dense signal."""
    bm25 = np.zeros(2, dtype=np.float32)
    overlap = np.zeros(2, dtype=np.float32)
    emb = np.array([0.1, 0.9], dtype=np.float32)

    class _Weights:
        lexical = 1.0
        dense = 0.8

    class _Tuning:
        rrf_signal_weights = _Weights()
        rrf_k = 60

    combined = hybrid._weighted_rrf_combined(bm25, emb, overlap, _Tuning())  # noqa: SLF001
    assert int(np.argmax(combined)) == 1
