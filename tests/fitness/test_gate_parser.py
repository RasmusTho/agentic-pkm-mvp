from __future__ import annotations

import pytest

from app.fitness.report import parse_summary_lines, evaluate_gates

pytestmark = pytest.mark.not_pg


def test_parse_and_gate_failure_codes() -> None:
    lines = [
        "CI SUMMARY LATENCY QAS003=0.120s QAS010=0.060s",
        "CI SUMMARY EVAL P10=0.180 NDCG10=0.820 BASE_P10=0.180 BASE_NDCG10=0.820",
        "CI SUMMARY EVAL DELTA DP10=+0.000 DnDCG10=-0.001 RELATION_TARGET=60%",
        "CI SUMMARY RELATION COVERAGE=80.00%",
        "CI SUMMARY RELATIONS coverage=80.00% validity=80.00% target=95%",
        "CI SUMMARY DIARIZATION chunk_p95=140.00 speaker_avg=1.50 flag=on",
        "CI SUMMARY REASONING claims_avg=0.00 inferences_avg=0.00 conflicts=2.00 flag=on",
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
        ],
    )
    thresholds = {
        "latency": {"tolerance": 0.05, "QAS003": {"value": 0.1}, "QAS010": {"value": 0.05}},
        "eval": {"delta_precision_min": 0.005, "delta_ndcg_min": 0.01, "delta_abs_tolerance": 0.001},
        "relations": {"coverage_min": 0.95, "validity_min": 0.95},
        "diarization": {"p95_ratio_max": 0.95},
        "reasoning": {"claims_avg_min": 1.0, "inferences_avg_min": 0.5, "conflicts_max": 1.0},
    }
    ok, reasons = evaluate_gates(
        parsed,
        thresholds,
        provider="ce_local",
        diarization_off={"chunk_p95": 100.0},
        strict=True,
        reasoning_enabled=True,
    )
    assert not ok
    assert set(reasons) == {"LAT", "EVAL_DELTA", "REL_COV", "REL_VAL", "DIA_P95", "REASONING"}
