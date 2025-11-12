from __future__ import annotations

import pytest

from app.fitness.reasoning import reasoning_metrics
from app.fitness.report import _summary_line

pytestmark = pytest.mark.not_pg


def test_reasoning_metrics_flag_control() -> None:
    off = reasoning_metrics(flag_enabled=False)
    assert off["claims_avg"] == 0.0
    on = reasoning_metrics(flag_enabled=True)
    assert on["inferences_avg"] > 0


def test_reasoning_summary_line_format() -> None:
    line = _summary_line("REASONING", claims_avg="1.00", inferences_avg="0.50", conflicts="0.00", flag="on")
    assert "CI SUMMARY REASONING" in line
