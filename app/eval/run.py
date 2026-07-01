"""`python -m app.eval.run` — deterministic retrieval/memory metrics runner.

Thin CLI entrypoint over `app.eval.golden.evaluate_bilingual_golden_set`
(itself built on `app.eval.benchmark`'s regression-gate machinery). No new
eval framework: this module wires the existing golden-set runner into a
scorecard, prints a human summary, and exits non-zero when any sliced
metric falls below the thresholds in `config/eval_thresholds.yaml`
(documented at `docs/eval.md :: Metrics`).

Runs fully offline — deterministic golden-set retrieval only, no live LLM
calls. Ragas/DeepEval eval suites stay opt-in behind `@pytest.mark.eval`
and are not part of this default run path.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import yaml

from app.eval.golden import MEMORY_RECALL_ROUTE_INTENTS, evaluate_bilingual_golden_set

THRESHOLDS_PATH = Path("config") / "eval_thresholds.yaml"
SCORECARD_PATH = Path("runtime") / "eval" / "scorecard.json"


@dataclass
class ThresholdFailure:
    scope: str
    metric: str
    value: float
    threshold: float

    def __str__(self) -> str:
        return f"{self.scope}: {self.metric}={self.value:.4f} < required {self.threshold:.4f}"


def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _check_bucket(scope: str, metrics: dict, thresholds: dict | None) -> List[ThresholdFailure]:
    if not thresholds:
        return []
    failures: List[ThresholdFailure] = []
    for metric_key, floor in thresholds.items():
        actual = metrics.get(metric_key.replace("_at_k", "@k"))
        if actual is None:
            continue
        if actual < floor:
            failures.append(ThresholdFailure(scope=scope, metric=metric_key, value=actual, threshold=floor))
    return failures


def build_scorecard(k: int | None = None, thresholds: dict | None = None) -> Dict:
    thresholds = thresholds if thresholds is not None else load_thresholds()
    k = k if k is not None else int(thresholds.get("k", 5))

    result = evaluate_bilingual_golden_set(k=k)

    failures: List[ThresholdFailure] = []
    failures += _check_bucket("aggregate", result["aggregate"], thresholds.get("aggregate"))
    for lang, metrics in result["by_language"].items():
        failures += _check_bucket(f"language:{lang}", metrics, thresholds.get("per_language"))
    failures += _check_bucket("memory_recall", result["memory_recall"], thresholds.get("memory_recall"))

    scorecard = {
        "schema_version": "eval_scorecard.v1",
        "k": k,
        "thresholds": thresholds,
        "aggregate": result["aggregate"],
        "by_language": result["by_language"],
        "by_slice": result["by_slice"],
        "memory_recall": result["memory_recall"],
        "memory_recall_route_intents": sorted(MEMORY_RECALL_ROUTE_INTENTS),
        "queries": result["queries"],
        "regression": bool(failures),
        "failures": [
            {"scope": f.scope, "metric": f.metric, "value": f.value, "threshold": f.threshold}
            for f in failures
        ],
    }
    return scorecard


def write_scorecard(scorecard: dict, path: Path = SCORECARD_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scorecard, indent=2), encoding="utf-8")


def render_summary(scorecard: dict) -> str:
    lines = ["Deterministic retrieval/memory eval — scorecard", "=" * 60]
    lines.append(f"k = {scorecard['k']}")
    agg = scorecard["aggregate"]
    lines.append(
        f"aggregate: precision@k={agg['precision@k']:.4f} ndcg@k={agg['ndcg@k']:.4f} "
        f"(n={agg['count']})"
    )
    lines.append("")
    lines.append("Per language:")
    for lang, metrics in scorecard["by_language"].items():
        lines.append(
            f"  {lang}: precision@k={metrics['precision@k']:.4f} "
            f"ndcg@k={metrics['ndcg@k']:.4f} (n={metrics['count']})"
        )
    lines.append("")
    lines.append("Per slice (route_intent):")
    for slice_name, metrics in scorecard["by_slice"].items():
        lines.append(
            f"  {slice_name}: precision@k={metrics['precision@k']:.4f} "
            f"ndcg@k={metrics['ndcg@k']:.4f} (n={metrics['count']})"
        )
    lines.append("")
    mr = scorecard["memory_recall"]
    lines.append(
        f"Memory-recall slice ({'+'.join(scorecard['memory_recall_route_intents'])}): "
        f"precision@k={mr['precision@k']:.4f} ndcg@k={mr['ndcg@k']:.4f} (n={mr['count']})"
    )
    lines.append("")
    if scorecard["regression"]:
        lines.append("REGRESSION DETECTED:")
        for failure in scorecard["failures"]:
            lines.append(
                f"  - {failure['scope']}: {failure['metric']}={failure['value']:.4f} "
                f"< required {failure['threshold']:.4f}"
            )
    else:
        lines.append("All sliced metrics meet configured thresholds.")
    return "\n".join(lines)


def main(argv: List[str] | None = None) -> int:
    scorecard = build_scorecard()
    write_scorecard(scorecard)
    print(render_summary(scorecard))
    print(f"\nScorecard written to {SCORECARD_PATH}")
    return 1 if scorecard["regression"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
