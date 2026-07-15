"""Baseline-vs-candidate scorecard compare (KERNEL-14, #2776).

Pure, deterministic comparison over two already-produced ``eval_scorecard.v1``
files (written by ``app.eval.run``): per-slice deltas (aggregate, per-language,
per-route-intent, memory-recall, classification incl. per-class metrics and
the KERNEL-13 confusion slice) plus a single ``regression`` / ``improved`` /
``neutral`` verdict.

No live LLM calls, no timestamps, no RNG — the same scorecard pair always
produces byte-identical output. Delta/regression math is shared with
``app.eval.benchmark`` (``compute_metric_delta``), not re-implemented.

Input hardening (one mechanism, all sections): the *comparison surface spec*
(``FLAT_BUCKET_SPEC`` / ``KEYED_GROUP_SPEC`` / ``CLASSIFICATION_METRIC_SPEC``)
is the single source of truth for every leaf this module reads. The
validation walker (``_validated_view``) and the comparison/renderer iterate
that same spec — there is no parallel hand-list to drift. On load, every
numeric leaf (including confusion-matrix cells and ``failures`` entries) is
checked; anything structurally missing, non-numeric, or non-finite (NaN/±inf)
raises :class:`ScorecardCompareError` naming the offending path. The CLI maps
that to exit code 2, so malformed input is never conflated with a genuine
``regression`` verdict (exit 1). The comparison and the summary renderer only
ever consume the validated view, never the raw input.

Verdict semantics:

- ``regression`` — any of:
  1. the candidate trips either the KERNEL-13 mutation-side hard gate or the
     provisional-memory authority hard gate
     (``classification.hard_gate_passed`` is false) — blocking, never
     tolerance-relative;
  2. the candidate scorecard failed its own configured floors
     (``regression: true`` — floors come from ``config/eval_thresholds.yaml``
     at scorecard build time, which is how compare consumes them);
  3. any compared metric worsened relative to baseline by more than the
     relative tolerance (default 5 %, same as ``BenchmarkSuite.compare``);
  4. any keyed slice present in the baseline is MISSING in the candidate —
     per-language, per-route-intent, or per-class alike. A disappeared slice
     is the strongest possible regression; the comparison surface must never
     silently shrink. Keys only in the candidate are reported
     (``slice_coverage``) but do not block.
- ``improved`` — no regression and at least one metric improved beyond the
  tolerance.
- ``neutral`` — everything within tolerance.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, List, Tuple

from app.eval.benchmark import compute_metric_delta

SCORECARD_SCHEMA_VERSION = "eval_scorecard.v1"
COMPARE_SCHEMA_VERSION = "eval_scorecard_compare.v1"

# Same default relative-regression tolerance as BenchmarkSuite.compare().
DEFAULT_RELATIVE_TOLERANCE = 0.05

# ── Comparison surface spec ─────────────────────────────────────────────
# Single source of truth for every numeric leaf this module touches. The
# validation walker AND the comparison iterate these specs; adding a section
# here automatically adds it to validation, comparison, missing-slice
# detection, coverage reporting, and the renderer inputs.

# Retrieval-slice metrics; all higher-is-better.
RETRIEVAL_METRICS = ("precision@k", "ndcg@k")

# Per-class classification metrics compared; all higher-is-better.
PER_CLASS_METRICS = ("precision", "recall")

# Flat (single-bucket) sections: (name, path-in-scorecard, required metrics).
FLAT_BUCKET_SPEC: Tuple[Tuple[str, Tuple[str, ...], Tuple[str, ...]], ...] = (
    ("aggregate", ("aggregate",), RETRIEVAL_METRICS),
    ("memory_recall", ("memory_recall",), RETRIEVAL_METRICS),
)

# Keyed groups (dict of buckets): (name, path-in-scorecard, required metrics).
# A key present in baseline but missing in candidate is a blocking regression
# for EVERY group listed here.
KEYED_GROUP_SPEC: Tuple[Tuple[str, Tuple[str, ...], Tuple[str, ...]], ...] = (
    ("by_language", ("by_language",), RETRIEVAL_METRICS),
    ("by_slice", ("by_slice",), RETRIEVAL_METRICS),
    ("per_class", ("classification", "per_class"), PER_CLASS_METRICS),
)

# Scalar classification read-side metrics: (name, path-in-scorecard).
CLASSIFICATION_METRIC_SPEC: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("macro_precision", ("classification", "macro_precision")),
    ("macro_recall", ("classification", "macro_recall")),
    ("pass_rate", ("classification", "pass_rate")),
    ("answer_rate", ("classification", "safe_fail", "answer_rate")),
    ("unknown_safe_fail_rate", ("classification", "unknown", "safe_fail_rate")),
)

CLASSIFICATION_METRICS = tuple(name for name, _ in CLASSIFICATION_METRIC_SPEC)

# Keys every mutation-side confusion entry must carry (they are rendered).
CONFUSION_ENTRY_KEYS = ("case_id", "expected_intent", "predicted_intent")

# Keys every threshold-failure entry must carry (they are rendered); the
# numeric ones are finiteness-checked because the renderer formats them.
FAILURE_ENTRY_KEYS = ("scope", "metric", "value", "threshold")
FAILURE_ENTRY_NUMERIC_KEYS = ("value", "threshold")
PROVISIONAL_BOUNDARY_SCHEMA_VERSION = "provisional_memory_boundary.v1"
PROVISIONAL_FAILURE_ENTRY_KEYS = ("case_id", "reason")


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
    schema = data.get("schema_version") if isinstance(data, dict) else None
    if schema != SCORECARD_SCHEMA_VERSION:
        raise ScorecardCompareError(
            f"unsupported scorecard schema_version {schema!r} in {path} "
            f"(expected {SCORECARD_SCHEMA_VERSION!r})"
        )
    return data


# ── Validation walker ───────────────────────────────────────────────────


def _resolve(container: object, label: str, path: Tuple[str, ...]) -> object:
    """Resolve a nested path, failing loud with the dotted path on any miss."""
    current = container
    walked: List[str] = []
    for part in path:
        if not isinstance(current, dict) or part not in current:
            dotted = ".".join([label, *walked, part])
            raise ScorecardCompareError(
                f"scorecard is missing required section or key at {dotted}"
            )
        walked.append(part)
        current = current[part]
    return current


def _resolve_dict(container: object, label: str, path: Tuple[str, ...]) -> Dict:
    value = _resolve(container, label, path)
    if not isinstance(value, dict):
        dotted = ".".join([label, *path])
        raise ScorecardCompareError(f"scorecard section at {dotted} is not an object")
    return value


def _require_finite(value: object, path: str) -> float:
    """Reject non-numeric and non-finite (NaN/±inf) values, naming the path."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScorecardCompareError(f"non-numeric metric value at {path}: {value!r}")
    if not math.isfinite(value):
        raise ScorecardCompareError(f"non-finite metric value at {path}: {value!r}")
    return float(value)


