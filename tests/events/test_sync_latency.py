"""Tests for sync-chain timestamp and latency tracking."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from uuid import uuid4


from app.events.sync import (
    SyncChainCorrelationData,
    SyncLatencySummaryEvent,
    SyncLatencySummaryPayload,
    _ts_to_ms,
)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


class TestTimestampConversion:
    """Test _ts_to_ms timestamp conversion."""

    def test_convert_iso_z_format(self) -> None:
        """Convert ISO timestamp with Z suffix."""
        iso_ts = "2025-03-05T14:30:00Z"
        ms = _ts_to_ms(iso_ts)
        assert ms > 0

    def test_convert_iso_plus_offset(self) -> None:
        """Convert ISO timestamp with +00:00 offset."""
        iso_ts = "2025-03-05T14:30:00+00:00"
        ms = _ts_to_ms(iso_ts)
        assert ms > 0

    def test_convert_two_timestamps_ordering(self) -> None:
        """Verify timestamp ordering (earlier < later)."""
        ts1 = "2025-03-05T14:30:00Z"
        ts2 = "2025-03-05T14:35:00Z"
        ms1 = _ts_to_ms(ts1)
        ms2 = _ts_to_ms(ts2)
        assert ms1 < ms2

    def test_convert_invalid_returns_zero(self) -> None:
        """Invalid timestamp returns 0."""
        assert _ts_to_ms("invalid") == 0.0
        assert _ts_to_ms("") == 0.0


class TestSyncLatencySummaryPayload:
    """Test latency summary payload structure."""

    def test_payload_creation(self) -> None:
        """Create a valid latency summary payload."""
        now = _now_iso()
        payload = SyncLatencySummaryPayload(
            note_uuid="test-uuid-123",
            note_path="Notes/test.md",
            file_detection_ts=now,
            scan_requested_ts=now,
            runtime_start_ts=now,
            runtime_complete_ts=now,
            watcher_to_scan_ms=10,
            scan_to_runtime_start_ms=20,
            runtime_execution_ms=100,
            end_to_end_ms=130,
            trace_id="trace-001",
        )
        assert payload.note_uuid == "test-uuid-123"
        assert payload.trace_id == "trace-001"
        assert payload.end_to_end_ms == 130

    def test_payload_json_serialization(self) -> None:
        """Payload serializes to valid JSON."""
        now = _now_iso()
        payload = SyncLatencySummaryPayload(
            note_uuid="test-uuid",
            note_path="Notes/test.md",
            file_detection_ts=now,
            scan_requested_ts=now,
            runtime_start_ts=now,
            runtime_complete_ts=now,
            watcher_to_scan_ms=5,
            scan_to_runtime_start_ms=10,
            runtime_execution_ms=50,
            end_to_end_ms=65,
            trace_id="trace-001",
        )
        json_str = payload.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["note_uuid"] == "test-uuid"
        assert parsed["end_to_end_ms"] == 65


class TestSyncChainCorrelationData:
    """Test sync-chain correlation tracking."""

    def test_correlation_creation(self) -> None:
        """Create correlation data for a note."""
        trace_id = uuid4().hex
        now = _now_iso()
        correlation = SyncChainCorrelationData(
            trace_id=trace_id,
            note_uuid="test-uuid",
            note_path="Notes/test.md",
            file_detection_ts=now,
            scan_requested_ts=now,
            runtime_start_ts=now,
        )
        assert correlation.trace_id == trace_id
        assert correlation.note_uuid == "test-uuid"

    def test_correlation_completion_with_zero_latency(self) -> None:
        """Complete correlation with same timestamps (zero latency)."""
        trace_id = uuid4().hex
        now = _now_iso()
        correlation = SyncChainCorrelationData(
            trace_id=trace_id,
            note_uuid="test-uuid",
            note_path="Notes/test.md",
            file_detection_ts=now,
            scan_requested_ts=now,
            runtime_start_ts=now,
        )
        summary = correlation.complete(completion_ts=now)
        # All milestones should be zero or close to zero
        assert summary.watcher_to_scan_ms >= 0
        assert summary.scan_to_runtime_start_ms >= 0
        assert summary.runtime_execution_ms >= 0
        assert summary.end_to_end_ms >= 0

    def test_correlation_completion_computes_latencies(self) -> None:
        """Complete correlation computes latency milestones correctly."""
        trace_id = uuid4().hex
        base_time = datetime(2025, 3, 5, 14, 30, 0, tzinfo=timezone.utc)

        file_detect_ts = base_time.isoformat().replace("+00:00", "Z")
        scan_req_ts = (base_time + timedelta(milliseconds=10)).isoformat().replace("+00:00", "Z")
        runtime_start_ts = (base_time + timedelta(milliseconds=30)).isoformat().replace("+00:00", "Z")
        completion_ts = (base_time + timedelta(milliseconds=130)).isoformat().replace("+00:00", "Z")

        correlation = SyncChainCorrelationData(
            trace_id=trace_id,
            note_uuid="test-uuid",
            note_path="Notes/test.md",
            file_detection_ts=file_detect_ts,
            scan_requested_ts=scan_req_ts,
            runtime_start_ts=runtime_start_ts,
        )
        summary = correlation.complete(completion_ts=completion_ts)

        # Verify latency computations (allow for small rounding errors)
        assert abs(summary.watcher_to_scan_ms - 10) <= 1
        assert abs(summary.scan_to_runtime_start_ms - 20) <= 1
        assert abs(summary.runtime_execution_ms - 100) <= 1
        assert abs(summary.end_to_end_ms - 130) <= 1

    def test_correlation_preserves_trace_id(self) -> None:
        """Completion preserves the trace_id for correlation."""
        trace_id = uuid4().hex
        now = _now_iso()
        correlation = SyncChainCorrelationData(
            trace_id=trace_id,
            note_uuid="test-uuid",
            note_path="Notes/test.md",
            file_detection_ts=now,
            scan_requested_ts=now,
            runtime_start_ts=now,
        )
        summary = correlation.complete(completion_ts=now)
        assert summary.trace_id == trace_id


class TestSyncLatencySummaryEvent:
    """Test latency summary event."""

    def test_event_creation(self) -> None:
        """Create a latency summary event."""
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
            runtime_execution_ms=0,
            end_to_end_ms=0,
            trace_id="trace-001",
        )
        event = SyncLatencySummaryEvent(payload=payload)
        assert event.event == "sync.latency.summary"
        assert event.version == "1.0"
        assert event.source == "worker"
        assert event.payload.note_uuid == "test-uuid"

    def test_event_json_serialization(self) -> None:
        """Event serializes to valid JSON."""
        now = _now_iso()
        payload = SyncLatencySummaryPayload(
            note_uuid="test-uuid",
            note_path="Notes/test.md",
            file_detection_ts=now,
            scan_requested_ts=now,
            runtime_start_ts=now,
            runtime_complete_ts=now,
            watcher_to_scan_ms=50,
            scan_to_runtime_start_ms=20,
            runtime_execution_ms=100,
            end_to_end_ms=170,
            trace_id="trace-001",
        )
        event = SyncLatencySummaryEvent(payload=payload)
        json_str = event.model_dump_json()
        parsed = json.loads(json_str)

        assert parsed["event"] == "sync.latency.summary"
        assert parsed["source"] == "worker"
        assert parsed["payload"]["end_to_end_ms"] == 170

    def test_event_has_unique_event_id(self) -> None:
        """Each event gets a unique event_id."""
        now = _now_iso()
        payload1 = SyncLatencySummaryPayload(
            note_uuid="uuid1",
            note_path="Notes/1.md",
            file_detection_ts=now,
            scan_requested_ts=now,
            runtime_start_ts=now,
            runtime_complete_ts=now,
            watcher_to_scan_ms=0,
            scan_to_runtime_start_ms=0,
            runtime_execution_ms=0,
            end_to_end_ms=0,
            trace_id="trace-001",
        )
        payload2 = SyncLatencySummaryPayload(
            note_uuid="uuid2",
            note_path="Notes/2.md",
            file_detection_ts=now,
            scan_requested_ts=now,
            runtime_start_ts=now,
            runtime_complete_ts=now,
            watcher_to_scan_ms=0,
            scan_to_runtime_start_ms=0,
            runtime_execution_ms=0,
            end_to_end_ms=0,
            trace_id="trace-002",
        )
        event1 = SyncLatencySummaryEvent(payload=payload1)
        event2 = SyncLatencySummaryEvent(payload=payload2)

        assert event1.event_id != event2.event_id
