from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from statistics import fmean
from typing import Dict, List

import math

from app.retrieval.hybrid import get_store, hybrid_search

DATA_ROOT = Path("data") / "golden"
CORPUS_PATH = DATA_ROOT / "corpus.jsonl"
JUDGMENTS_PATH = DATA_ROOT / "judgments.json"
BILINGUAL_CORPUS_PATH = DATA_ROOT / "bilingual_corpus.jsonl"
BILINGUAL_JUDGMENTS_PATH = DATA_ROOT / "bilingual_judgments.json"

# route_intent values used by the W2-EVAL-01 bilingual seed
# (docs/eval/retrieval_bilingual_seed.yaml) that count as memory-recall slices:
# recall-into-ASK and low-trust-citation retrieval.
MEMORY_RECALL_ROUTE_INTENTS = {"recall_into_ask", "low_trust_citation"}


@contextmanager
def _temporary_env(values: Dict[str, str | None]):
    old = {k: os.environ.get(k) for k in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _snapshot_store(store) -> List[dict]:
    return [
        {
            "doc_id": doc.doc_id,
            "text": doc.text,
            "language": doc.language,
            "source_ref": doc.source_ref,
            "payload": doc.payload,
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


def evaluate_golden_set(k: int = 5, *, rerank_provider: str | None = None) -> Dict[str, dict]:
    store = get_store()
    backup = _snapshot_store(store)
    corpus = load_corpus()
    judgments = load_judgments()
    env_updates = {"RERANK_ENABLE": None, "RERANK_PROVIDER": None}
    if rerank_provider:
        env_updates["RERANK_ENABLE"] = "1"
        env_updates["RERANK_PROVIDER"] = rerank_provider
    try:
        with _temporary_env(env_updates):
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


def evaluate_vs_baseline(provider: str, *, k: int = 10) -> Dict[str, Dict[str, float]]:
    baseline = evaluate_golden_set(k=k, rerank_provider=None)["aggregate"]
    candidate = evaluate_golden_set(k=k, rerank_provider=provider)["aggregate"]
    return {"baseline": baseline, "candidate": candidate}


def load_bilingual_corpus() -> List[dict]:
    corpus: List[dict] = []
    with BILINGUAL_CORPUS_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            corpus.append(json.loads(line))
    return corpus


def load_bilingual_judgments() -> Dict[str, list]:
    return json.loads(BILINGUAL_JUDGMENTS_PATH.read_text(encoding="utf-8"))


def evaluate_bilingual_golden_set(k: int = 5, *, rerank_provider: str | None = None) -> Dict[str, dict]:
    """Evaluate the W2-EVAL-01 bilingual deterministic seed.

    Returns per-query metrics plus aggregates sliced by language and by
    `route_intent` (the seed's slice taxonomy: exact_lexical, hybrid_semantic,
    recall_into_ask, low_trust_citation). `recall_into_ask` and
    `low_trust_citation` together form the memory-recall slice (recall-into-ASK
    / low-trust citation) required by W2.
    """
    store = get_store()
    backup = _snapshot_store(store)
    corpus = load_bilingual_corpus()
    judgments = load_bilingual_judgments()
    env_updates = {"RERANK_ENABLE": None, "RERANK_PROVIDER": None}
    if rerank_provider:
        env_updates["RERANK_ENABLE"] = "1"
        env_updates["RERANK_PROVIDER"] = rerank_provider
    try:
        with _temporary_env(env_updates):
            store.set_documents(corpus)
            per_query = []
            for case in judgments.get("queries", []):
                relevant_map = {
                    entry["doc_id"]: entry.get("relevance", 0)
                    for entry in case.get("relevance", [])
                }
                hits = hybrid_search(case["query"], k=k)
                scores = [float(relevant_map.get(hit["doc_id"], 0)) for hit in hits]
                per_query.append(
                    {
                        "id": case["id"],
                        "query": case["query"],
                        "language": case["language"],
                        "route_intent": case["route_intent"],
                        "precision@k": precision_at_k(scores, k),
                        "ndcg@k": ndcg_at_k(scores, k),
                    }
                )

            def _aggregate(entries: List[dict]) -> Dict[str, float]:
                if not entries:
                    return {"precision@k": 0.0, "ndcg@k": 0.0, "count": 0}
                return {
                    "precision@k": fmean(e["precision@k"] for e in entries),
                    "ndcg@k": fmean(e["ndcg@k"] for e in entries),
                    "count": len(entries),
                }

            by_language: Dict[str, dict] = {}
            for lang in sorted({e["language"] for e in per_query}):
                by_language[lang] = _aggregate([e for e in per_query if e["language"] == lang])

            by_slice: Dict[str, dict] = {}
            for slice_name in sorted({e["route_intent"] for e in per_query}):
                by_slice[slice_name] = _aggregate(
                    [e for e in per_query if e["route_intent"] == slice_name]
                )

            memory_recall_entries = [
                e for e in per_query if e["route_intent"] in MEMORY_RECALL_ROUTE_INTENTS
            ]
            memory_recall = _aggregate(memory_recall_entries)

            aggregate = _aggregate(per_query)

            return {
                "aggregate": aggregate,
                "by_language": by_language,
                "by_slice": by_slice,
                "memory_recall": memory_recall,
                "queries": per_query,
            }
    finally:
        _restore_store(store, backup)


__all__ = [
    "precision_at_k",
    "ndcg_at_k",
    "evaluate_golden_set",
    "evaluate_vs_baseline",
    "load_bilingual_corpus",
    "load_bilingual_judgments",
    "evaluate_bilingual_golden_set",
    "MEMORY_RECALL_ROUTE_INTENTS",
]
