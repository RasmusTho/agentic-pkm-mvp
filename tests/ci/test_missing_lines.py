from __future__ import annotations

import pytest

from app.fitness.report import SUMMARY_LABELS, parse_summary_lines

pytestmark = pytest.mark.not_pg


def test_missing_summary_lines_raise_error() -> None:
    lines = [
        "CI SUMMARY LATENCY QAS003=0.1s QAS010=0.05s",
        "CI SUMMARY EVAL P10=0.188 NDCG10=0.924 BASE_P10=0.188 BASE_NDCG10=0.855",
    ]
    with pytest.raises(ValueError):
        parse_summary_lines(lines, required=SUMMARY_LABELS)
