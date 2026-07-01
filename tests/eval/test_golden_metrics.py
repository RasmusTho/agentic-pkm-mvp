from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.eval.golden import (
    MEMORY_RECALL_ROUTE_INTENTS,
    evaluate_bilingual_golden_set,
    evaluate_golden_set,
    evaluate_vs_baseline,
    ndcg_at_k,
    precision_at_k,
)

pytestmark = pytest.mark.not_pg

BILINGUAL_CORPUS_PATH = Path("data/golden/bilingual_corpus.jsonl")
BILINGUAL_JUDGMENTS_PATH = Path("data/golden/bilingual_judgments.json")
CANONICAL_REVIEW_STATES = {"draft", "provisional", "reviewed", "protected", "archived"}


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


def test_bilingual_ground_truth_resolves() -> None:
    corpus_ids: set[str] = set()
    languages: set[str] = set()
    for line in BILINGUAL_CORPUS_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        doc = json.loads(line)
        corpus_ids.add(str(doc["doc_id"]))
        languages.add(str(doc["language"]))
        assert doc["review_state"] in CANONICAL_REVIEW_STATES
        payload = doc.get("payload") or {}
        assert payload.get("trust") == doc["trust"]
        assert payload.get("review_state") == doc["review_state"]

    judgments = json.loads(BILINGUAL_JUDGMENTS_PATH.read_text(encoding="utf-8"))
    assert judgments["schema_version"] == "retrieval_bilingual_judgments.v1"
    assert languages == {"sv", "en"}

    for case in judgments["queries"]:
        assert case["language"] in {"sv", "en"}
        assert case["relevance"], f"{case['id']} must name relevant docs"
        unresolved = {
            entry["doc_id"]
            for entry in case["relevance"]
            if entry["doc_id"] not in corpus_ids
        }
        assert not unresolved, (
            f"{case['id']} references unresolved data/golden doc ids: "
            f"{sorted(unresolved)}"
        )


def test_per_language_metrics() -> None:
    """#2320: the runner must report precision@k/ndcg@k per language over the
    W2-EVAL-01 bilingual seed, in addition to per-slice and aggregate."""
    result = evaluate_bilingual_golden_set(k=5)

    assert set(result["by_language"]) == {"en", "sv"}
    for lang, metrics in result["by_language"].items():
        assert 0 <= metrics["precision@k"] <= 1
        assert 0 <= metrics["ndcg@k"] <= 1
        assert metrics["count"] > 0

    # per-slice (route_intent) coverage over the current seed taxonomy.
    assert set(result["by_slice"]) == {
        "exact_lexical",
        "hybrid_semantic",
        "recall_into_ask",
        "low_trust_citation",
    }
    for metrics in result["by_slice"].values():
        assert 0 <= metrics["precision@k"] <= 1
        assert 0 <= metrics["ndcg@k"] <= 1

    assert 0 <= result["aggregate"]["precision@k"] <= 1
    assert 0 <= result["aggregate"]["ndcg@k"] <= 1
    assert result["aggregate"]["count"] == len(result["queries"])


def test_memory_recall_slice() -> None:
    """#2320: the runner must score a memory-recall slice (recall-into-ASK /
    low-trust citation) with deterministic ground truth from the bilingual
    seed's `recall_into_ask` and `low_trust_citation` route_intents."""
    result = evaluate_bilingual_golden_set(k=5)

    memory_recall = result["memory_recall"]
    assert 0 <= memory_recall["precision@k"] <= 1
    assert 0 <= memory_recall["ndcg@k"] <= 1

    expected_count = sum(
        1 for q in result["queries"] if q["route_intent"] in MEMORY_RECALL_ROUTE_INTENTS
    )
    assert memory_recall["count"] == expected_count > 0

    # Ground truth is deterministic: recomputing directly from the queries
    # sliced by route_intent must match the memory_recall aggregate.
    from statistics import fmean

    recall_entries = [q for q in result["queries"] if q["route_intent"] in MEMORY_RECALL_ROUTE_INTENTS]
    assert memory_recall["precision@k"] == fmean(e["precision@k"] for e in recall_entries)
    assert memory_recall["ndcg@k"] == fmean(e["ndcg@k"] for e in recall_entries)
