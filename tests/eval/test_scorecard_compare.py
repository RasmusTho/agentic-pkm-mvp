"""Tests for the baseline-vs-candidate scorecard compare seam (KERNEL-14, #2776).

Covers `python -m app.eval.run compare --baseline <f> --candidate <f>`:
per-slice deltas (aggregate, per-language, per-route-intent, memory-recall,
classification confusion slice) and the deterministic
regression/improved/neutral verdict. Pure fixture comparison — no live LLM,
no golden-set re-run.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.eval import run as eval_run
from app.eval.compare import (
    ScorecardCompareError,
    compare_scorecard_files,
    compare_scorecards,
    load_scorecard,
    render_compare_summary,
)

pytestmark = pytest.mark.not_pg

FIXTURES = Path(__file__).parent / "fixtures"
BASELINE_PATH = FIXTURES / "scorecard_baseline.json"
CANDIDATE_PATH = FIXTURES / "scorecard_candidate.json"


def _rows_by_metric(rows: list[dict]) -> dict[str, dict]:
    return {row["metric"]: row for row in rows}


def _reconcile_classification_metrics(scorecard: dict) -> None:
    classification = scorecard["classification"]
    matrix = classification["confusion_matrix"]
    classes = ("co_authoring", "governance_bearing", "exploratory")
    precision: list[float] = []
    recall: list[float] = []
    for class_name in classes:
        support = sum(matrix[class_name].values())
        predicted = sum(matrix[expected][class_name] for expected in matrix)
        answered = support - matrix[class_name]["unknown"]
        true_positive = matrix[class_name][class_name]
        class_precision = true_positive / predicted if predicted else 0.0
        class_recall = true_positive / answered if answered else 0.0
        classification["per_class"][class_name] = {
            "precision": class_precision,
            "recall": class_recall,
            "support": support,
            "predicted": predicted,
        }
        precision.append(class_precision)
        recall.append(class_recall)
    classification["macro_precision"] = sum(precision) / len(precision)
    classification["macro_recall"] = sum(recall) / len(recall)
    unknown_expected = sum(matrix["unknown"].values())
    unknown_hits = matrix["unknown"]["unknown"]
    classification["unknown"] = {
        "expected": unknown_expected,
        "safe_fail_hits": unknown_hits,
        "read_side_landings": matrix["unknown"]["exploratory"],
        "safe_fail_rate": unknown_hits / unknown_expected if unknown_expected else 0.0,
    }
    safe_fail_count = sum(matrix[class_name]["unknown"] for class_name in classes)
    answerable = classification["n_cases"] - unknown_expected
    classification["safe_fail"] = {
        "count": safe_fail_count,
        "answer_rate": (
            (answerable - safe_fail_count) / answerable if answerable else 0.0
        ),
    }


# ── Per-slice deltas ─────────────────────────────────────────────────────


def test_per_slice_deltas() -> None:
    comparison = compare_scorecard_files(BASELINE_PATH, CANDIDATE_PATH)
    slices = comparison["slices"]

    # Aggregate slice.
    aggregate = _rows_by_metric(slices["aggregate"])
    assert aggregate["precision@k"]["delta"] == pytest.approx(0.02)
    assert aggregate["precision@k"]["delta_pct"] == pytest.approx(0.10)
    assert aggregate["precision@k"]["improved"] is True
    assert aggregate["precision@k"]["regression"] is False
    assert aggregate["ndcg@k"]["delta"] == pytest.approx(0.0)

    # Per-language slice (en, sv).
    assert set(slices["by_language"]) == {"en", "sv"}
    sv = _rows_by_metric(slices["by_language"]["sv"])
    assert sv["precision@k"]["delta"] == pytest.approx(0.04)
    assert sv["precision@k"]["improved"] is True
    en = _rows_by_metric(slices["by_language"]["en"])
    assert en["ndcg@k"]["delta"] == pytest.approx(0.01)
    assert en["ndcg@k"]["improved"] is False  # within tolerance

    # Per-route-intent slice.
    assert set(slices["by_slice"]) == {
        "exact_lexical",
        "hybrid_semantic",
        "recall_into_ask",
        "low_trust_citation",
    }
    hybrid = _rows_by_metric(slices["by_slice"]["hybrid_semantic"])
    assert hybrid["ndcg@k"]["delta"] == pytest.approx(-0.03)
    assert hybrid["ndcg@k"]["regression"] is False  # -3.5 % is within 5 % tolerance

    # Memory-recall slice.
    memory = _rows_by_metric(slices["memory_recall"])
    assert memory["precision@k"]["delta"] == pytest.approx(0.02)
    assert memory["precision@k"]["improved"] is True

    # Classification slice (read-side metrics).
    classification = _rows_by_metric(slices["classification"])
    assert set(classification) == {
        "macro_precision",
        "macro_recall",
        "pass_rate",
        "answer_rate",
        "unknown_safe_fail_rate",
    }
    assert classification["unknown_safe_fail_rate"]["delta"] == pytest.approx(0.125)
    assert classification["unknown_safe_fail_rate"]["improved"] is True

    # Per-class slice (keyed group, same mechanism as by_language/by_slice).
    assert set(slices["per_class"]) == {"co_authoring", "governance_bearing", "exploratory"}
    exploratory = _rows_by_metric(slices["per_class"]["exploratory"])
    assert exploratory["precision"]["delta"] == pytest.approx(
        0.9615384615384616 - 0.9230769230769231
    )
    assert exploratory["precision"]["regression"] is False

    # Classification confusion slice (KERNEL-13): hard gate + matrix delta.
    confusion = comparison["classification_confusion"]
    assert confusion["baseline_hard_gate_passed"] is True
    assert confusion["candidate_hard_gate_passed"] is True
    assert confusion["candidate_mutation_side_confusions"] == []
    assert confusion["confusion_matrix_delta"] == {
        "exploratory": {"exploratory": 1, "unknown": -1},
        "unknown": {"exploratory": -1, "unknown": 1},
    }


# ── Verdict determinism ──────────────────────────────────────────────────


def test_verdict_deterministic(capsys: pytest.CaptureFixture[str]) -> None:
    # Library seam: same inputs -> byte-identical serialized output.
    first = compare_scorecard_files(BASELINE_PATH, CANDIDATE_PATH)
    second = compare_scorecard_files(BASELINE_PATH, CANDIDATE_PATH)
    assert first["verdict"] == "improved"
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    # CLI seam: same argv -> identical stdout and exit code, twice.
    argv = [
        "compare",
        "--baseline",
        str(BASELINE_PATH),
        "--candidate",
        str(CANDIDATE_PATH),
    ]
    code_first = eval_run.main(argv)
    out_first = capsys.readouterr().out
    code_second = eval_run.main(argv)
    out_second = capsys.readouterr().out

    assert code_first == code_second == 0
    assert out_first == out_second
    assert "VERDICT: improved" in out_first


# ── Verdict semantics ────────────────────────────────────────────────────


def test_verdict_neutral_on_identical_scorecards() -> None:
    baseline = load_scorecard(BASELINE_PATH)
    comparison = compare_scorecards(baseline, copy.deepcopy(baseline))
    assert comparison["verdict"] == "neutral"
    assert comparison["regressions"] == []
    assert comparison["improvements"] == []


def test_verdict_regression_on_worsened_metric() -> None:
    baseline = load_scorecard(BASELINE_PATH)
    candidate = copy.deepcopy(baseline)
    # Worsen aggregate precision@k by 25 % — beyond the 5 % tolerance.
    candidate["aggregate"]["precision@k"] = 0.15
    comparison = compare_scorecards(baseline, candidate)
    assert comparison["verdict"] == "regression"
    assert any(
        row["slice"] == "aggregate" and row["metric"] == "precision@k"
        for row in comparison["regressions"]
    )


def test_verdict_regression_on_mutation_side_hard_gate() -> None:
    baseline = load_scorecard(BASELINE_PATH)
    candidate = load_scorecard(CANDIDATE_PATH)
    # The KERNEL-13 hard gate is blocking regardless of metric movement.
    candidate["classification"]["hard_gate_passed"] = False
    candidate["classification"]["mutation_side_confusions"] = [
        {
            "case_id": "adv-sv-01",
            "expected_intent": "exploratory",
            "predicted_intent": "governance_bearing",
        }
    ]
    candidate["classification"]["confusion_matrix"]["exploratory"][
        "exploratory"
    ] -= 1
    candidate["classification"]["confusion_matrix"]["exploratory"][
        "governance_bearing"
    ] += 1
    _reconcile_classification_metrics(candidate)
    candidate["regression"] = True
    candidate["failures"] = [
        {
            "scope": "classification:hard_gate",
            "metric": "mutation_side_confusion:adv-sv-01->governance_bearing",
            "value": 1.0,
            "threshold": 0.0,
            "kind": "categorical",
        }
    ]
    comparison = compare_scorecards(baseline, candidate)
    assert comparison["verdict"] == "regression"
    assert comparison["classification_confusion"]["candidate_hard_gate_passed"] is False


def test_rejects_scorecard_without_provisional_memory_boundary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = load_scorecard(BASELINE_PATH)
    candidate = load_scorecard(CANDIDATE_PATH)
    del candidate["provisional_memory_boundary"]

    with pytest.raises(
        ScorecardCompareError,
        match=r"candidate\.provisional_memory_boundary",
    ):
        compare_scorecards(baseline, candidate)

    candidate_path = tmp_path / "candidate_without_provisional_boundary.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    assert eval_run.main(
        [
            "compare",
            "--baseline",
            str(BASELINE_PATH),
            "--candidate",
            str(candidate_path),
        ]
    ) == 2
    assert "candidate.provisional_memory_boundary" in capsys.readouterr().err


def test_verdict_regression_on_provisional_memory_hard_gate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = load_scorecard(BASELINE_PATH)
    candidate = load_scorecard(CANDIDATE_PATH)
    candidate["provisional_memory_boundary"]["hard_gate_passed"] = False
    candidate["provisional_memory_boundary"]["failures"] = [
        {
            "case_id": "cited-proposal-en",
            "reason": "uncited_proposal_admitted",
        }
    ]
    next(
        case
        for case in candidate["provisional_memory_boundary"]["cases"]
        if case["id"] == "cited-proposal-en"
    )["passed"] = False
    candidate["regression"] = True
    candidate["failures"] = [
        {
            "scope": "provisional_memory:hard_gate",
            "metric": "cited-proposal-en:uncited_proposal_admitted",
            "value": 1.0,
            "threshold": 0.0,
            "kind": "categorical",
        }
    ]

    comparison = compare_scorecards(baseline, candidate)
    summary = render_compare_summary(comparison)

    assert comparison["verdict"] == "regression"
    assert comparison["provisional_memory_boundary"] == {
        "baseline_hard_gate_passed": True,
        "candidate_hard_gate_passed": False,
        "candidate_failures": [
            {
                "case_id": "cited-proposal-en",
                "reason": "uncited_proposal_admitted",
            }
        ],
        "candidate_n_cases": 16,
        "candidate_languages": ["en", "sv"],
    }
    assert "Provisional-memory authority hard gate" in summary
    assert "uncited_proposal_admitted" in summary

    candidate_path = tmp_path / "candidate_provisional_regression.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    assert eval_run.main(
        [
            "compare",
            "--baseline",
            str(BASELINE_PATH),
            "--candidate",
            str(candidate_path),
        ]
    ) == 1
    assert "VERDICT: regression" in capsys.readouterr().out


def test_cli_rejects_classification_gate_confusion_contradiction(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidate = load_scorecard(CANDIDATE_PATH)
    candidate["classification"]["mutation_side_confusions"] = [
        {
            "case_id": "adv-sv-01",
            "expected_intent": "exploratory",
            "predicted_intent": "governance_bearing",
        }
    ]
    candidate["classification"]["confusion_matrix"]["exploratory"][
        "exploratory"
    ] -= 1
    candidate["classification"]["confusion_matrix"]["exploratory"][
        "governance_bearing"
    ] += 1
    _reconcile_classification_metrics(candidate)
    path = tmp_path / "candidate_contradictory_classification_gate.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")

    assert eval_run.main(
        ["compare", "--baseline", str(BASELINE_PATH), "--candidate", str(path)]
    ) == 2
    assert "hard-gate state contradicts" in capsys.readouterr().err


def test_cli_rejects_matrix_mutation_missing_from_confusion_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidate = load_scorecard(CANDIDATE_PATH)
    matrix = candidate["classification"]["confusion_matrix"]["exploratory"]
    matrix["exploratory"] -= 1
    matrix["governance_bearing"] += 1
    _reconcile_classification_metrics(candidate)
    path = tmp_path / "candidate_matrix_mutation_without_evidence.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")

    assert eval_run.main(
        ["compare", "--baseline", str(BASELINE_PATH), "--candidate", str(path)]
    ) == 2
    assert "matrix contradicts mutation confusions" in capsys.readouterr().err


@pytest.mark.parametrize("count", [-1, 1.5])
def test_cli_rejects_invalid_confusion_matrix_count(
    count: float,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidate = load_scorecard(CANDIDATE_PATH)
    candidate["classification"]["confusion_matrix"]["exploratory"][
        "exploratory"
    ] = count
    path = tmp_path / "candidate_invalid_matrix_count.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")

    assert eval_run.main(
        ["compare", "--baseline", str(BASELINE_PATH), "--candidate", str(path)]
    ) == 2
    assert "non-negative integer" in capsys.readouterr().err


def test_cli_rejects_classification_case_count_matrix_mismatch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidate = load_scorecard(CANDIDATE_PATH)
    candidate["classification"]["n_cases"] += 1
    path = tmp_path / "candidate_classification_count_mismatch.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")

    assert eval_run.main(
        ["compare", "--baseline", str(BASELINE_PATH), "--candidate", str(path)]
    ) == 2
    assert "n_cases contradicts confusion matrix" in capsys.readouterr().err


def test_cli_rejects_classification_metrics_that_contradict_matrix(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidate = load_scorecard(CANDIDATE_PATH)
    row = candidate["classification"]["confusion_matrix"]["co_authoring"]
    row["exploratory"] += row["co_authoring"]
    row["co_authoring"] = 0
    path = tmp_path / "candidate_forged_classification_metrics.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")

    assert eval_run.main(
        ["compare", "--baseline", str(BASELINE_PATH), "--candidate", str(path)]
    ) == 2
    assert "contradicts confusion matrix" in capsys.readouterr().err


@pytest.mark.parametrize("gate", ["classification", "provisional"])
def test_cli_rejects_categorical_metric_nested_evidence_mismatch(
    gate: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidate = load_scorecard(CANDIDATE_PATH)
    if gate == "classification":
        candidate["classification"]["hard_gate_passed"] = False
        candidate["classification"]["mutation_side_confusions"] = [
            {
                "case_id": "adv-sv-01",
                "expected_intent": "exploratory",
                "predicted_intent": "governance_bearing",
            }
        ]
        candidate["classification"]["confusion_matrix"]["exploratory"][
            "exploratory"
        ] -= 1
        candidate["classification"]["confusion_matrix"]["exploratory"][
            "governance_bearing"
        ] += 1
        _reconcile_classification_metrics(candidate)
        scope = "classification:hard_gate"
    else:
        boundary = candidate["provisional_memory_boundary"]
        boundary["hard_gate_passed"] = False
        boundary["failures"] = [
            {
                "case_id": "cited-proposal-en",
                "reason": "uncited_proposal_admitted",
            }
        ]
        next(
            case
            for case in boundary["cases"]
            if case["id"] == "cited-proposal-en"
        )["passed"] = False
        scope = "provisional_memory:hard_gate"
    candidate["regression"] = True
    candidate["failures"] = [
        {
            "scope": scope,
            "metric": "totally-wrong-case:totally-wrong-reason",
            "value": 1.0,
            "threshold": 0.0,
            "kind": "categorical",
        }
    ]
    path = tmp_path / f"candidate_{gate}_metric_mismatch.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")

    assert eval_run.main(
        ["compare", "--baseline", str(BASELINE_PATH), "--candidate", str(path)]
    ) == 2
    assert "categorical metrics contradict nested evidence" in capsys.readouterr().err


def test_cli_rejects_duplicate_scorecard_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidate = load_scorecard(CANDIDATE_PATH)
    failure = {
        "scope": "aggregate",
        "metric": "precision_at_k",
        "value": 0.1,
        "threshold": 0.15,
        "kind": "threshold_floor",
    }
    candidate["regression"] = True
    candidate["failures"] = [failure, failure]
    path = tmp_path / "candidate_duplicate_failure.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")

    assert eval_run.main(
        ["compare", "--baseline", str(BASELINE_PATH), "--candidate", str(path)]
    ) == 2
    assert "duplicate scorecard failure" in capsys.readouterr().err


@pytest.mark.parametrize(
    "target,mutation",
    [
        ("baseline", "missing_families"),
        ("candidate", "missing_cases"),
        ("candidate", "count_mismatch"),
        ("candidate", "incomplete_coverage"),
        ("candidate", "unknown_family"),
        ("candidate", "unsafe_write_passed"),
        ("candidate", "failure_case_still_passed"),
    ],
)
def test_cli_rejects_incomplete_provisional_case_evidence(
    target: str,
    mutation: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scorecards = {
        "baseline": load_scorecard(BASELINE_PATH),
        "candidate": load_scorecard(CANDIDATE_PATH),
    }
    boundary = scorecards[target]["provisional_memory_boundary"]
    if mutation == "missing_families":
        del boundary["families"]
    elif mutation == "missing_cases":
        del boundary["cases"]
    elif mutation == "count_mismatch":
        boundary["n_cases"] = 1
    elif mutation == "incomplete_coverage":
        boundary["cases"][0]["family"] = "cited_proposal"
    elif mutation == "unknown_family":
        boundary["families"][1] = "invented_family"
        for case in boundary["cases"]:
            if case["family"] == "benign_read":
                case["family"] = "invented_family"
    elif mutation == "unsafe_write_passed":
        boundary["cases"][0]["may_write"] = True
    else:
        boundary["hard_gate_passed"] = False
        boundary["failures"] = [
            {
                "case_id": "benign-read-en",
                "reason": "write_authority_granted",
            }
        ]

    paths: dict[str, Path] = {}
    for label, scorecard in scorecards.items():
        path = tmp_path / f"{label}.json"
        path.write_text(json.dumps(scorecard), encoding="utf-8")
        paths[label] = path

    assert eval_run.main(
        [
            "compare",
            "--baseline",
            str(paths["baseline"]),
            "--candidate",
            str(paths["candidate"]),
        ]
    ) == 2
    assert "error:" in capsys.readouterr().err


def test_verdict_regression_on_missing_slice() -> None:
    """A slice present in baseline but missing in candidate is blocking.

    Round-1 review repro on PR #2858: deleting 'sv' plus a route slice from
    the candidate previously yielded 'improved' because only the key
    intersection was compared and slice_coverage never fed the verdict.
    """
    baseline = load_scorecard(BASELINE_PATH)
    candidate = load_scorecard(CANDIDATE_PATH)
    del candidate["by_language"]["sv"]
    del candidate["by_slice"]["hybrid_semantic"]

    comparison = compare_scorecards(baseline, candidate)
    assert comparison["verdict"] == "regression"
    assert comparison["missing_slices"] == [
        {"group": "by_language", "key": "sv"},
        {"group": "by_slice", "key": "hybrid_semantic"},
    ]
    summary = render_compare_summary(comparison)
    assert "MISSING in candidate (blocking)" in summary
    assert "by_language:sv" in summary
    assert "by_slice:hybrid_semantic" in summary


def test_candidate_only_slices_report_but_do_not_block() -> None:
    baseline = load_scorecard(BASELINE_PATH)
    candidate = load_scorecard(CANDIDATE_PATH)
    candidate["by_slice"]["new_route_intent"] = {"precision@k": 0.5, "ndcg@k": 0.9, "count": 2}

    comparison = compare_scorecards(baseline, candidate)
    # Fixture pair verdict is 'improved'; a candidate-only slice must not flip it.
    assert comparison["verdict"] == "improved"
    assert comparison["missing_slices"] == []
    assert comparison["slice_coverage"]["by_slice_only_in_candidate"] == ["new_route_intent"]
    assert "Slices only in candidate (reported, non-blocking)" in render_compare_summary(
        comparison
    )


def test_rejects_non_finite_metric_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    candidate = load_scorecard(CANDIDATE_PATH)
    candidate["by_language"]["sv"]["precision@k"] = float("nan")
    nan_path = tmp_path / "candidate_nan.json"
    # json.dumps emits bare NaN (invalid strict JSON) — exactly the hostile
    # input class compare must reject instead of flowing to 'neutral'.
    nan_path.write_text(json.dumps(candidate), encoding="utf-8")

    with pytest.raises(
        ScorecardCompareError, match=r"non-finite .* candidate\.by_language\.sv"
    ):
        compare_scorecard_files(BASELINE_PATH, nan_path)

    code = eval_run.main(
        ["compare", "--baseline", str(BASELINE_PATH), "--candidate", str(nan_path)]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "error:" in captured.err
    assert "non-finite" in captured.err


def test_cli_exit_2_on_truncated_scorecard(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Malformed input is exit 2 with an `error:` message, never a raw
    traceback exit that is indistinguishable from a regression verdict (1)."""
    truncated = load_scorecard(CANDIDATE_PATH)
    del truncated["classification"]
    truncated_path = tmp_path / "truncated.json"
    truncated_path.write_text(json.dumps(truncated), encoding="utf-8")

    with pytest.raises(
        ScorecardCompareError,
        match="missing required section or key at candidate.classification",
    ):
        compare_scorecard_files(BASELINE_PATH, truncated_path)

    code = eval_run.main(
        ["compare", "--baseline", str(BASELINE_PATH), "--candidate", str(truncated_path)]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "error:" in captured.err
    assert "missing required section or key at candidate.classification" in captured.err


def test_rejects_per_class_disappearance_as_malformed_proof() -> None:
    baseline = load_scorecard(BASELINE_PATH)
    candidate = load_scorecard(CANDIDATE_PATH)
    del candidate["classification"]["per_class"]["exploratory"]

    with pytest.raises(ScorecardCompareError, match="invalid per-class keys"):
        compare_scorecards(baseline, candidate)


def test_rejects_nan_confusion_matrix_cell(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Round-2 review: int(...) on raw confusion cells crashed uncaught.

    Non-finite/non-numeric cells must be a ScorecardCompareError naming the
    cell path (CLI exit 2), never a traceback exit 1.
    """
    candidate = load_scorecard(CANDIDATE_PATH)
    candidate["classification"]["confusion_matrix"]["exploratory"]["unknown"] = float("nan")
    nan_path = tmp_path / "candidate_nan_cell.json"
    nan_path.write_text(json.dumps(candidate), encoding="utf-8")

    with pytest.raises(
        ScorecardCompareError,
        match=r"non-finite .* candidate\.classification\.confusion_matrix\.exploratory\.unknown",
    ):
        compare_scorecard_files(BASELINE_PATH, nan_path)

    code = eval_run.main(
        ["compare", "--baseline", str(BASELINE_PATH), "--candidate", str(nan_path)]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "error:" in captured.err

    # Same mechanism for a non-numeric cell (the empirical int('x') crash).
    candidate["classification"]["confusion_matrix"]["exploratory"]["unknown"] = "boom"
    bad_path = tmp_path / "candidate_bad_cell.json"
    bad_path.write_text(json.dumps(candidate), encoding="utf-8")
    code = eval_run.main(
        ["compare", "--baseline", str(BASELINE_PATH), "--candidate", str(bad_path)]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "non-numeric" in captured.err


def test_rejects_malformed_failures_entry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Round-2 review: rendering candidate failures crashed on a missing
    'value' key AFTER a successful compare (exit 1). The walker now rejects
    malformed failures entries on load (exit 2)."""
    candidate = load_scorecard(CANDIDATE_PATH)
    candidate["regression"] = True
    candidate["failures"] = [{"scope": "aggregate", "metric": "precision_at_k"}]
    bad_path = tmp_path / "candidate_bad_failures.json"
    bad_path.write_text(json.dumps(candidate), encoding="utf-8")

    with pytest.raises(
        ScorecardCompareError, match=r"candidate\.failures\[0\]: missing 'value'"
    ):
        compare_scorecard_files(BASELINE_PATH, bad_path)

    code = eval_run.main(
        ["compare", "--baseline", str(BASELINE_PATH), "--candidate", str(bad_path)]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "error:" in captured.err
    assert "missing 'value'" in captured.err


@pytest.mark.parametrize("regression", [0, None, ""])
def test_cli_rejects_non_boolean_regression_flag(
    regression: object,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidate = load_scorecard(CANDIDATE_PATH)
    candidate["regression"] = regression
    path = tmp_path / "candidate_bad_regression_type.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")

    assert eval_run.main(
        ["compare", "--baseline", str(BASELINE_PATH), "--candidate", str(path)]
    ) == 2
    assert "non-boolean gate value at candidate.regression" in capsys.readouterr().err


@pytest.mark.parametrize("kind", [None, "bogus", 1, "__missing__"])
def test_cli_rejects_invalid_failure_kind(
    kind: object,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidate = load_scorecard(CANDIDATE_PATH)
    failure: dict[str, object] = {
        "scope": "aggregate",
        "metric": "precision_at_k",
        "value": 0.1,
        "threshold": 0.15,
        "kind": kind,
    }
    if kind == "__missing__":
        del failure["kind"]
    candidate["regression"] = True
    candidate["failures"] = [failure]
    path = tmp_path / "candidate_bad_failure_kind.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")

    assert eval_run.main(
        ["compare", "--baseline", str(BASELINE_PATH), "--candidate", str(path)]
    ) == 2
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize(
    "scope", ["classification:hard_gate", "provisional_memory:hard_gate"]
)
def test_cli_rejects_threshold_floor_with_hard_gate_scope(
    scope: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidate = load_scorecard(CANDIDATE_PATH)
    candidate["regression"] = True
    candidate["failures"] = [
        {
            "scope": scope,
            "metric": "fake_floor",
            "value": -1.0,
            "threshold": 0.0,
            "kind": "threshold_floor",
        }
    ]
    path = tmp_path / "candidate_hard_gate_as_floor.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")

    assert eval_run.main(
        ["compare", "--baseline", str(BASELINE_PATH), "--candidate", str(path)]
    ) == 2
    assert "hard-gate scope cannot be threshold-relative" in capsys.readouterr().err


@pytest.mark.parametrize(
    "regression,failures",
    [
        (True, []),
        (
            False,
            [
                {
                    "scope": "provisional_memory:hard_gate",
                    "metric": "cited-proposal-en:uncited_proposal_admitted",
                    "value": 1.0,
                    "threshold": 0.0,
                    "kind": "categorical",
                }
            ],
        ),
    ],
)
def test_cli_rejects_regression_failure_contradiction(
    regression: bool,
    failures: list[dict[str, object]],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidate = load_scorecard(CANDIDATE_PATH)
    candidate["regression"] = regression
    candidate["failures"] = failures
    path = tmp_path / "candidate_contradictory_regression.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")

    assert eval_run.main(
        ["compare", "--baseline", str(BASELINE_PATH), "--candidate", str(path)]
    ) == 2
    assert "regression flag contradicts failures" in capsys.readouterr().err


def test_verdict_regression_when_candidate_fails_own_floors() -> None:
    baseline = load_scorecard(BASELINE_PATH)
    candidate = load_scorecard(CANDIDATE_PATH)
    candidate["aggregate"]["precision@k"] = 0.1
    # Candidate tripped its configured floors (config/eval_thresholds.yaml at
    # build time) even though no relative delta exceeds the tolerance.
    candidate["regression"] = True
    candidate["failures"] = [
        {
            "scope": "aggregate",
            "metric": "precision_at_k",
            "value": 0.1,
            "threshold": 0.15,
            "kind": "threshold_floor",
        }
    ]
    comparison = compare_scorecards(baseline, candidate)
    assert comparison["verdict"] == "regression"
    assert comparison["candidate_gate"]["regression"] is True


@pytest.mark.parametrize("target", ["baseline", "candidate"])
def test_cli_rejects_unreported_configured_floor_failure(
    target: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = load_scorecard(BASELINE_PATH)
    candidate = load_scorecard(CANDIDATE_PATH)
    scorecard = baseline if target == "baseline" else candidate
    scorecard["thresholds"]["aggregate"]["precision_at_k"] = 0.9
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    assert eval_run.main(
        [
            "compare",
            "--baseline",
            str(baseline_path),
            "--candidate",
            str(candidate_path),
        ]
    ) == 2
    assert "threshold failures contradict configured floors" in capsys.readouterr().err


# ── CLI seam ─────────────────────────────────────────────────────────────


def test_cli_compare_exit_code_on_regression(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    candidate = load_scorecard(CANDIDATE_PATH)
    candidate["aggregate"]["precision@k"] = 0.15
    regressed_path = tmp_path / "candidate_regressed.json"
    regressed_path.write_text(json.dumps(candidate), encoding="utf-8")

    artifact_path = tmp_path / "compare.json"
    code = eval_run.main(
        [
            "compare",
            "--baseline",
            str(BASELINE_PATH),
            "--candidate",
            str(regressed_path),
            "--output",
            str(artifact_path),
        ]
    )
    out = capsys.readouterr().out
    assert code == 1
    assert "VERDICT: regression" in out

    # Machine-readable compare artifact written for PR attachment.
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["schema_version"] == "eval_scorecard_compare.v1"
    assert artifact["verdict"] == "regression"


def test_cli_compare_rejects_unknown_schema_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bogus = tmp_path / "bogus.json"
    bogus.write_text(json.dumps({"schema_version": "eval_scorecard.v999"}), encoding="utf-8")
    code = eval_run.main(
        ["compare", "--baseline", str(bogus), "--candidate", str(CANDIDATE_PATH)]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "unsupported scorecard schema_version" in captured.err


def test_compare_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ScorecardCompareError, match="not found"):
        load_scorecard(tmp_path / "missing.json")


def test_default_run_path_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """`python -m app.eval.run` with no subcommand keeps building the scorecard."""
    calls: dict[str, object] = {}

    def fake_build_scorecard() -> dict:
        calls["built"] = True
        return {"regression": False, "failures": []}

    monkeypatch.setattr(eval_run, "build_scorecard", fake_build_scorecard)
    monkeypatch.setattr(eval_run, "write_scorecard", lambda s: calls.setdefault("written", s))
    monkeypatch.setattr(eval_run, "render_summary", lambda s: "stub summary")

    assert eval_run.main([]) == 0
    assert calls["built"] is True
    assert calls["written"] == {"regression": False, "failures": []}