def _require_bool(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise ScorecardCompareError(f"non-boolean gate value at {path}: {value!r}")
    return value


def _validated_bucket(
    bucket: object, path: str, metrics: Tuple[str, ...]
) -> Dict[str, float]:
    """Validate one metric bucket: every spec'd metric present and finite."""
    if not isinstance(bucket, dict):
        raise ScorecardCompareError(f"scorecard bucket at {path} is not an object")
    validated: Dict[str, float] = {}
    for metric in metrics:
        if metric not in bucket:
            raise ScorecardCompareError(
                f"scorecard is missing required section or key at {path}.{metric}"
            )
        validated[metric] = _require_finite(bucket[metric], f"{path}.{metric}")
    return validated


def _validated_view(scorecard: Dict, label: str) -> Dict:
    """Walk EVERY leaf the comparison and renderer will touch, spec-driven.

    Returns a fully validated view; downstream code consumes only this view,
    never the raw input. Any structurally missing, non-numeric, or non-finite
    leaf raises :class:`ScorecardCompareError` naming the dotted path.
    """
    view: Dict = {"flat": {}, "keyed": {}}

    for name, path, metrics in FLAT_BUCKET_SPEC:
        dotted = ".".join([label, *path])
        view["flat"][name] = _validated_bucket(
            _resolve_dict(scorecard, label, path), dotted, metrics
        )

    for name, path, metrics in KEYED_GROUP_SPEC:
        group = _resolve_dict(scorecard, label, path)
        dotted = ".".join([label, *path])
        view["keyed"][name] = {
            key: _validated_bucket(group[key], f"{dotted}.{key}", metrics)
            for key in sorted(group)
        }

    view["classification_metrics"] = {
        name: _require_finite(_resolve(scorecard, label, path), ".".join([label, *path]))
        for name, path in CLASSIFICATION_METRIC_SPEC
    }

    matrix = _resolve_dict(scorecard, label, ("classification", "confusion_matrix"))
    matrix_path = f"{label}.classification.confusion_matrix"
    validated_matrix: Dict[str, Dict[str, int]] = {}
    for expected in sorted(matrix):
        row = matrix[expected]
        if not isinstance(row, dict):
            raise ScorecardCompareError(
                f"scorecard bucket at {matrix_path}.{expected} is not an object"
            )
        validated_matrix[expected] = {
            predicted: int(
                _require_finite(row[predicted], f"{matrix_path}.{expected}.{predicted}")
            )
            for predicted in sorted(row)
        }
    view["confusion_matrix"] = validated_matrix

    view["hard_gate_passed"] = _require_bool(
        _resolve(scorecard, label, ("classification", "hard_gate_passed")),
        f"{label}.classification.hard_gate_passed",
    )

    confusions = _resolve(scorecard, label, ("classification", "mutation_side_confusions"))
    confusions_path = f"{label}.classification.mutation_side_confusions"
    if not isinstance(confusions, list):
        raise ScorecardCompareError(f"scorecard section at {confusions_path} is not a list")
    for index, entry in enumerate(confusions):
        if not isinstance(entry, dict):
            raise ScorecardCompareError(
                f"malformed entry at {confusions_path}[{index}]: not an object"
            )
        for key in CONFUSION_ENTRY_KEYS:
            if key not in entry:
                raise ScorecardCompareError(
                    f"malformed entry at {confusions_path}[{index}]: missing {key!r}"
                )
    view["mutation_side_confusions"] = confusions

    provisional = _resolve_dict(scorecard, label, ("provisional_memory_boundary",))
    provisional_path = f"{label}.provisional_memory_boundary"
    if provisional.get("schema_version") != PROVISIONAL_BOUNDARY_SCHEMA_VERSION:
        raise ScorecardCompareError(
            f"unsupported provisional-memory boundary schema_version "
            f"{provisional.get('schema_version')!r} at {provisional_path}.schema_version"
        )
    n_cases = _require_finite(provisional.get("n_cases"), f"{provisional_path}.n_cases")
    if not n_cases.is_integer() or n_cases <= 0:
        raise ScorecardCompareError(
            f"provisional-memory boundary case count must be a positive integer at "
            f"{provisional_path}.n_cases"
        )
    languages = provisional.get("languages")
    if not isinstance(languages, list) or not all(
        isinstance(language, str) for language in languages
    ):
        raise ScorecardCompareError(
            f"scorecard section at {provisional_path}.languages is not a string list"
        )
    if not {"en", "sv"} <= set(languages):
        raise ScorecardCompareError(
            f"scorecard is missing required bilingual coverage at "
            f"{provisional_path}.languages"
        )
    provisional_failures = provisional.get("failures")
    if not isinstance(provisional_failures, list):
        raise ScorecardCompareError(
            f"scorecard section at {provisional_path}.failures is not a list"
        )
    for index, entry in enumerate(provisional_failures):
        if not isinstance(entry, dict):
            raise ScorecardCompareError(
                f"malformed entry at {provisional_path}.failures[{index}]: not an object"
            )
        for key in PROVISIONAL_FAILURE_ENTRY_KEYS:
            if not isinstance(entry.get(key), str) or not entry[key]:
                raise ScorecardCompareError(
                    f"malformed entry at {provisional_path}.failures[{index}]: "
                    f"missing non-empty {key!r}"
                )
    provisional_hard_gate_passed = _require_bool(
        provisional.get("hard_gate_passed"),
        f"{provisional_path}.hard_gate_passed",
    )
    if provisional_hard_gate_passed != (not provisional_failures):
        raise ScorecardCompareError(
            f"inconsistent hard-gate state and failures at {provisional_path}"
        )
    view["provisional_memory_boundary"] = {
        "hard_gate_passed": provisional_hard_gate_passed,
        "n_cases": int(n_cases),
        "languages": sorted(set(languages)),
        "failures": provisional_failures,
    }

    view["floor_regression"] = bool(scorecard.get("regression"))
    failures = scorecard.get("failures", [])
    failures_path = f"{label}.failures"
    if not isinstance(failures, list):
        raise ScorecardCompareError(f"scorecard section at {failures_path} is not a list")
    for index, entry in enumerate(failures):
        if not isinstance(entry, dict):
            raise ScorecardCompareError(
                f"malformed entry at {failures_path}[{index}]: not an object"
            )
        for key in FAILURE_ENTRY_KEYS:
            if key not in entry:
                raise ScorecardCompareError(
                    f"malformed entry at {failures_path}[{index}]: missing {key!r}"
                )
        for key in FAILURE_ENTRY_NUMERIC_KEYS:
            _require_finite(entry[key], f"{failures_path}[{index}].{key}")
    view["failures"] = failures

    return view


# ── Delta rows ──────────────────────────────────────────────────────────


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
    baseline_metrics: Dict[str, float],
    candidate_metrics: Dict[str, float],
    metric_names: Tuple[str, ...],
    tolerance: float,
) -> List[Dict]:
    # Inputs are validated views: every spec'd metric is present and finite.
    return [
        _metric_row(metric, baseline_metrics[metric], candidate_metrics[metric], tolerance)
        for metric in metric_names
    ]


