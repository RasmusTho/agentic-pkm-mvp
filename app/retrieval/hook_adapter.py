from __future__ import annotations

import math
from typing import Any, Dict, List

import numpy as np
from rank_bm25 import BM25Okapi

from app.retrieval.hybrid_rerank_hook import apply_optional_rerank
from app.retrieval.tuning import get_retrieval_tuning


def _bm25_dominance_margin(query: str, items: List[Dict[str, Any]]) -> float | None:
    """Deterministic score-margin signal for the conditional rerank gate (ADR-0059 D3 step 5,
    #3407): the gap between the top-1 and top-2 normalized-BM25 scores.

    BM25 is recomputed fresh over the current admitted candidate set's texts — a self-contained
    re-tokenization, deliberately NOT the corpus-wide BM25 already folded into the fused ranking
    score. That keeps the gate independent of which fusion strategy produced ``items`` (linear or
    rrf) and needs no new field threaded through the exposed result-dict contract (the ranking
    contract preserves the current shape under every strategy per ADR-0059 D3).

    Returns ``None`` when a margin is not meaningfully defined (fewer than 2 items, or no
    query/document tokens at all) — callers must treat ``None`` as "not dominant" and rerank.
    """
    if len(items) < 2:
        return None
    query_tokens = query.lower().split()
    if not query_tokens:
        return None
    tokenized_docs = [str(it.get("text", "")).lower().split() for it in items]
    if not any(tokenized_docs):
        return None
    bm25 = BM25Okapi(tokenized_docs)
    raw = np.asarray(bm25.get_scores(query_tokens), dtype=np.float32)
    min_v = float(np.min(raw))
    max_v = float(np.max(raw))
    if math.isclose(max_v - min_v, 0.0):
        # Rank-BM25's IDF can collapse to zero for a two-result window even
        # when one result uniquely contains every query term. Preserve the
        # same deterministic lexical intent with a bounded coverage fallback;
        # absent a coverage gap this remains a genuine non-dominant tie.
        if len(items) == 2:
            query_terms = set(query_tokens)
            coverage = np.asarray(
                [len(query_terms & set(tokens)) / len(query_terms) for tokens in tokenized_docs],
                dtype=np.float32,
            )
            # ``items`` is already ranked. Only the current top candidate's
            # coverage can establish lexical dominance; a better runner-up
            # must still reach the reranker.
            return float(coverage[0] - coverage[1])
        # Every candidate scores identically -> no dominant top result.
        return 0.0
    norm = (raw - min_v) / (max_v - min_v)
    top_two = np.sort(norm)[::-1][:2]
    return float(top_two[0] - top_two[1])


def maybe_rerank(query: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rerank gate (ADR-0059 D3, #3404/#3407): reads the process-resolved RetrievalTuning surface.

    ``RERANK_ENABLE`` keeps working as an override into that surface (compat) — see
    ``app.retrieval.tuning``.

    - ``"off"`` (default): pass through unchanged.
    - ``"always"``: reranks every result through the existing optional rerank hook.
    - ``"conditional"`` (deterministic score-margin gate, not a keyword classifier): skips rerank
      when the top BM25 result already dominates by at least ``rerank_score_margin`` (exact-match
      queries are where reranking measurably hurts); otherwise reranks like ``"always"``. Results
      pass through unchanged when gated off. Containment (``_contain_rerank`` in
      ``app/retrieval/hybrid.py``) applies identically whenever rerank actually runs.
    """
    tuning = get_retrieval_tuning()
    if tuning.rerank == "off":
        return items
    if tuning.rerank == "conditional":
        margin = _bm25_dominance_margin(query, items)
        if margin is not None and margin >= tuning.rerank_score_margin:
            return items
        return apply_optional_rerank(query, items)
    # "always"
    return apply_optional_rerank(query, items)
