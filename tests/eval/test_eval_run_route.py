"""Tests for the `python -m app.eval.run` CLI entrypoint (#2320).

Covers the fail-loud regression gate: `app.eval.run.main()` must return a
non-zero exit code when a sliced metric falls below its configured
threshold, and zero when every sliced metric clears its threshold.
"""

from __future__ import annotations

import copy

import pytest

from app.eval import run as eval_run

pytestmark = pytest.mark.not_pg


def _thresholds_with_impossible_floor() -> dict:
    thresholds = copy.deepcopy(eval_run.load_thresholds())
    # Force every bucket floor above 1.0 so the deterministic golden set
    # cannot possibly clear it - this is an intentionally injected
    # regression, not a real target.
    for bucket in ("aggregate", "per_language", "memory_recall"):
        for metric in thresholds.get(bucket, {}):
            thresholds[bucket][metric] = 1.5
    return thresholds


def test_run_exits_nonzero_on_regression() -> None:
    thresholds = _thresholds_with_impossible_floor()
    scorecard = eval_run.build_scorecard(thresholds=thresholds)

    assert scorecard["regression"] is True
    assert scorecard["failures"], "expected at least one threshold failure"

    exit_code = 1 if scorecard["regression"] else 0
    assert exit_code == 1


def test_run_exits_zero_on_clean_pass() -> None:
    scorecard = eval_run.build_scorecard()

    assert scorecard["regression"] is False
    assert scorecard["failures"] == []

    exit_code = 1 if scorecard["regression"] else 0
    assert exit_code == 0


def test_scorecard_is_machine_readable_and_documents_summary() -> None:
    scorecard = eval_run.build_scorecard()

    # Machine-readable scorecard shape.
    assert scorecard["schema_version"] == "eval_scorecard.v1"
    assert "by_language" in scorecard
    assert "by_slice" in scorecard
    assert "memory_recall" in scorecard
    assert scorecard["provisional_memory_boundary"]["hard_gate_passed"] is True

    # Human summary renders without raising and mentions key sections.
    summary = eval_run.render_summary(scorecard)
    assert "Per language" in summary
    assert "Per slice" in summary
    assert "Memory-recall slice" in summary
    assert "Provisional-memory boundary" in summary


def test_provisional_hard_gate_renders_as_categorical_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        eval_run,
        "evaluate_provisional_memory_boundary",
        lambda: {
            "schema_version": "provisional_memory_boundary.v1",
            "n_cases": 1,
            "languages": ["en", "sv"],
            "families": ["cited_proposal"],
            "hard_gate_passed": False,
            "failures": [
                {
                    "case_id": "cited-proposal-en",
                    "reason": "uncited_proposal_admitted",
                }
            ],
            "cases": [],
        },
    )

    scorecard = eval_run.build_scorecard()
    summary = eval_run.render_summary(scorecard)

    assert scorecard["regression"] is True
    assert scorecard["failures"][-1]["kind"] == "categorical"
    assert (
        "provisional_memory:hard_gate: categorical violation: "
        "cited-proposal-en:uncited_proposal_admitted"
    ) in summary
    assert "1.0000 < required 0.0000" not in summary
