"""Tests for panel scan latency tracking in the worker."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture
def temp_vault(tmp_path: Path) -> Path:
    """Create a temporary vault with a test note."""
    vault = tmp_path / "vault"
    vault.mkdir()

    note_file = vault / "test.md"
    note_file.write_text(
        "---\nuuid: test-uuid-001\ntitle: Test Note\n---\n\nContent",
        encoding="utf-8"
    )

    return vault


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


class TestLatencySummaryEventSerialization:
    """Test latency summary event serialization for worker."""

    def test_latency_summary_contains_required_fields(self, tmp_path: Path) -> None:
        """Latency summary event contains all required timing fields."""
        from app.events.sync import SyncLatencySummaryEvent, SyncLatencySummaryPayload

        now = _now_iso()
        payload = SyncLatencySummaryPayload(
            note_uuid="test-uuid",
            note_path="Notes/test.md",
            file_detection_ts=now,
            scan_requested_ts=now,
            runtime_start_ts=now,
            runtime_complete_ts=now,
            watcher_to_scan_ms=10,
            scan_to_runtime_start_ms=5,
            runtime_execution_ms=100,
            end_to_end_ms=115,
            trace_id="trace-123",
        )
        event = SyncLatencySummaryEvent(payload=payload)

        # Verify all required fields are present
        assert event.event == "sync.latency.summary"
        assert event.payload.note_uuid == "test-uuid"
        assert event.payload.file_detection_ts == now
        assert event.payload.scan_requested_ts == now
        assert event.payload.runtime_start_ts == now
        assert event.payload.runtime_complete_ts == now
        assert event.payload.end_to_end_ms == 115
        assert event.payload.trace_id == "trace-123"

    def test_latency_summary_event_serializes_to_jsonl(self, tmp_path: Path) -> None:
        """Latency summary serializes correctly for JSONL outbox."""
        from app.events.sync import SyncLatencySummaryEvent, SyncLatencySummaryPayload

        now = _now_iso()
        payload = SyncLatencySummaryPayload(
            note_uuid="test-uuid",
            note_path="Notes/test.md",
            file_detection_ts=now,
            scan_requested_ts=now,
            runtime_start_ts=now,
            runtime_complete_ts=now,
            watcher_to_scan_ms=0,
            scan_to_runtime_start_ms=0,
            runtime_execution_ms=50,
            end_to_end_ms=50,
            trace_id="trace-123",
        )
        event = SyncLatencySummaryEvent(payload=payload)

        # Serialize to JSONL format
        json_line = event.model_dump_json()

        # Should be valid JSON
        parsed = json.loads(json_line)
        assert parsed["event"] == "sync.latency.summary"
        assert parsed["source"] == "worker"
        assert parsed["payload"]["end_to_end_ms"] == 50

    def test_trace_id_correlation_across_stages(self) -> None:
        """Trace ID is preserved for correlation across sync chain."""
        from app.events.sync import SyncChainCorrelationData

        trace_id = uuid4().hex
        now = _now_iso()

        correlation = SyncChainCorrelationData(
            trace_id=trace_id,
            note_uuid="uuid-123",
            note_path="Notes/example.md",
            file_detection_ts=now,
            scan_requested_ts=now,
            runtime_start_ts=now,
        )

        summary = correlation.complete(completion_ts=now)

        # Trace ID should match through the entire chain
        assert summary.trace_id == trace_id

    def test_latency_calculation_is_monotonic(self) -> None:
        """Latency calculations don't produce negative values."""
        from app.events.sync import SyncChainCorrelationData
        from datetime import datetime, timezone

        trace_id = uuid4().hex
        base_time = datetime(2025, 3, 5, 14, 30, 0, tzinfo=timezone.utc)

        file_detect_ts = base_time.isoformat().replace("+00:00", "Z")
        scan_req_ts = (base_time + timedelta(milliseconds=5)).isoformat().replace("+00:00", "Z")
        runtime_start_ts = (base_time + timedelta(milliseconds=15)).isoformat().replace("+00:00", "Z")
        completion_ts = (base_time + timedelta(milliseconds=150)).isoformat().replace("+00:00", "Z")

        correlation = SyncChainCorrelationData(
            trace_id=trace_id,
            note_uuid="uuid",
            note_path="test.md",
            file_detection_ts=file_detect_ts,
            scan_requested_ts=scan_req_ts,
            runtime_start_ts=runtime_start_ts,
        )

        summary = correlation.complete(completion_ts=completion_ts)

        # All latency values should be non-negative
        assert summary.watcher_to_scan_ms >= 0
        assert summary.scan_to_runtime_start_ms >= 0
        assert summary.runtime_execution_ms >= 0
        assert summary.end_to_end_ms >= 0

        # End-to-end should be sum of all stages
        assert summary.end_to_end_ms >= summary.runtime_execution_ms
