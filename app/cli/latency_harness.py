"""Automated multi-device sync latency harness.

Runs a controlled changed-note scenario on the supported local test bootstrap path
and emits machine-readable latency results for each sync-chain stage.

The harness:
1. Seeds or targets a bounded changed-note scenario
2. Waits for the sync/runtime chain to converge
3. Collects machine-readable timing outputs from sync.latency.summary events
4. Emits a per-run latency summary suitable for repeated trials
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from app.events.outbox import read_outbox
from app.events.sync import SyncLatencySummaryEvent
from app.testing.runtime_contract import write_contract_report
from app.watcher.vault_watcher import VaultWatcher, run_watcher_tick
from app.promotion.consumer import consume_promotion_intents


@dataclass
class LatencyResult:
    """A single latency measurement from a changed-note scenario."""

    note_uuid: str
    note_path: str
    file_detection_ts: str
    scan_requested_ts: str
    runtime_start_ts: str
    runtime_complete_ts: str
    watcher_to_scan_ms: int
    scan_to_runtime_start_ms: int
    runtime_execution_ms: int
    end_to_end_ms: int
    trace_id: str


@dataclass
class LatencySummary:
    """Summary of all latency measurements from a harness run."""

    run_id: str
    timestamp: str
    scenario: str
    latency_results: list[LatencyResult]
    transport: str = "test"  # Changed note source transport
    statistics: Dict[str, Any] | None = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to machine-readable JSON-compatible dict."""
        stats = self.statistics or {}
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "scenario": self.scenario,
            "transport": self.transport,
            "latency_count": len(self.latency_results),
            "statistics": stats,
            "measurements": [
                {
                    "note_uuid": r.note_uuid,
                    "note_path": r.note_path,
                    "trace_id": r.trace_id,
                    "timestamps": {
                        "file_detection": r.file_detection_ts,
                        "scan_requested": r.scan_requested_ts,
                        "runtime_start": r.runtime_start_ts,
                        "runtime_complete": r.runtime_complete_ts,
                    },
                    "latencies_ms": {
                        "watcher_to_scan": r.watcher_to_scan_ms,
                        "scan_to_runtime_start": r.scan_to_runtime_start_ms,
                        "runtime_execution": r.runtime_execution_ms,
                        "end_to_end": r.end_to_end_ms,
                    },
                }
                for r in self.latency_results
            ],
        }

    def to_lines(self) -> list[str]:
        """Convert to human-readable output lines."""
        lines = [
            f"Latency Harness Run: {self.run_id}",
            f"Timestamp: {self.timestamp}",
            f"Scenario: {self.scenario}",
            f"Transport: {self.transport}",
            f"Latency measurements captured: {len(self.latency_results)}",
        ]

        if self.statistics:
            lines.append("")
            lines.append("Latency Statistics:")
            for key, value in self.statistics.items():
                lines.append(f"  {key}: {value}")

        if self.latency_results:
            lines.append("")
            lines.append("Per-note latencies (milliseconds):")
            for r in self.latency_results:
                lines.append(f"  {r.note_uuid} ({r.note_path})")
                lines.append(f"    watcher→scan: {r.watcher_to_scan_ms}ms")
                lines.append(f"    scan→runtime: {r.scan_to_runtime_start_ms}ms")
                lines.append(f"    runtime execution: {r.runtime_execution_ms}ms")
                lines.append(f"    end-to-end: {r.end_to_end_ms}ms")

        return lines


def _extract_sync_latency_events(outbox_path: Path) -> list[Dict[str, Any]]:
    """Extract sync.latency.summary events from the outbox."""
    events = read_outbox(outbox_path)
    latency_events = [
        e for e in events if e.get("event") == "sync.latency.summary"
    ]
    return latency_events


