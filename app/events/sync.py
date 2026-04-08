from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _ts_to_ms(iso_timestamp: str) -> float:
    """Convert ISO-8601 UTC timestamp to milliseconds since epoch."""
    try:
        # Remove Z suffix if present, add +00:00 for parsing
        ts_str = iso_timestamp.rstrip("Z") if iso_timestamp.endswith("Z") else iso_timestamp
        if "+" not in ts_str and "Z" not in ts_str:
            ts_str += "+00:00"
        dt = datetime.fromisoformat(ts_str)
        return dt.timestamp() * 1000.0
    except Exception:
        return 0.0


class SyncLatencySummaryPayload(BaseModel):
    """Correlated timing data for a changed note across the sync chain."""

    note_uuid: str
    note_path: str

    # Timestamps from the changed-note processing chain
    file_detection_ts: str  # When watcher detected file mtime/content changed
    scan_requested_ts: str  # When watcher emitted panel.scan.requested event
    runtime_start_ts: str  # When worker started processing panel.scan.requested
    runtime_complete_ts: str  # When worker completed panel execution

    # Latency milestones (milliseconds)
    watcher_to_scan_ms: int  # Time from file detection to scan event
    scan_to_runtime_start_ms: int  # Time from scan request to worker pickup
    runtime_execution_ms: int  # Wall-clock duration of panel execution
    end_to_end_ms: int  # Total time from file detection to completion

    # Correlation and source attribution
    trace_id: str  # Stable correlation id across chain
    source_watcher: str = "registry"  # Watcher implementation id


class SyncLatencySummaryEvent(BaseModel):
    """Machine-readable latency summary for changed notes (for harness/analysis)."""

    event: str = "sync.latency.summary"
    version: str = "1.0"
    timestamp: str = Field(default_factory=_now_iso)
    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    source: str = "worker"
    payload: SyncLatencySummaryPayload


class SyncChainCorrelationData(BaseModel):
    """Runtime container for tracking latency across the sync chain."""

    trace_id: str
    note_uuid: str
    note_path: str
    file_detection_ts: str  # From scan event payload.mtime or file_stat
    scan_requested_ts: str  # From panel.scan.requested timestamp
    runtime_start_ts: str  # Set when worker starts processing

    def complete(self, *, completion_ts: str) -> SyncLatencySummaryPayload:
        """Generate completed latency summary with computed milestones."""
        file_detect_ms = _ts_to_ms(self.file_detection_ts)
        scan_req_ms = _ts_to_ms(self.scan_requested_ts)
        runtime_start_ms = _ts_to_ms(self.runtime_start_ts)
        runtime_complete_ms = _ts_to_ms(completion_ts)

        return SyncLatencySummaryPayload(
            note_uuid=self.note_uuid,
            note_path=self.note_path,
            file_detection_ts=self.file_detection_ts,
            scan_requested_ts=self.scan_requested_ts,
            runtime_start_ts=self.runtime_start_ts,
            runtime_complete_ts=completion_ts,
            watcher_to_scan_ms=max(0, int(scan_req_ms - file_detect_ms)),
            scan_to_runtime_start_ms=max(0, int(runtime_start_ms - scan_req_ms)),
            runtime_execution_ms=max(0, int(runtime_complete_ms - runtime_start_ms)),
            end_to_end_ms=max(0, int(runtime_complete_ms - file_detect_ms)),
            trace_id=self.trace_id,
        )


__all__ = [
    "SyncLatencySummaryPayload",
    "SyncLatencySummaryEvent",
    "SyncChainCorrelationData",
]
