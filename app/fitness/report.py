from __future__ import annotations

import json
import os
import sys

from app.eval.golden import evaluate_vs_baseline
from .metrics import qas003_hybrid_latency, qas010_outbox_to_index_latency
from .relations import relation_metrics


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
    relation_stats = relation_metrics()
    coverage = relation_stats["coverage"]
    validity = relation_stats["validity"]
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
    delta_p = golden["candidate"]["precision@k"] - golden["baseline"]["precision@k"]
    delta_ndcg = golden["candidate"]["ndcg@k"] - golden["baseline"]["ndcg@k"]
    print(
        _summary_line(
            "EVAL DELTA",
            DP10=f"{delta_p:+.3f}",
            DnDCG10=f"{delta_ndcg:+.3f}",
            RELATION_TARGET="60%",
        )
    )
    print(_summary_line("RELATION", COVERAGE=f"{coverage:.2f}%"))
    print(
        _summary_line(
            "RELATIONS",
            coverage=f"{coverage:.2f}%",
            validity=f"{validity:.2f}%",
            target="95%",
        )
    )

    fail = False
    provider_spec = (provider or "").strip().lower()
    require_gain = provider_spec in {"ce_local", "local"}
    if qas003["p95"] > qas003["threshold"] or qas010["p95"] > qas010["threshold"]:
        fail = True
    if require_gain:
        meets_delta = (delta_p >= 0.005) or (delta_ndcg >= 0.01)
        if not meets_delta:
            fail = True
    min_coverage = float(os.getenv("RELATION_COVERAGE_MIN", "95"))
    if coverage < min_coverage:
        fail = True
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