def _parse_latency_event(event: Dict[str, Any]) -> LatencyResult | None:
    """Parse a sync.latency.summary event into a LatencyResult."""
    try:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return None

        # Ensure we have at least the minimal required fields
        if not payload.get("note_uuid"):
            return None

        return LatencyResult(
            note_uuid=str(payload.get("note_uuid", "")),
            note_path=str(payload.get("note_path", "")),
            file_detection_ts=str(payload.get("file_detection_ts", "")),
            scan_requested_ts=str(payload.get("scan_requested_ts", "")),
            runtime_start_ts=str(payload.get("runtime_start_ts", "")),
            runtime_complete_ts=str(payload.get("runtime_complete_ts", "")),
            watcher_to_scan_ms=int(payload.get("watcher_to_scan_ms", 0)),
            scan_to_runtime_start_ms=int(payload.get("scan_to_runtime_start_ms", 0)),
            runtime_execution_ms=int(payload.get("runtime_execution_ms", 0)),
            end_to_end_ms=int(payload.get("end_to_end_ms", 0)),
            trace_id=str(event.get("trace_id", "")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _compute_statistics(results: list[LatencyResult]) -> Dict[str, Any]:
    """Compute aggregate latency statistics from a list of results."""
    if not results:
        return {}

    e2e_latencies = [r.end_to_end_ms for r in results]
    watcher_latencies = [r.watcher_to_scan_ms for r in results]
    scan_latencies = [r.scan_to_runtime_start_ms for r in results]
    runtime_latencies = [r.runtime_execution_ms for r in results]

    def _stats(values: list[int]) -> Dict[str, int]:
        if not values:
            return {}
        return {
            "min": min(values),
            "max": max(values),
            "mean": sum(values) // len(values),
        }

    return {
        "end_to_end_ms": _stats(e2e_latencies),
        "watcher_to_scan_ms": _stats(watcher_latencies),
        "scan_to_runtime_start_ms": _stats(scan_latencies),
        "runtime_execution_ms": _stats(runtime_latencies),
    }


def run_latency_harness(
    *,
    vault_root: Path,
    target_subdir: str = "Test",
    folder: str = "AgenticPKM-UAT",
    scenario: str = "changed-note-default",
    outbox_path: Path | None = None,
    report_path: Path | None = None,
    dry_run: bool = False,
) -> LatencySummary:
    """Run an automated latency harness against a changed-note scenario.

    Args:
        vault_root: Root path of the vault
        target_subdir: Vault subdirectory to watch
        folder: Folder name containing test notes
        scenario: Name of the scenario being measured
        outbox_path: Path to the event outbox (defaults to INDEX_OUTBOX_PATH)
        report_path: Optional path to write JSON report
        dry_run: If True, don't run the watcher/panel flow

    Returns:
        LatencySummary with all captured latency measurements
    """
    resolved_root = vault_root.expanduser().resolve()
    scenario_path = resolved_root / target_subdir / folder

    if not scenario_path.exists():
        raise FileNotFoundError(f"Scenario folder not found: {scenario_path}")

    if outbox_path is None:
        outbox_path = Path(os.getenv("INDEX_OUTBOX_PATH", "index-outbox.jsonl"))

    outbox_path = outbox_path.expanduser().resolve()

    # Record the initial event count to find new latency events
    initial_events = read_outbox(outbox_path)
    initial_count = len(initial_events)

    # Run the watcher/panel flow to generate changed-note events
    snapshot_path = scenario_path / ".agentic-pkm" / "latency_harness_snapshot.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    original_scope = os.environ.get("WATCHER_SCOPE_GLOB")
    os.environ["WATCHER_SCOPE_GLOB"] = f"{target_subdir}/{folder}/*.md,{target_subdir}/{folder}/**/*.md"

    try:
        if not dry_run:
            # Run watcher with panel execution to generate sync.latency.summary events
            watcher_summary, watcher_messages = run_watcher_tick(
                vault_root=resolved_root,
                snapshot_path=snapshot_path,
                skip_panel=False,  # Enable panel to generate latency events
                emit_only=False,
                dry_run=False,
                max_notes=50,
                force=True,  # Force re-evaluation to capture latency
                outbox_path=outbox_path,
            )

            for msg in watcher_messages:
                print(msg)

            # Consume promotions to ensure full pipeline execution
            consume_promotion_intents(outbox_path=outbox_path)
            VaultWatcher(resolved_root, snapshot_path=snapshot_path).refresh_snapshot()
    finally:
        if original_scope is None:
            os.environ.pop("WATCHER_SCOPE_GLOB", None)
        else:
            os.environ["WATCHER_SCOPE_GLOB"] = original_scope

    # Extract latency events from the outbox
    all_events = read_outbox(outbox_path)
    new_events = all_events[initial_count:] if initial_count < len(all_events) else all_events

    latency_events = _extract_sync_latency_events(outbox_path)
    latency_results = [
        result
        for event in latency_events
        if (result := _parse_latency_event(event)) is not None
    ]

    # Create the summary
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    timestamp = datetime.utcnow().isoformat() + "Z"
    statistics = _compute_statistics(latency_results)

    summary = LatencySummary(
        run_id=run_id,
        timestamp=timestamp,
        scenario=scenario,
        latency_results=latency_results,
        statistics=statistics if latency_results else None,
    )

    # Write JSON report if requested
    if report_path:
        report_path = report_path.expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_data = summary.to_dict()
        write_contract_report(report_path, report_data)

    return summary


__all__ = [
    "run_latency_harness",
    "LatencySummary",
    "LatencyResult",
]
