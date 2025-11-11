from __future__ import annotations

import json
from pathlib import Path
from statistics import fmean
from typing import Dict, List

import math

from app.retrieval.hybrid import get_store, hybrid_search

DATA_ROOT = Path("data") / "golden"
CORPUS_PATH = DATA_ROOT / "corpus.jsonl"
JUDGMENTS_PATH = DATA_ROOT / "judgments.json"


def _snapshot_store(store) -> List[dict]:
    return [
        {
            "doc_id": doc.doc_id,
            "text": doc.text,
            "language": doc.language,
            "source_ref": doc.source_ref,
        }
        for doc in store.all()
    ]


def _restore_store(store, docs: List[dict]) -> None:
    store.set_documents(docs)


def precision_at_k(relevances: List[float], k: int) -> float:
    if k <= 0:
        return 0.0
    top = relevances[:k]
    hits = sum(1 for score in top if score > 0)
    return hits / k


def ndcg_at_k(relevances: List[float], k: int) -> float:
    def _dcg(scores: List[float]) -> float:
        total = 0.0
        for idx, score in enumerate(scores, start=1):
            total += (2 ** score - 1) / (math.log2(idx + 1))
        return total

    top = relevances[:k]
    ideal = sorted(relevances, reverse=True)[:k]
    denom = _dcg(ideal)
    if denom == 0:
        return 0.0
    return _dcg(top) / denom


def load_corpus() -> List[dict]:
    corpus: List[dict] = []
    with CORPUS_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            corpus.append(json.loads(line))
    return corpus


def load_judgments() -> Dict[str, List[dict]]:
    return json.loads(JUDGMENTS_PATH.read_text(encoding="utf-8"))


def evaluate_golden_set(k: int = 5) -> Dict[str, dict]:
    store = get_store()
    backup = _snapshot_store(store)
    corpus = load_corpus()
    judgments = load_judgments()
    try:
        store.set_documents(corpus)
        per_query = []
        for case in judgments.get("queries", []):
            relevant_map = {entry["doc_id"]: entry.get("relevance", 0) for entry in case.get("relevance", [])}
            hits = hybrid_search(case["query"], k=k)
            scores = [float(relevant_map.get(hit["doc_id"], 0)) for hit in hits]
            metrics = {
                "precision@k": precision_at_k(scores, k),
                "ndcg@k": ndcg_at_k(scores, k),
            }
            per_query.append({"query": case["query"], **metrics})
        aggregate = {
            "precision@k": fmean(entry["precision@k"] for entry in per_query),
            "ndcg@k": fmean(entry["ndcg@k"] for entry in per_query),
        }
        return {"aggregate": aggregate, "queries": per_query}
    finally:
        _restore_store(store, backup)


__all__ = [
    "precision_at_k",
    "ndcg_at_k",
    "evaluate_golden_set",
]
