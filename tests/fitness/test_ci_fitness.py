from __future__ import annotations

import pytest

from app.fitness import qas003_hybrid_latency, qas010_outbox_to_index_latency

pytestmark = pytest.mark.not_pg


def test_qas003_latency_guard() -> None:
    result = qas003_hybrid_latency(samples=16)
    assert result["p95"] <= result["threshold"]
    assert result["count"] == 16


def test_qas010_latency_guard() -> None:
    result = qas010_outbox_to_index_latency(events=16)
    assert result["p95"] <= result["threshold"]
    assert result["count"] == 16
