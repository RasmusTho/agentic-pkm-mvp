from __future__ import annotations

import json
import math
import os
import runpy
import sys

import pytest

from app.fitness import qas003_hybrid_latency, qas010_outbox_to_index_latency

pytestmark = [pytest.mark.not_pg, pytest.mark.usefixtures("product_model_access_gateway")]


def test_qas003_latency_guard() -> None:
    result = qas003_hybrid_latency(samples=16)
    assert result["p95"] <= result["threshold"]
    assert result["count"] == 16


def test_qas010_latency_guard() -> None:
    result = qas010_outbox_to_index_latency(events=16)
    assert result["p95"] <= result["threshold"]
    assert result["count"] == 16


def test_ci_report_entrypoint_uses_scoped_product_gateway_fixture(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CI producer runs the complete report through the admitted test boundary."""
    for name in tuple(os.environ):
        if name.startswith("MODEL_ACCESS_") or name.endswith("_API_KEY"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("REASONING_ENABLE", "1")
    monkeypatch.delitem(sys.modules, "app.fitness.report", raising=False)
    try:
        report = runpy.run_module("app.fitness.report", run_name="__main__")
    finally:
        output = capsys.readouterr()
        # Keep the real report and its diagnostics in the workflow's tee log,
        # including when the entrypoint exits before these assertions run.
        with capsys.disabled():
            print(output.out, end="")
            print(output.err, end="", file=sys.stderr)

    payload, _ = json.JSONDecoder().raw_decode(output.out)
    summary = report["parse_summary_lines"](
        output.out.splitlines(), required=report["SUMMARY_LABELS"]
    )
    assert set(summary) == set(report["SUMMARY_LABELS"])
    for name in ("QAS-003", "QAS-010"):
        result = payload[name]
        assert result["count"] == 32
        assert set(result) == {"p95", "avg", "threshold", "count"}
        assert all(math.isfinite(value) for value in result.values())
    for result in payload["golden"].values():
        assert set(result) == {"precision@k", "ndcg@k"}
        assert all(math.isfinite(value) and 0 <= value <= 1 for value in result.values())
    for result in summary.values():
        assert all(
            math.isfinite(value) for value in result.values() if isinstance(value, float)
        )

    ok, reasons = report["evaluate_gates"](
        summary,
        report["load_thresholds"](),
        provider=os.getenv("CI_EVAL_RERANK_PROVIDER", "ce_local"),
        diarization_off=payload["diarization"]["off"],
        strict=report["_truthy"](os.getenv("GATE_STRICT")),
        reasoning_enabled=True,
    )
    assert summary["GATES"] == {"ok": ok, "reasons": ",".join(reasons)}
    assert ok, reasons
