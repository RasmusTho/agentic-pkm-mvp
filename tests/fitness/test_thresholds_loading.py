from __future__ import annotations

from pathlib import Path

import pytest

from app.fitness.report import evaluate_gates, load_thresholds, parse_summary_lines

pytestmark = pytest.mark.not_pg


def test_load_thresholds_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "thresholds.yaml"
    cfg.write_text(
        "latency:\n  tolerance: 0.05\n  QAS003:\n    value: 0.1\n  QAS010:\n    value: 0.2\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("THRESHOLDS_PATH", str(cfg))
    data = load_thresholds()
    assert data["latency"]["tolerance"] == 0.05
    assert data["latency"]["QAS010"]["value"] == 0.2
    monkeypatch.delenv("THRESHOLDS_PATH", raising=False)


def test_gate_strict_requires_positive_deltas() -> None:
    lines = [
        "CI SUMMARY LATENCY QAS003=0.050s QAS010=0.020s",
        "CI SUMMARY EVAL P10=0.188 NDCG10=0.924 BASE_P10=0.188 BASE_NDCG10=0.855",
        "CI SUMMARY EVAL DELTA DP10=+0.000 DnDCG10=+0.000 RELATION_TARGET=60%",
        "CI SUMMARY RELATION COVERAGE=100.00%",
        "CI SUMMARY RELATIONS coverage=100.00% validity=100.00% target=95%",
        "CI SUMMARY DIARIZATION chunk_p95=70.00 speaker_avg=2.33 flag=on",
        "CI SUMMARY REASONING claims_avg=1.50 inferences_avg=0.70 conflicts=0.00 flag=off",
    ]
    parsed = parse_summary_lines(
        lines,
        required=[
            "LATENCY",
            "EVAL",
            "EVAL DELTA",
            "RELATION COVERAGE",
            "RELATIONS",
            "DIARIZATION",
            "REASONING",
        ],
    )
    thresholds = {
        "latency": {"tolerance": 0.10, "QAS003": {"value": 0.1}, "QAS010": {"value": 0.05}},
        "eval": {"delta_precision_min": 0.005, "delta_ndcg_min": 0.01, "delta_abs_tolerance": 0.005},
        "relations": {"coverage_min": 0.95, "validity_min": 0.95},
        "diarization": {"p95_ratio_max": 0.95},
        "reasoning": {"claims_avg_min": 1.0, "inferences_avg_min": 0.5, "conflicts_max": 1.0},
    }
    ok_relaxed, reasons_relaxed = evaluate_gates(
        parsed,
        thresholds,
        provider="ce_local",
        diarization_off={"chunk_p95": 80.0},
        strict=False,
        reasoning_enabled=False,
    )
    assert ok_relaxed
    ok_strict, reasons_strict = evaluate_gates(
        parsed,
        thresholds,
        provider="ce_local",
        diarization_off={"chunk_p95": 80.0},
        strict=True,
        reasoning_enabled=False,
    )
    assert not ok_strict
    assert reasons_strict == ["EVAL_DELTA"]
