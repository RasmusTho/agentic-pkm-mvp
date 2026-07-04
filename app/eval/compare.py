"""Baseline-vs-candidate scorecard compare (KERNEL-14, #2776).

Pure, deterministic comparison over two already-produced ``eval_scorecard.v1``
files (written by ``app.eval.run``): per-slice deltas (aggregate, per-language,
per-route-intent, memory-recall, classification incl. the KERNEL-13 confusion
slice) plus a single ``regression`` / ``improved`` / ``neutral`` verdict.

No live LLM calls, no timestamps, no RNG — the same scorecard pair always
produces byte-identical output. Delta/regression math is shared with
``app.eval.benchmark`` (``compute_metric_delta``), not re-implemented.

Verdict semantics:

- ``regression`` — any of:
  1. the candidate trips the KERNEL-13 mutation-side hard gate
     (``classification.hard_gate_passed`` is false) — blocking, never
     tolerance-relative;
  2. the candidate scorecard failed its own configured floors
     (``regression: true`` — floors come from ``config/eval_thresholds.yaml``
     at scorecard build time, which is how compare consumes them);
  3. any compared metric worsened relative to baseline by more than the
     relative tolerance (default 5 %, same as ``BenchmarkSuite.compare``);
  4. any per-language / per-route-intent slice present in the baseline is
     MISSING in the candidate — a disappeared slice is the strongest possible
     regression, never a silent shrink of the comparison surface. Keys only
     in the candidate are reported (``slice_coverage``) but do not block.
- ``improved`` — no regression and at least one metric improved beyond the
  tolerance.
- ``neutral`` — everything within tolerance.

Malformed inputs fail loud as :class:`ScorecardCompareError` — missing
required sections and non-finite metric values (NaN/±inf) included — and the
CLI maps that to exit code 2, so a broken input is never mistaken for a
genuine ``regression`` verdict (exit 1).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, List

from app.eval.benchmark import compute_metric_delta

SCORECARD_SCHEMA_VERSION = "eval_scorecard.v1"
COMPARE_SCHEMA_VERSION = "eval_scorecard_compare.v1"

# Same default relative-regression tolerance as BenchmarkSuite.compare().
DEFAULT_RELATIVE_TOLERANCE = 0.05

# Retrieval-slice metrics compared per slice; all are higher-is-better.
RETRIEVAL_METRICS = ("precision@k", "ndcg@k")

# Classification read-side metrics compared; all are higher-is-better.
CLASSIFICATION_METRICS = (
    "macro_precision",
    "macro_recall",
    "pass_rate",
    "answer_rate",
    "unknown_safe_fail_rate",
)


class ScorecardCompareError(ValueError):
    """Fail-loud error for unusable compare inputs."""


def load_scorecard(path: Path) -> Dict:
    """Load and validate one ``eval_scorecard.v1`` file (fail loud)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ScorecardCompareError(f"scorecard not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ScorecardCompareError(f"scorecard is not valid JSON: {path}: {exc}") from exc
    schema = data.get("schema_version")
    if schema != SCORECARD_SCHEMA_VERSION:
        raise ScorecardCompareError(
            f"unsupported scorecard schema_version {schema!r} in {path} "
            f"(expected {SCORECARD_SCHEMA_VERSION!r})"
        )
    return data


def _section(scorecard: Dict, label: str, key: str) -> Dict:
    """Fetch a required scorecard section, failing loud on malformed input."""
    try:
        value = scorecard[key]
    except (KeyError, TypeError) as exc:
        raise ScorecardCompareError(
            f"{label} scorecard is missing required section {key!r}"
        ) from exc
    if not isinstance(value, dict):
        raise ScorecardCompareError(
            f"{label} scorecard section {key!r} is not an object"
        )
    return value


def _require_finite(value: object, path: str) -> float:
    """Reject non-numeric and non-finite (NaN/±inf) metric values, naming the path."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScorecardCompareError(f"non-numeric metric value at {path}: {value!r}")
    if not math.isfinite(value):
        raise ScorecardCompareError(f"non-finite metric value at {path}: {value!r}")
    return float(value)


def _classification_metrics(classification: Dict, label: str) -> Dict[str, float]:
    """Flatten the read-side classification metrics compared by this seam."""
    try:
        metrics = {
            "macro_precision": classification["macro_precision"],
            "macro_recall": classification["macro_recall"],
            "pass_rate": classification["pass_rate"],
            "answer_rate": classification["safe_fail"]["answer_rate"],
            "unknown_safe_fail_rate": classification["unknown"]["safe_fail_rate"],
        }
    except (KeyError, TypeError) as exc:
        raise ScorecardCompareError(
            f"{label} scorecard classification section is missing required key {exc}"
        ) from exc
    return {
        name: _require_finite(value, f"{label}.classification.{name}")
        for name, value in metrics.items()
    }


def _validate_retrieval_bucket(bucket: object, path: str) -> Dict:
    """Validate one retrieval-metric bucket (finite leaves only)."""
    if not isinstance(bucket, dict):
        raise ScorecardCompareError(f"scorecard bucket at {path} is not an object")
    for metric in RETRIEVAL_METRICS:
        if metric in bucket:
            _require_finite(bucket[metric], f"{path}.{metric}")
    return bucket


def _metric_row(
    metric: str,
    baseline_value: float,
    candidate_value: float,
    tolerance: float,
) -> Dict:
    delta, delta_pct, regression = compute_metric_delta(
        baseline_value, candidate_value, threshold=tolerance, higher_is_better=True
    )
    improved = delta_pct > tolerance
    return {
        "metric": metric,
        "baseline": baseline_value,
        "candidate": candidate_value,
        "delta": delta,
        # ±inf (zero baseline) is not valid strict JSON; report null instead.
        "delta_pct": delta_pct if math.isfinite(delta_pct) else None,
        "regression": regression,
        "improved": improved,
    }


def _compare_bucket(
    baseline_metrics: Dict,
    candidate_metrics: Dict,
    metric_names: tuple[str, ...],
    tolerance: float,
) -> List[Dict]:
    rows = []
    for metric in metric_names:
        if metric not in baseline_metrics or metric not in candidate_metrics:
            continue
        rows.append(
            _metric_row(metric, baseline_metrics[metric], candidate_metrics[metric], tolerance)
        )
    return rows


def _compare_keyed_buckets(
    baseline_group: Dict[str, Dict],
    candidate_group: Dict[str, Dict],
    tolerance: float,
) -> Dict[str, List[Dict]]:
    """Compare per-key buckets (by_language / by_slice) over common keys, sorted."""
    common = sorted(set(baseline_group) & set(candidate_group))
    return {
        key: _compare_bucket(
            baseline_group[key], candidate_group[key], RETRIEVAL_METRICS, tolerance
        )
        for key in common
    }


def _confusion_matrix_delta(baseline: Dict, candidate: Dict) -> Dict[str, Dict[str, int]]:
    """Per-cell candidate-minus-baseline confusion-matrix delta (sorted keys)."""
    delta: Dict[str, Dict[str, int]] = {}
    for expected in sorted(set(baseline) | set(candidate)):
        baseline_row = baseline.get(expected, {})
        candidate_row = candidate.get(expected, {})
        row: Dict[str, int] = {}
        for predicted in sorted(set(baseline_row) | set(candidate_row)):
            cell = int(candidate_row.get(predicted, 0)) - int(baseline_row.get(predicted, 0))
            if cell:
                row[predicted] = cell
        if row:
            delta[expected] = row
    return delta


def compare_scorecards(
    baseline: Dict,
    candidate: Dict,
    *,
    tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
) -> Dict:
    """Compare two ``eval_scorecard.v1`` dicts into a deterministic report."""
    for label, scorecard in (("baseline", baseline), ("candidate", candidate)):
        if not isinstance(scorecard, dict) or (
            scorecard.get("schema_version") != SCORECARD_SCHEMA_VERSION
        ):
            schema = scorecard.get("schema_version") if isinstance(scorecard, dict) else None
            raise ScorecardCompareError(
                f"{label} scorecard has unsupported schema_version "
                f"{schema!r} (expected {SCORECARD_SCHEMA_VERSION!r})"
            )

    # Structural + finiteness validation up front: compare accepts arbitrary
    # files, so malformed input must raise ScorecardCompareError (CLI exit 2),
    # never a raw traceback or a silent 'neutral'.
    sections: Dict[str, Dict[str, Dict]] = {}
    for label, scorecard in (("baseline", baseline), ("candidate", candidate)):
        aggregate = _validate_retrieval_bucket(
            _section(scorecard, label, "aggregate"), f"{label}.aggregate"
        )
        memory_recall = _validate_retrieval_bucket(
            _section(scorecard, label, "memory_recall"), f"{label}.memory_recall"
        )
        keyed: Dict[str, Dict[str, Dict]] = {}
        for group_name in ("by_language", "by_slice"):
            group = _section(scorecard, label, group_name)
            for key in group:
                _validate_retrieval_bucket(group[key], f"{label}.{group_name}.{key}")
            keyed[group_name] = group
        classification = _section(scorecard, label, "classification")
        sections[label] = {
            "aggregate": aggregate,
            "memory_recall": memory_recall,
            "by_language": keyed["by_language"],
            "by_slice": keyed["by_slice"],
            "classification": classification,
            "classification_metrics": _classification_metrics(classification, label),
        }

    slices: Dict = {
        "aggregate": _compare_bucket(
            sections["baseline"]["aggregate"],
            sections["candidate"]["aggregate"],
            RETRIEVAL_METRICS,
            tolerance,
        ),
        "by_language": _compare_keyed_buckets(
            sections["baseline"]["by_language"], sections["candidate"]["by_language"], tolerance
        ),
        "by_slice": _compare_keyed_buckets(
            sections["baseline"]["by_slice"], sections["candidate"]["by_slice"], tolerance
        ),
        "memory_recall": _compare_bucket(
            sections["baseline"]["memory_recall"],
            sections["candidate"]["memory_recall"],
            RETRIEVAL_METRICS,
            tolerance,
        ),
        "classification": _compare_bucket(
            sections["baseline"]["classification_metrics"],
            sections["candidate"]["classification_metrics"],
            CLASSIFICATION_METRICS,
            tolerance,
        ),
    }

    # A slice present in the baseline but missing in the candidate is the
    # strongest possible regression: the comparison surface silently shrank.
    # Blocking; candidate-only keys are reported via slice_coverage only.
    missing_slices: List[Dict] = []
    for group_name in ("by_language", "by_slice"):
        for key in sorted(
            set(sections["baseline"][group_name]) - set(sections["candidate"][group_name])
        ):
            missing_slices.append({"group": group_name, "key": key})

    baseline_cls = sections["baseline"]["classification"]
    candidate_cls = sections["candidate"]["classification"]
    try:
        classification_confusion = {
            "baseline_hard_gate_passed": bool(baseline_cls["hard_gate_passed"]),
            "candidate_hard_gate_passed": bool(candidate_cls["hard_gate_passed"]),
            "candidate_mutation_side_confusions": candidate_cls["mutation_side_confusions"],
            "confusion_matrix_delta": _confusion_matrix_delta(
                baseline_cls["confusion_matrix"], candidate_cls["confusion_matrix"]
            ),
        }
    except (KeyError, TypeError) as exc:
        raise ScorecardCompareError(
            f"scorecard classification section is missing required key {exc}"
        ) from exc

    def _flag(kind: str) -> List[Dict]:
        flagged: List[Dict] = []
        for row in slices["aggregate"]:
            if row[kind]:
                flagged.append({"slice": "aggregate", **row})
        for group_name in ("by_language", "by_slice"):
            for key, rows in slices[group_name].items():
                for row in rows:
                    if row[kind]:
                        flagged.append({"slice": f"{group_name}:{key}", **row})
        for slice_name in ("memory_recall", "classification"):
            for row in slices[slice_name]:
                if row[kind]:
                    flagged.append({"slice": slice_name, **row})
        return flagged

    regressions = _flag("regression")
    improvements = _flag("improved")

    hard_gate_regression = not classification_confusion["candidate_hard_gate_passed"]
    candidate_floor_regression = bool(candidate.get("regression"))

    if hard_gate_regression or candidate_floor_regression or missing_slices or regressions:
        verdict = "regression"
    elif improvements:
        verdict = "improved"
    else:
        verdict = "neutral"

    return {
        "schema_version": COMPARE_SCHEMA_VERSION,
        "tolerance": tolerance,
        "slices": slices,
        "classification_confusion": classification_confusion,
        "candidate_gate": {
            "regression": candidate_floor_regression,
            "failures": candidate.get("failures", []),
        },
        "slice_coverage": {
            "by_language_only_in_baseline": sorted(
                set(sections["baseline"]["by_language"])
                - set(sections["candidate"]["by_language"])
            ),
            "by_language_only_in_candidate": sorted(
                set(sections["candidate"]["by_language"])
                - set(sections["baseline"]["by_language"])
            ),
            "by_slice_only_in_baseline": sorted(
                set(sections["baseline"]["by_slice"]) - set(sections["candidate"]["by_slice"])
            ),
            "by_slice_only_in_candidate": sorted(
                set(sections["candidate"]["by_slice"]) - set(sections["baseline"]["by_slice"])
            ),
        },
        "missing_slices": missing_slices,
        "regressions": regressions,
        "improvements": improvements,
        "verdict": verdict,
    }


def compare_scorecard_files(
    baseline_path: Path,
    candidate_path: Path,
    *,
    tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
) -> Dict:
    """File-level convenience seam used by ``python -m app.eval.run compare``."""
    comparison = compare_scorecards(
        load_scorecard(baseline_path),
        load_scorecard(candidate_path),
        tolerance=tolerance,
    )
    comparison["baseline_path"] = str(baseline_path)
    comparison["candidate_path"] = str(candidate_path)
    return comparison


def _format_row(row: Dict) -> str:
    delta_pct = row["delta_pct"]
    pct = f"{delta_pct:+.1%}" if delta_pct is not None else "n/a"
    flag = ""
    if row["regression"]:
        flag = " ** REGRESSION **"
    elif row["improved"]:
        flag = " (improved)"
    return (
        f"{row['metric']}: {row['baseline']:.4f} -> {row['candidate']:.4f} ({pct}){flag}"
    )


def render_compare_summary(comparison: Dict) -> str:
    """Human-readable, deterministic compare report."""
    lines = ["Scorecard compare — baseline vs candidate", "=" * 60]
    if "baseline_path" in comparison:
        lines.append(f"baseline:  {comparison['baseline_path']}")
        lines.append(f"candidate: {comparison['candidate_path']}")
    lines.append(f"relative tolerance = {comparison['tolerance']:.2%}")
    lines.append("")

    slices = comparison["slices"]
    lines.append("Aggregate:")
    for row in slices["aggregate"]:
        lines.append(f"  {_format_row(row)}")
    lines.append("")
    lines.append("Per language:")
    for lang, rows in slices["by_language"].items():
        for row in rows:
            lines.append(f"  {lang}: {_format_row(row)}")
    lines.append("")
    lines.append("Per slice (route_intent):")
    for name, rows in slices["by_slice"].items():
        for row in rows:
            lines.append(f"  {name}: {_format_row(row)}")
    lines.append("")
    lines.append("Memory-recall slice:")
    for row in slices["memory_recall"]:
        lines.append(f"  {_format_row(row)}")
    lines.append("")
    lines.append("Classification slice:")
    for row in slices["classification"]:
        lines.append(f"  {_format_row(row)}")

    confusion = comparison["classification_confusion"]
    lines.append(
        "  hard gate: baseline="
        f"{'pass' if confusion['baseline_hard_gate_passed'] else 'FAIL'} "
        f"candidate={'pass' if confusion['candidate_hard_gate_passed'] else 'FAIL'}"
    )
    if confusion["candidate_mutation_side_confusions"]:
        lines.append("  HARD GATE VIOLATIONS in candidate (blocking):")
        for item in confusion["candidate_mutation_side_confusions"]:
            lines.append(
                f"    - {item['case_id']}: expected {item['expected_intent']} "
                f"-> predicted {item['predicted_intent']}"
            )
    if confusion["confusion_matrix_delta"]:
        lines.append("  Confusion-matrix delta (candidate - baseline, non-zero cells):")
        for expected, row in confusion["confusion_matrix_delta"].items():
            cells = " ".join(f"{predicted}={count:+d}" for predicted, count in row.items())
            lines.append(f"    {expected}: {cells}")
    else:
        lines.append("  Confusion-matrix delta: none.")

    if comparison["missing_slices"]:
        lines.append("")
        lines.append("Slices present in baseline but MISSING in candidate (blocking):")
        for item in comparison["missing_slices"]:
            lines.append(f"  - {item['group']}:{item['key']}")

    coverage = comparison["slice_coverage"]
    candidate_only = [
        f"by_language:{key}" for key in coverage["by_language_only_in_candidate"]
    ] + [f"by_slice:{key}" for key in coverage["by_slice_only_in_candidate"]]
    if candidate_only:
        lines.append("")
        lines.append(
            "Slices only in candidate (reported, non-blocking): " + ", ".join(candidate_only)
        )

    if comparison["candidate_gate"]["regression"]:
        lines.append("")
        lines.append("Candidate scorecard failed its own configured floors:")
        for failure in comparison["candidate_gate"]["failures"]:
            lines.append(
                f"  - {failure['scope']}: {failure['metric']}={failure['value']:.4f} "
                f"< required {failure['threshold']:.4f}"
            )

    lines.append("")
    lines.append(f"VERDICT: {comparison['verdict']}")
    return "\n".join(lines)


__all__ = [
    "COMPARE_SCHEMA_VERSION",
    "DEFAULT_RELATIVE_TOLERANCE",
    "SCORECARD_SCHEMA_VERSION",
    "ScorecardCompareError",
    "compare_scorecard_files",
    "compare_scorecards",
    "load_scorecard",
    "render_compare_summary",
]
