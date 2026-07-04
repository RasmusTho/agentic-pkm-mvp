"""`python -m app.eval.run` — deterministic retrieval/memory/classification metrics runner.

Thin CLI entrypoint over `app.eval.golden.evaluate_bilingual_golden_set`
(itself built on `app.eval.benchmark`'s regression-gate machinery) plus the
intent-classification golden set (`app.eval.classification`, KERNEL-13). No
new eval framework: this module wires the existing golden-set runners into a
scorecard, prints a human summary, and exits non-zero when any sliced
metric falls below the thresholds in `config/eval_thresholds.yaml`
(documented at `docs/eval.md :: Metrics`) or when the classification
hard gate trips (mutation-side confusion — blocking, never thresholded).

Runs fully offline — deterministic golden-set retrieval plus replayed
classifier completions only, no live LLM calls. Ragas/DeepEval eval suites
stay opt-in behind `@pytest.mark.eval` and are not part of this default run
path.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping

import yaml

from app.eval.classification import evaluate_classification_golden_set
from app.eval.compare import (
    DEFAULT_RELATIVE_TOLERANCE,
    ScorecardCompareError,
    compare_scorecard_files,
    render_compare_summary,
)
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


def _check_classification(
    classification: dict, thresholds: dict | None
) -> List[ThresholdFailure]:
    """Threshold read-side classification metrics and enforce the hard gate.

    The mutation-side hard gate (KERNEL-13) is deliberately NOT a threshold:
    any expected exploratory/unknown case classified into an action-capable
    class is a blocking regression regardless of configuration.
    """
    metrics = {
        "macro_precision": classification["macro_precision"],
        "macro_recall": classification["macro_recall"],
        "pass_rate": classification["pass_rate"],
        "answer_rate": classification["safe_fail"]["answer_rate"],
        "unknown_safe_fail_rate": classification["unknown"]["safe_fail_rate"],
    }
    failures = _check_bucket("classification", metrics, thresholds)
    for confusion in classification["mutation_side_confusions"]:
        failures.append(
            ThresholdFailure(
                scope="classification:hard_gate",
                metric=(
                    "mutation_side_confusion:"
                    f"{confusion['case_id']}->{confusion['predicted_intent']}"
                ),
                value=1.0,
                threshold=0.0,
            )
        )
    return failures


def build_scorecard(
    k: int | None = None,
    thresholds: dict | None = None,
    classification_completions: Mapping[str, str] | None = None,
) -> Dict:
    thresholds = thresholds if thresholds is not None else load_thresholds()
    k = k if k is not None else int(thresholds.get("k", 5))

    result = evaluate_bilingual_golden_set(k=k)
    classification = evaluate_classification_golden_set(
        completions=classification_completions
    )

    failures: List[ThresholdFailure] = []
    failures += _check_bucket("aggregate", result["aggregate"], thresholds.get("aggregate"))
    for lang, metrics in result["by_language"].items():
        failures += _check_bucket(f"language:{lang}", metrics, thresholds.get("per_language"))
    failures += _check_bucket("memory_recall", result["memory_recall"], thresholds.get("memory_recall"))
    failures += _check_classification(classification, thresholds.get("classification"))

    scorecard = {
        "schema_version": "eval_scorecard.v1",
        "k": k,
        "thresholds": thresholds,
        "aggregate": result["aggregate"],
        "by_language": result["by_language"],
        "by_slice": result["by_slice"],
        "memory_recall": result["memory_recall"],
        "memory_recall_route_intents": sorted(MEMORY_RECALL_ROUTE_INTENTS),
        "classification": classification,
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
    cls = scorecard["classification"]
    lines.append(f"Intent-classification slice ({cls['mode']}, n={cls['n_cases']}):")
    for name, metrics in cls["per_class"].items():
        lines.append(
            f"  {name}: precision={metrics['precision']:.4f} "
            f"recall={metrics['recall']:.4f} (support={metrics['support']})"
        )
    lines.append(
        f"  macro: precision={cls['macro_precision']:.4f} recall={cls['macro_recall']:.4f} "
        f"pass_rate={cls['pass_rate']:.4f} answer_rate={cls['safe_fail']['answer_rate']:.4f}"
    )
    unknown = cls["unknown"]
    lines.append(
        f"  unknown safe-fail: {unknown['safe_fail_hits']}/{unknown['expected']} "
        f"(rate={unknown['safe_fail_rate']:.4f}); "
        f"answerable safe-fails={cls['safe_fail']['count']}"
    )
    lines.append("  Confusion matrix (expected -> predicted):")
    for expected, row in cls["confusion_matrix"].items():
        cells = " ".join(f"{predicted}={count}" for predicted, count in row.items() if count)
        lines.append(f"    {expected}: {cells or '-'}")
    if cls["mutation_side_confusions"]:
        lines.append("  HARD GATE VIOLATIONS (mutation-side confusion, blocking):")
        for confusion in cls["mutation_side_confusions"]:
            lines.append(
                f"    - {confusion['case_id']}: expected {confusion['expected_intent']} "
                f"-> predicted {confusion['predicted_intent']}"
            )
    else:
        lines.append("  Hard gate: no mutation-side confusion.")
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


def run_default() -> int:
    """Default (no-subcommand) behavior: build + write + gate the scorecard."""
    scorecard = build_scorecard()
    write_scorecard(scorecard)
    print(render_summary(scorecard))
    print(f"\nScorecard written to {SCORECARD_PATH}")
    return 1 if scorecard["regression"] else 0


def run_compare(
    baseline: Path,
    candidate: Path,
    *,
    tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
    output: Path | None = None,
) -> int:
    """`compare` subcommand: deterministic baseline-vs-candidate report.

    Operates purely on the two already-produced `eval_scorecard.v1` files —
    no golden-set re-run, no live LLM. Exit code is 1 only on a
    `regression` verdict (KERNEL-14).
    """
    try:
        comparison = compare_scorecard_files(baseline, candidate, tolerance=tolerance)
    except ScorecardCompareError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(render_compare_summary(comparison))
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
        print(f"\nCompare artifact written to {output}")
    return 1 if comparison["verdict"] == "regression" else 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.eval.run",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")
    compare_parser = subparsers.add_parser(
        "compare",
        help="Compare two eval_scorecard.v1 files (baseline vs candidate).",
    )
    compare_parser.add_argument(
        "--baseline", type=Path, required=True, help="Path to the baseline scorecard JSON."
    )
    compare_parser.add_argument(
        "--candidate", type=Path, required=True, help="Path to the candidate scorecard JSON."
    )
    compare_parser.add_argument(
        "--tolerance",
        type=float,
        default=DEFAULT_RELATIVE_TOLERANCE,
        help=(
            "Relative worsening fraction flagged as regression "
            f"(default {DEFAULT_RELATIVE_TOLERANCE})."
        ),
    )
    compare_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write the machine-readable compare artifact (JSON).",
    )
    return parser


def main(argv: List[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "compare":
        return run_compare(
            args.baseline,
            args.candidate,
            tolerance=args.tolerance,
            output=args.output,
        )
    return run_default()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
