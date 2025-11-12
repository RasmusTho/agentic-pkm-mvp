from __future__ import annotations

import pytest

from app.fitness.chunks import diarization_metrics
from app.fitness.report import _summary_line

pytestmark = pytest.mark.not_pg


def test_diarization_metrics_reduce_chunk_p95() -> None:
    baseline = diarization_metrics(flag_enabled=False)
    diarized = diarization_metrics(flag_enabled=True)
    assert diarized["chunk_p95"] <= baseline["chunk_p95"] * 0.95
    assert diarized["speaker_avg"] >= 1.0


def test_diarization_summary_line_format() -> None:
    line = _summary_line("DIARIZATION", chunk_p95="80.0", speaker_avg="2.3", flag="on")
    assert "CI SUMMARY DIARIZATION" in line
    assert "chunk_p95=80.0" in line
