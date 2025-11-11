from __future__ import annotations

import json
import os
import sys

from app.eval.golden import evaluate_vs_baseline
from .metrics import qas003_hybrid_latency, qas010_outbox_to_index_latency
from .relations import promotion_relation_coverage


def _summary_line(label: str, **metrics: float) -> str:
    parts = [label]
    for key, value in metrics.items():
        parts.append(f"{key}={value}")
    return "CI SUMMARY " + " ".join(parts)


def main() -> None:
    qas003 = qas003_hybrid_latency()
    qas010 = qas010_outbox_to_index_latency()
    provider = os.getenv("CI_EVAL_RERANK_PROVIDER", "ce_local")
    eval_k = int(os.getenv("CI_EVAL_K", "10"))
    golden = evaluate_vs_baseline(provider, k=eval_k)
    coverage = promotion_relation_coverage()
    payload = {
        "QAS-003": qas003,
        "QAS-010": qas010,
        "golden": golden,
        "relation_coverage_percent": coverage,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))

    print(
        _summary_line(
            "LATENCY",
            QAS003=f"{qas003['p95']:.6f}s",
            QAS010=f"{qas010['p95']:.6f}s",
        )
    )
    print(
        _summary_line(
            "EVAL",
            P10=f"{golden['candidate']['precision@k']:.3f}",
            NDCG10=f"{golden['candidate']['ndcg@k']:.3f}",
            BASE_P10=f"{golden['baseline']['precision@k']:.3f}",
            BASE_NDCG10=f"{golden['baseline']['ndcg@k']:.3f}",
        )
    )
    print(_summary_line("RELATION", COVERAGE=f"{coverage:.2f}%"))

    fail = False
    if qas003["p95"] > qas003["threshold"] or qas010["p95"] > qas010["threshold"]:
        fail = True
    if golden["candidate"]["precision@k"] < golden["baseline"]["precision@k"]:
        fail = True
    if golden["candidate"]["ndcg@k"] < golden["baseline"]["ndcg@k"]:
        fail = True
    min_coverage = float(os.getenv("RELATION_COVERAGE_MIN", "50"))
    if coverage < min_coverage:
        fail = True
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
