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
)

pytestmark = pytest.mark.not_pg

FIXTURES = Path(__file__).parent / "fixtures"
BASELINE_PATH = FIXTURES / "scorecard_baseline.json"
CANDIDATE_PATH = FIXTURES / "scorecard_candidate.json"


def _rows_by_metric(rows: list[dict]) -> dict[str, dict]:
    return {row["metric"]: row for row in rows}


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
    comparison = compare_scorecards(baseline, candidate)
    assert comparison["verdict"] == "regression"
    assert comparison["classification_confusion"]["candidate_hard_gate_passed"] is False


def test_verdict_regression_when_candidate_fails_own_floors() -> None:
    baseline = load_scorecard(BASELINE_PATH)
    candidate = load_scorecard(CANDIDATE_PATH)
    # Candidate tripped its configured floors (config/eval_thresholds.yaml at
    # build time) even though no relative delta exceeds the tolerance.
    candidate["regression"] = True
    candidate["failures"] = [
        {"scope": "aggregate", "metric": "precision_at_k", "value": 0.1, "threshold": 0.15}
    ]
    comparison = compare_scorecards(baseline, candidate)
    assert comparison["verdict"] == "regression"
    assert comparison["candidate_gate"]["regression"] is True


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
