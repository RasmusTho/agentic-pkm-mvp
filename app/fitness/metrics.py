from __future__ import annotations

import math
import time
from statistics import fmean
from typing import Dict, List, Sequence
from uuid import uuid4

from app.components.llm.fabric import LLMTaskIntent, get_embeddings_client
from app.retrieval.hybrid import MemoryHybridStore, hybrid_search, get_store
from app.stores.memory import MemoryVectorIndex

_QAS003_THRESHOLD = 0.250  # seconds
_QAS010_THRESHOLD = 2.000  # seconds


def _percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return math.inf
    data = sorted(values)
    if len(data) == 1:
        return data[0]
    idx = max(min(int(round((pct / 100.0) * len(data))) - 1, len(data) - 1), 0)
    return data[idx]


def _snapshot_store(store: MemoryHybridStore) -> List[dict]:
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


def _restore_store(store: MemoryHybridStore, docs: List[dict]) -> None:
    if docs:
        store.set_documents(docs)
    else:
        store.set_documents([])


def qas003_hybrid_latency(samples: int = 32) -> Dict[str, float]:
    """
    Measure hybrid_search latency against a deterministic corpus.
    Returns dict with p95, avg, threshold, and count.
    """
    store = get_store()
    backup = _snapshot_store(store)
    try:
        docs = [
            {
                "doc_id": f"fitness-doc-{i}",
                "text": (
                    f"Alpha knowledge base entry {i}. "
                    f"This contains beta facts and gamma reasoning for topic {i % 5}."
                ),
                "source_ref": f"fitness/{i}.md",
            }
            for i in range(24)
        ]
        store.set_documents(docs)
        queries = [
            "alpha knowledge",
            "beta facts",
            "gamma reasoning",
            "topic 3 summary",
            "knowledge base entry",
            "alpha beta gamma mix",
            "reasoning topic 1",
            "alpha insights topic 4",
        ]
        timings: List[float] = []
        for i in range(samples):
            q = queries[i % len(queries)]
            start = time.perf_counter()
            hits = hybrid_search(q, k=8)
            end = time.perf_counter()
            timings.append(end - start)
            if not hits:
                raise AssertionError("hybrid_search returned no results during fitness probe")
        return {
            "p95": _percentile(timings, 95),
            "avg": fmean(timings),
            "threshold": _QAS003_THRESHOLD,
            "count": float(len(timings)),
        }
    finally:
        _restore_store(store, backup)


def _process_outbox_event(
    payload: Dict[str, str],
    *,
    vector_index: MemoryVectorIndex,
) -> None:
    client = get_embeddings_client(LLMTaskIntent(task_kind="embed", determinism_required=True))
    vec = client.embed_text(payload["text"])
    identity = client.identity
    vector_index.upsert(
        uuid4(),
        kind="fitness",
        source_ref=payload.get("source_ref", "fitness"),
        payload={"title": payload["title"]},
        embedding=list(vec),
        model=identity.model,
        identity=identity,
    )


def qas010_outbox_to_index_latency(events: int = 32) -> Dict[str, float]:
    """
    Measure synthetic outbox -> index propagation latency in-memory.
    """
    index = MemoryVectorIndex()
    latencies: List[float] = []
    for i in range(events):
        payload = {
            "title": f"Fitness payload {i}",
            "text": f"Gamma delta epsilon block {i} with structured facts.",
            "source_ref": f"fitness/outbox/{i}",
        }
        created = time.perf_counter()
        _process_outbox_event(payload, vector_index=index)
        latencies.append(time.perf_counter() - created)
    return {
        "p95": _percentile(latencies, 95),
        "avg": fmean(latencies),
        "threshold": _QAS010_THRESHOLD,
        "count": float(len(latencies)),
    }


__all__ = [
    "qas003_hybrid_latency",
    "qas010_outbox_to_index_latency",
]