def _confusion_matrix_delta(
    baseline: Dict[str, Dict[str, int]], candidate: Dict[str, Dict[str, int]]
) -> Dict[str, Dict[str, int]]:
    """Per-cell candidate-minus-baseline confusion-matrix delta (sorted keys)."""
    delta: Dict[str, Dict[str, int]] = {}
    for expected in sorted(set(baseline) | set(candidate)):
        baseline_row = baseline.get(expected, {})
        candidate_row = candidate.get(expected, {})
        row: Dict[str, int] = {}
        for predicted in sorted(set(baseline_row) | set(candidate_row)):
            cell = candidate_row.get(predicted, 0) - baseline_row.get(predicted, 0)
            if cell:
                row[predicted] = cell
        if row:
            delta[expected] = row
    return delta


# ── Comparison ──────────────────────────────────────────────────────────


def compare_scorecards(
    baseline: Dict,
    candidate: Dict,
    *,
    tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
) -> Dict:
    """Compare two ``eval_scorecard.v1`` dicts into a deterministic report."""
    views: Dict[str, Dict] = {}
    for label, scorecard in (("baseline", baseline), ("candidate", candidate)):
        if not isinstance(scorecard, dict) or (
            scorecard.get("schema_version") != SCORECARD_SCHEMA_VERSION
        ):
            schema = scorecard.get("schema_version") if isinstance(scorecard, dict) else None
            raise ScorecardCompareError(
                f"{label} scorecard has unsupported schema_version "
                f"{schema!r} (expected {SCORECARD_SCHEMA_VERSION!r})"
            )
        # Validation walker: everything below consumes these views only,
        # never the raw input.
        views[label] = _validated_view(scorecard, label)

    try:
        return _compare_validated(views["baseline"], views["candidate"], tolerance)
    except ScorecardCompareError:
        raise
    except (KeyError, TypeError, ValueError) as exc:  # pragma: no cover — backstop
        # The walker should make this unreachable; keep any residual
        # malformed-input crash on the documented exit-2 path regardless.
        raise ScorecardCompareError(f"malformed scorecard input: {exc!r}") from exc


