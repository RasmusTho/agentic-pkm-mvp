from __future__ import annotations

import pytest

from app.observability.status_model import SystemStatus

pytestmark = pytest.mark.not_pg


def test_status_slice_wired_into_system_status() -> None:
    status = SystemStatus(
        timestamp="2026-10-15T00:00:00+00:00",
        environment="test",
        sot_version="test",
        sot_baseline_version="test",
        sot_forward_line_version="test",
        sot_label="test",
        stores=[],
        ingestion={"total_scanned": 0, "total_ingested": 0, "total_errors": 0, "total_malformed": 0},
        ask={"total_queries_24h": 0},
        youtube_sync={
            "auth_status": "connected",
            "sources": {"total": 1, "enabled": 1, "degraded": 0},
            "queue": {"depth": 2, "dead_letters": 0},
            "quota": {"spent_today": 2, "budget": 10000, "exhausted": False},
        },
    )
    assert status.youtube_sync is not None
    assert status.youtube_sync["sources"]["enabled"] == 1
    assert status.youtube_sync["queue"]["depth"] == 2
