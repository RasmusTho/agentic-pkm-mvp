from __future__ import annotations

import pytest

from app.eval.golden import evaluate_golden_set, evaluate_vs_baseline, ndcg_at_k, precision_at_k

pytestmark = pytest.mark.not_pg


def test_precision_bounds() -> None:
    relevances = [1, 0, 1, 0]
    assert precision_at_k(relevances, 2) == 0.5


def test_ndcg_bounds() -> None:
    relevances = [3, 2, 0]
    score = ndcg_at_k(relevances, 3)
    assert 0 <= score <= 1


def test_golden_eval_pipeline() -> None:
    result = evaluate_golden_set(k=3)
    agg = result["aggregate"]
    assert 0 <= agg["precision@k"] <= 1
    assert 0 <= agg["ndcg@k"] <= 1
    assert len(result["queries"]) >= 1


def test_ce_local_meets_eval_thresholds() -> None:
    metrics = evaluate_vs_baseline("ce_local", k=10)
    base = metrics["baseline"]
    cand = metrics["candidate"]
    delta_p = cand["precision@k"] - base["precision@k"]
    delta_ndcg = cand["ndcg@k"] - base["ndcg@k"]
    assert 0 <= base["precision@k"] <= 1
    assert 0 <= cand["precision@k"] <= 1
    assert 0 <= base["ndcg@k"] <= 1
    assert 0 <= cand["ndcg@k"] <= 1
    assert delta_p >= 0.005 or delta_ndcg >= 0.01