def _compare_validated(baseline: Dict, candidate: Dict, tolerance: float) -> Dict:
    slices: Dict = {}
    for name, _, metrics in FLAT_BUCKET_SPEC:
        slices[name] = _compare_bucket(
            baseline["flat"][name], candidate["flat"][name], metrics, tolerance
        )
    for name, _, metrics in KEYED_GROUP_SPEC:
        common = sorted(set(baseline["keyed"][name]) & set(candidate["keyed"][name]))
        slices[name] = {
            key: _compare_bucket(
                baseline["keyed"][name][key],
                candidate["keyed"][name][key],
                metrics,
                tolerance,
            )
            for key in common
        }
    slices["classification"] = _compare_bucket(
        baseline["classification_metrics"],
        candidate["classification_metrics"],
        CLASSIFICATION_METRICS,
        tolerance,
    )

    # A key present in the baseline but missing in the candidate is the
    # strongest possible regression for every keyed group in the spec: the
    # comparison surface silently shrank. Blocking; candidate-only keys are
    # reported via slice_coverage only.
    missing_slices: List[Dict] = []
    slice_coverage: Dict[str, List[str]] = {}
    for name, _, _ in KEYED_GROUP_SPEC:
        baseline_keys = set(baseline["keyed"][name])
        candidate_keys = set(candidate["keyed"][name])
        only_in_baseline = sorted(baseline_keys - candidate_keys)
        for key in only_in_baseline:
            missing_slices.append({"group": name, "key": key})
        slice_coverage[f"{name}_only_in_baseline"] = only_in_baseline
        slice_coverage[f"{name}_only_in_candidate"] = sorted(candidate_keys - baseline_keys)

    classification_confusion = {
        "baseline_hard_gate_passed": baseline["hard_gate_passed"],
        "candidate_hard_gate_passed": candidate["hard_gate_passed"],
        "candidate_mutation_side_confusions": candidate["mutation_side_confusions"],
        "confusion_matrix_delta": _confusion_matrix_delta(
            baseline["confusion_matrix"], candidate["confusion_matrix"]
        ),
    }
    provisional_memory_boundary = {
        "baseline_hard_gate_passed": baseline["provisional_memory_boundary"][
            "hard_gate_passed"
        ],
        "candidate_hard_gate_passed": candidate["provisional_memory_boundary"][
            "hard_gate_passed"
        ],
        "candidate_failures": candidate["provisional_memory_boundary"]["failures"],
        "candidate_n_cases": candidate["provisional_memory_boundary"]["n_cases"],
        "candidate_languages": candidate["provisional_memory_boundary"]["languages"],
    }

    def _flag(kind: str) -> List[Dict]:
        flagged: List[Dict] = []
        for name, _, _ in FLAT_BUCKET_SPEC:
            for row in slices[name]:
                if row[kind]:
                    flagged.append({"slice": name, **row})
        for name, _, _ in KEYED_GROUP_SPEC:
            for key, rows in slices[name].items():
                for row in rows:
                    if row[kind]:
                        flagged.append({"slice": f"{name}:{key}", **row})
        for row in slices["classification"]:
            if row[kind]:
                flagged.append({"slice": "classification", **row})
        return flagged

    regressions = _flag("regression")
    improvements = _flag("improved")

    hard_gate_regression = (
        not classification_confusion["candidate_hard_gate_passed"]
        or not provisional_memory_boundary["candidate_hard_gate_passed"]
    )
    candidate_floor_regression = candidate["floor_regression"]

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
        "provisional_memory_boundary": provisional_memory_boundary,
        "candidate_gate": {
            "regression": candidate_floor_regression,
            "failures": candidate["failures"],
        },
        "slice_coverage": slice_coverage,
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


