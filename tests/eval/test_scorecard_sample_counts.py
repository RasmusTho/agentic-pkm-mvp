"""Sample-count shrink is a scorecard compare regression (#5708, audit #2899 F8).

A candidate with fewer cases but unchanged metric values and slice keys must
not read as neutral/improved: every supported sample count (retrieval
aggregate, memory recall, per-language / per-slice retrieval buckets,
classification total, per-class support) is compared baseline -> candidate.
Pure fixture comparison through the real compare seam and CLI.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.eval import run as eval_run
from app.eval.compare import (
    ScorecardCompareError,
    compare_scorecards,
    load_scorecard,
    render_compare_summary,
)

pytestmark = pytest.mark.not_pg

FIXTURES = Path(__file__).parent / "fixtures"
BASELINE_PATH = FIXTURES / "scorecard_baseline.json"
CANDIDATE_PATH = FIXTURES / "scorecard_candidate.json"
CLASSES = ("co_authoring", "governance_bearing", "exploratory")


def _reconcile_classification(scorecard: dict) -> None:
    """Re-derive matrix-bound classification fields so the card stays valid."""
    classification = scorecard["classification"]
    matrix = classification["confusion_matrix"]
    classification["n_cases"] = sum(sum(row.values()) for row in matrix.values())
    precision: list[float] = []
    recall: list[float] = []
    for name in CLASSES:
        support = sum(matrix[name].values())
        predicted = sum(matrix[expected][name] for expected in matrix)
        answered = support - matrix[name]["unknown"]
        tp = matrix[name][name]
        class_precision = tp / predicted if predicted else 0.0
        class_recall = tp / answered if answered else 0.0
        classification["per_class"][name] = {
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
    safe_fail_count = sum(matrix[name]["unknown"] for name in CLASSES)
    answerable = classification["n_cases"] - unknown_expected
    classification["safe_fail"] = {
        "count": safe_fail_count,
        "answer_rate": (answerable - safe_fail_count) / answerable if answerable else 0.0,
    }


def _shrink_retrieval(scorecard: dict) -> None:
    """Drop one 'en'/'exact_lexical' case; every metric value stays identical."""
    scorecard["aggregate"]["count"] -= 1
    scorecard["by_language"]["en"]["count"] -= 1
    scorecard["by_slice"]["exact_lexical"]["count"] -= 1


def _shrink_classification(scorecard: dict) -> None:
    """Drop one correctly classified exploratory case (metrics stay in tolerance)."""
    scorecard["classification"]["confusion_matrix"]["exploratory"]["exploratory"] -= 1
    _reconcile_classification(scorecard)


def _shrink_memory_recall(scorecard: dict) -> None:
    scorecard["memory_recall"]["count"] -= 1


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            _shrink_retrieval,
            [
                {"path": "aggregate.count", "baseline": 11, "candidate": 10},
                {"path": "by_language.en.count", "baseline": 6, "candidate": 5},
                {"path": "by_slice.exact_lexical.count", "baseline": 3, "candidate": 2},
            ],
        ),
        (
            _shrink_memory_recall,
            [{"path": "memory_recall.count", "baseline": 5, "candidate": 4}],
        ),
        (
            _shrink_classification,
            [
                {"path": "classification.n_cases", "baseline": 68, "candidate": 67},
                {
                    "path": "classification.per_class.exploratory.support",
                    "baseline": 25,
                    "candidate": 24,
                },
            ],
        ),
    ],
    ids=["retrieval", "memory_recall", "classification"],
)
def test_sample_count_shrink_is_regression_with_unchanged_metrics(
    mutate, expected
) -> None:
    baseline = load_scorecard(BASELINE_PATH)
    candidate = copy.deepcopy(baseline)
    mutate(candidate)

    comparison = compare_scorecards(baseline, candidate)

    # Slice keys and metrics hold (no tolerance-relative regression, no
    # missing slice), yet the reduced coverage blocks.
    assert comparison["missing_slices"] == []
    assert comparison["regressions"] == []
    assert comparison["sample_count_regressions"] == expected
    assert comparison["verdict"] == "regression"
    summary = render_compare_summary(comparison)
    assert "Sample counts that SHRANK vs baseline (blocking):" in summary
    for item in expected:
        assert f"  - {item['path']}: {item['baseline']} -> {item['candidate']}" in summary


def test_equal_or_larger_samples_preserve_existing_verdict_rules() -> None:
    baseline = load_scorecard(BASELINE_PATH)

    # Equal counts: identical pair stays neutral with no count findings.
    identical = compare_scorecards(baseline, copy.deepcopy(baseline))
    assert identical["verdict"] == "neutral"
    assert identical["sample_count_regressions"] == []
    assert identical["sample_count_increases"] == []

    # Larger counts with identical metrics: informational only, never "improved".
    grown = copy.deepcopy(baseline)
    grown["aggregate"]["count"] += 2
    grown["by_language"]["sv"]["count"] += 2
    grown_cmp = compare_scorecards(baseline, grown)
    assert grown_cmp["verdict"] == "neutral"
    assert grown_cmp["sample_count_regressions"] == []
    assert grown_cmp["sample_count_increases"] == [
        {"path": "aggregate.count", "baseline": 11, "candidate": 13},
        {"path": "by_language.sv.count", "baseline": 5, "candidate": 7},
    ]
    assert "Sample counts that grew (reported, non-blocking):" in render_compare_summary(
        grown_cmp
    )

    # The fixture candidate's metric improvement is unchanged by larger counts.
    improved = load_scorecard(CANDIDATE_PATH)
    improved["aggregate"]["count"] += 2
    improved["by_slice"]["hybrid_semantic"]["count"] += 2
    assert compare_scorecards(baseline, improved)["verdict"] == "improved"

    # Existing metric-tolerance regression still fires with larger counts.
    worse = copy.deepcopy(grown)
    worse["aggregate"]["precision@k"] = 0.15
    worse_cmp = compare_scorecards(baseline, worse)
    assert worse_cmp["verdict"] == "regression"
    assert worse_cmp["sample_count_regressions"] == []
    assert any(row["slice"] == "aggregate" for row in worse_cmp["regressions"])

    # Existing missing-slice regression still fires; the vanished slice's count
    # is reported by missing_slices, not double-counted as a count shrink.
    missing = copy.deepcopy(grown)
    del missing["by_slice"]["hybrid_semantic"]
    missing_cmp = compare_scorecards(baseline, missing)
    assert missing_cmp["verdict"] == "regression"
    assert missing_cmp["missing_slices"] == [{"group": "by_slice", "key": "hybrid_semantic"}]
    assert missing_cmp["sample_count_regressions"] == []

    # Existing hard-gate regression still fires on otherwise equal counts.
    gated = load_scorecard(CANDIDATE_PATH)
    gated["classification"]["hard_gate_passed"] = False
    gated["classification"]["mutation_side_confusions"] = [
        {
            "case_id": "adv-sv-01",
            "expected_intent": "exploratory",
            "predicted_intent": "governance_bearing",
        }
    ]
    matrix = gated["classification"]["confusion_matrix"]
    matrix["exploratory"]["exploratory"] -= 1
    matrix["exploratory"]["governance_bearing"] += 1
    _reconcile_classification(gated)
    gated["regression"] = True
    gated["failures"] = [
        {
            "scope": "classification:hard_gate",
            "metric": "mutation_side_confusion:adv-sv-01->governance_bearing",
            "value": 1.0,
            "threshold": 0.0,
            "kind": "categorical",
        }
    ]
    gated_cmp = compare_scorecards(baseline, gated)
    assert gated_cmp["verdict"] == "regression"
    assert gated_cmp["classification_confusion"]["candidate_hard_gate_passed"] is False
    assert gated_cmp["sample_count_regressions"] == []


@pytest.mark.parametrize(
    ("side", "mutate", "message"),
    [
        (
            "candidate",
            lambda s: s["aggregate"].pop("count"),
            "missing required sample count at candidate.aggregate.count",
        ),
        (
            "baseline",
            lambda s: s["by_language"]["sv"].pop("count"),
            "missing required sample count at baseline.by_language.sv.count",
        ),
        (
            "candidate",
            lambda s: s["memory_recall"].__setitem__("count", -1),
            "non-negative integer at candidate.memory_recall.count",
        ),
        (
            "candidate",
            lambda s: s["by_slice"]["exact_lexical"].__setitem__("count", 2.5),
            "non-negative integer at candidate.by_slice.exact_lexical.count",
        ),
        (
            "candidate",
            lambda s: s["by_language"]["en"].__setitem__("count", True),
            "non-negative integer at candidate.by_language.en.count",
        ),
        (
            "candidate",
            lambda s: s["aggregate"].__setitem__("count", "11"),
            "non-negative integer at candidate.aggregate.count",
        ),
        (
            "candidate",
            lambda s: s["by_language"]["en"].__setitem__("count", 12),
            "sample count contradicts aggregate count at candidate.by_language.en.count",
        ),
        (
            "candidate",
            lambda s: s["classification"]["per_class"]["exploratory"].__setitem__(
                "support", 24
            ),
            "support contradicts confusion matrix",
        ),
        (
            "candidate",
            lambda s: s["classification"].__setitem__("n_cases", 67),
            "n_cases contradicts confusion matrix",
        ),
    ],
    ids=[
        "missing-aggregate",
        "missing-baseline-language",
        "negative",
        "non-integer",
        "bool",
        "string",
        "exceeds-aggregate",
        "per-class-support-contradiction",
        "classification-total-contradiction",
    ],
)
def test_invalid_sample_counts_are_malformed_input(side, mutate, message) -> None:
    cards = {
        "baseline": load_scorecard(BASELINE_PATH),
        "candidate": load_scorecard(BASELINE_PATH),
    }
    mutate(cards[side])
    with pytest.raises(ScorecardCompareError) as excinfo:
        compare_scorecards(cards["baseline"], cards["candidate"])
    assert message in str(excinfo.value)


def test_compare_cli_distinguishes_shrink_from_malformed_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = load_scorecard(BASELINE_PATH)

    shrunk = copy.deepcopy(baseline)
    _shrink_retrieval(shrunk)
    shrunk_path = tmp_path / "candidate_shrunk.json"
    shrunk_path.write_text(json.dumps(shrunk), encoding="utf-8")

    artifacts = []
    for name in ("compare_a.json", "compare_b.json"):
        artifact_path = tmp_path / name
        code = eval_run.main(
            [
                "compare",
                "--baseline",
                str(BASELINE_PATH),
                "--candidate",
                str(shrunk_path),
                "--output",
                str(artifact_path),
            ]
        )
        out = capsys.readouterr().out
        assert code == 1
        assert "VERDICT: regression" in out
        assert "Sample counts that SHRANK vs baseline (blocking):" in out
        assert "  - by_language.en.count: 6 -> 5" in out
        artifacts.append(artifact_path.read_bytes())

    # Deterministic artifact for an identical input pair (paths aside).
    first, second = (json.loads(raw) for raw in artifacts)
    assert first == second
    assert first["verdict"] == "regression"
    assert {"path": "aggregate.count", "baseline": 11, "candidate": 10} in first[
        "sample_count_regressions"
    ]

    malformed = copy.deepcopy(baseline)
    malformed["by_slice"]["exact_lexical"]["count"] = -3
    malformed_path = tmp_path / "candidate_malformed.json"
    malformed_path.write_text(json.dumps(malformed), encoding="utf-8")
    malformed_artifact = tmp_path / "compare_malformed.json"
    code = eval_run.main(
        [
            "compare",
            "--baseline",
            str(BASELINE_PATH),
            "--candidate",
            str(malformed_path),
            "--output",
            str(malformed_artifact),
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "error:" in captured.err
    assert "candidate.by_slice.exact_lexical.count" in captured.err
    assert "VERDICT" not in captured.out
    assert not malformed_artifact.exists()