# ── Rendering ───────────────────────────────────────────────────────────


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
    """Human-readable, deterministic compare report.

    Consumes only the validated comparison structure produced by
    :func:`compare_scorecards`: every leaf rendered here (metric rows,
    confusion entries, failure entries) was checked by the validation walker
    on load, so rendering cannot crash after a successful compare.
    """
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
    lines.append("  Per class:")
    for name, rows in slices["per_class"].items():
        for row in rows:
            lines.append(f"    {name}: {_format_row(row)}")

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

    boundary = comparison["provisional_memory_boundary"]
    lines.append("")
    lines.append("Provisional-memory authority hard gate:")
    lines.append(
        "  baseline="
        f"{'pass' if boundary['baseline_hard_gate_passed'] else 'FAIL'} "
        f"candidate={'pass' if boundary['candidate_hard_gate_passed'] else 'FAIL'} "
        f"(n={boundary['candidate_n_cases']}; "
        f"languages={','.join(boundary['candidate_languages'])})"
    )
    if boundary["candidate_failures"]:
        lines.append("  HARD GATE VIOLATIONS in candidate (blocking):")
        for failure in boundary["candidate_failures"]:
            lines.append(f"    - {failure['case_id']}: {failure['reason']}")

    if comparison["missing_slices"]:
        lines.append("")
        lines.append("Slices present in baseline but MISSING in candidate (blocking):")
        for item in comparison["missing_slices"]:
            lines.append(f"  - {item['group']}:{item['key']}")

    coverage = comparison["slice_coverage"]
    candidate_only = [
        f"{name}:{key}"
        for name, _, _ in KEYED_GROUP_SPEC
        for key in coverage[f"{name}_only_in_candidate"]
    ]
    if candidate_only:
        lines.append("")
        lines.append(
            "Slices only in candidate (reported, non-blocking): " + ", ".join(candidate_only)
        )

    if comparison["candidate_gate"]["regression"]:
        lines.append("")
        lines.append("Candidate scorecard failed its own configured floors:")
        for failure in comparison["candidate_gate"]["failures"]:
            if failure.get("kind") == "categorical":
                lines.append(
                    f"  - {failure['scope']}: categorical violation: "
                    f"{failure['metric']}"
                )
            else:
                lines.append(
                    f"  - {failure['scope']}: {failure['metric']}="
                    f"{failure['value']:.4f} < required {failure['threshold']:.4f}"
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
