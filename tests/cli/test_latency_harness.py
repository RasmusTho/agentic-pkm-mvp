"""Tests for the automated multi-device sync latency harness.

Tests the latency event extraction, parsing, and summary generation
for the sync chain latency measurement harness.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
import tempfile

import pytest

from app.cli.latency_harness import (
    LatencyResult,
    LatencySummary,
    _extract_sync_latency_events,
    _parse_latency_event,
    _compute_statistics,
    _run_watcher_tick_with_timeout,
    run_latency_harness,
    LatencyHarnessTimeoutError,
)


@pytest.fixture
def sample_latency_event() -> Dict[str, Any]:
    """Create a sample sync.latency.summary event."""
    return {
        "event": "sync.latency.summary",
        "version": "1.0",
        "timestamp": "2026-04-08T10:30:45Z",
        "trace_id": "trace-001",
        "event_id": "event-001",
        "source": "worker",
        "payload": {
            "note_uuid": "note-uuid-001",
            "note_path": "Test/Folder/note.md",
            "file_detection_ts": "2026-04-08T10:30:00Z",
            "scan_requested_ts": "2026-04-08T10:30:02Z",
            "runtime_start_ts": "2026-04-08T10:30:03Z",
            "runtime_complete_ts": "2026-04-08T10:30:05Z",
            "watcher_to_scan_ms": 2000,
            "scan_to_runtime_start_ms": 1000,
            "runtime_execution_ms": 2000,
            "end_to_end_ms": 5000,
            "trace_id": "trace-001",
            "source_watcher": "registry",
        },
    }


@pytest.fixture
def sample_mixed_events(sample_latency_event: Dict[str, Any]) -> list[Dict[str, Any]]:
    """Create a mixed list of events including latency events."""
    return [
        {
            "event": "ingest.vault.changed",
            "timestamp": "2026-04-08T10:30:01Z",
            "trace_id": "trace-001",
        },
        sample_latency_event,
        {
            "event": "promotion.project.done",
            "timestamp": "2026-04-08T10:30:06Z",
            "trace_id": "trace-001",
        },
    ]


class TestLatencyEventParsing:
    """Test parsing of latency events."""

    def test_parse_valid_latency_event(self, sample_latency_event: Dict[str, Any]) -> None:
        """Parse a valid sync.latency.summary event."""
        result = _parse_latency_event(sample_latency_event)
        assert result is not None
        assert result.note_uuid == "note-uuid-001"
        assert result.note_path == "Test/Folder/note.md"
        assert result.end_to_end_ms == 5000
        assert result.trace_id == "trace-001"

    def test_parse_missing_payload(self) -> None:
        """Handle events with missing payload."""
        event = {
            "event": "sync.latency.summary",
            "trace_id": "trace-001",
        }
        result = _parse_latency_event(event)
        assert result is None

    def test_parse_invalid_payload_type(self) -> None:
        """Handle events with non-dict payload."""
        event = {
            "event": "sync.latency.summary",
            "trace_id": "trace-001",
            "payload": "not a dict",
        }
        result = _parse_latency_event(event)
        assert result is None

    def test_parse_missing_required_fields(self) -> None:
        """Handle events with missing required fields."""
        event = {
            "event": "sync.latency.summary",
            "trace_id": "trace-001",
            "payload": {
                "note_uuid": "note-001",
                # Missing other required fields
            },
        }
        result = _parse_latency_event(event)
        # Should still create a result with defaults
        assert result is not None
        assert result.note_uuid == "note-001"


class TestEventExtraction:
    """Test extraction of latency events from mixed event lists."""

    def test_extract_latency_events_from_mixed(self, sample_mixed_events: list[Dict[str, Any]]) -> None:
        """Extract only latency events from mixed event stream."""
        with tempfile.TemporaryDirectory() as tmpdir:
            outbox_path = Path(tmpdir) / "outbox.jsonl"
            outbox_path.write_text(
                "\n".join(json.dumps(e) for e in sample_mixed_events),
                encoding="utf-8",
            )

            latency_events = _extract_sync_latency_events(outbox_path)
            assert len(latency_events) == 1
            assert latency_events[0]["event"] == "sync.latency.summary"
            assert latency_events[0]["trace_id"] == "trace-001"

    def test_extract_from_empty_outbox(self) -> None:
        """Handle extraction from empty or missing outbox."""
        with tempfile.TemporaryDirectory() as tmpdir:
            outbox_path = Path(tmpdir) / "outbox.jsonl"
            latency_events = _extract_sync_latency_events(outbox_path)
            assert latency_events == []


class TestStatisticsComputation:
    """Test computation of latency statistics."""

    def test_compute_statistics_single_result(self) -> None:
        """Compute statistics from a single latency measurement."""
        result = LatencyResult(
            note_uuid="note-001",
            note_path="path",
            file_detection_ts="2026-04-08T10:30:00Z",
            scan_requested_ts="2026-04-08T10:30:02Z",
            runtime_start_ts="2026-04-08T10:30:03Z",
            runtime_complete_ts="2026-04-08T10:30:05Z",
            watcher_to_scan_ms=2000,
            scan_to_runtime_start_ms=1000,
            runtime_execution_ms=2000,
            end_to_end_ms=5000,
            trace_id="trace-001",
        )

        stats = _compute_statistics([result])
        assert stats["end_to_end_ms"]["min"] == 5000
        assert stats["end_to_end_ms"]["max"] == 5000
        assert stats["end_to_end_ms"]["mean"] == 5000

    def test_compute_statistics_multiple_results(self) -> None:
        """Compute statistics from multiple latency measurements."""
        results = [
            LatencyResult(
                note_uuid=f"note-{i}",
                note_path=f"path-{i}",
                file_detection_ts="2026-04-08T10:30:00Z",
                scan_requested_ts="2026-04-08T10:30:02Z",
                runtime_start_ts="2026-04-08T10:30:03Z",
                runtime_complete_ts="2026-04-08T10:30:05Z",
                watcher_to_scan_ms=2000,
                scan_to_runtime_start_ms=1000,
                runtime_execution_ms=2000,
                end_to_end_ms=5000 + i * 1000,  # Vary latencies
                trace_id=f"trace-{i}",
            )
            for i in range(3)
        ]

        stats = _compute_statistics(results)
        e2e = stats["end_to_end_ms"]
        assert e2e["min"] == 5000
        assert e2e["max"] == 7000
        assert e2e["mean"] == 6000  # (5000 + 6000 + 7000) / 3 = 6000


class TestLatencySummary:
    """Test latency summary generation."""

    def test_summary_to_dict(self) -> None:
        """Convert summary to machine-readable JSON dict."""
        result = LatencyResult(
            note_uuid="note-001",
            note_path="Test/note.md",
            file_detection_ts="2026-04-08T10:30:00Z",
            scan_requested_ts="2026-04-08T10:30:02Z",
            runtime_start_ts="2026-04-08T10:30:03Z",
            runtime_complete_ts="2026-04-08T10:30:05Z",
            watcher_to_scan_ms=2000,
            scan_to_runtime_start_ms=1000,
            runtime_execution_ms=2000,
            end_to_end_ms=5000,
            trace_id="trace-001",
        )

        summary = LatencySummary(
            run_id="run-20260408-103000",
            timestamp="2026-04-08T10:30:00Z",
            scenario="test-scenario",
            latency_results=[result],
            statistics={"end_to_end_ms": {"min": 5000, "max": 5000, "mean": 5000}},
        )

        data = summary.to_dict()
        assert data["run_id"] == "run-20260408-103000"
        assert data["scenario"] == "test-scenario"
        assert data["latency_count"] == 1
        assert len(data["measurements"]) == 1
        assert data["measurements"][0]["note_uuid"] == "note-001"
        assert data["measurements"][0]["latencies_ms"]["end_to_end"] == 5000

    def test_summary_to_lines(self) -> None:
        """Convert summary to human-readable lines."""
        result = LatencyResult(
            note_uuid="note-001",
            note_path="Test/note.md",
            file_detection_ts="2026-04-08T10:30:00Z",
            scan_requested_ts="2026-04-08T10:30:02Z",
            runtime_start_ts="2026-04-08T10:30:03Z",
            runtime_complete_ts="2026-04-08T10:30:05Z",
            watcher_to_scan_ms=2000,
            scan_to_runtime_start_ms=1000,
            runtime_execution_ms=2000,
            end_to_end_ms=5000,
            trace_id="trace-001",
        )

        summary = LatencySummary(
            run_id="run-001",
            timestamp="2026-04-08T10:30:00Z",
            scenario="test-scenario",
            latency_results=[result],
        )

        lines = summary.to_lines()
        assert any("Latency Harness Run" in line for line in lines)
        assert any("test-scenario" in line for line in lines)
        assert any("1" in line for line in lines)  # 1 measurement


class TestLatencyHarnessExecution:
    """Test bounded execution and provider-free harness mode."""

    def test_run_watcher_tick_with_timeout_drains_result_queue_before_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FakeProcess:
            def __init__(self) -> None:
                self.exitcode = 0
                self._alive = True

            def start(self) -> None:
                return None

            def join(self, timeout: float | None = None) -> None:
                return None

            def is_alive(self) -> bool:
                return self._alive

            def terminate(self) -> None:
                self._alive = False

        class FakeQueue:
            def __init__(self, proc: FakeProcess) -> None:
                self.proc = proc
                self._result = ("ok", ({"changed": 1}, ["watcher ok"]))

            def get(self, timeout: float | None = None) -> tuple[str, tuple[Dict[str, Any], list[str]]]:
                self.proc._alive = False
                return self._result

            def get_nowait(self) -> tuple[str, tuple[Dict[str, Any], list[str]]]:
                return self.get()

        class FakeContext:
            def __init__(self) -> None:
                self.proc = FakeProcess()

            def Queue(self) -> FakeQueue:
                return FakeQueue(self.proc)

            def Process(self, target: Any, args: tuple[Any, ...]) -> FakeProcess:
                return self.proc

        fake_ctx = FakeContext()
        monkeypatch.setattr("app.cli.latency_harness.mp.get_context", lambda method: fake_ctx)

        watcher_summary, watcher_messages = _run_watcher_tick_with_timeout(
            1,
            vault_root=Path("/tmp/vault"),
            snapshot_path=Path("/tmp/snapshot.json"),
        )

        assert watcher_summary == {"changed": 1}
        assert watcher_messages == ["watcher ok"]
        assert fake_ctx.proc.is_alive() is False

    def test_run_latency_harness_uses_provider_free_rule_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        vault_root = tmp_path / "vault"
        scenario_path = vault_root / "Test" / "AgenticPKM-UAT-2026-03-19"
        scenario_path.mkdir(parents=True)
        outbox_path = tmp_path / "outbox.jsonl"
        progress_lines: list[str] = []

        event = {
            "event": "sync.latency.summary",
            "trace_id": "trace-123",
            "payload": {
                "note_uuid": "note-123",
                "note_path": "Test/AgenticPKM-UAT-2026-03-19/note.md",
                "file_detection_ts": "2026-04-08T10:30:00Z",
                "scan_requested_ts": "2026-04-08T10:30:01Z",
                "runtime_start_ts": "2026-04-08T10:30:02Z",
                "runtime_complete_ts": "2026-04-08T10:30:04Z",
                "watcher_to_scan_ms": 1000,
                "scan_to_runtime_start_ms": 1000,
                "runtime_execution_ms": 2000,
                "end_to_end_ms": 4000,
            },
        }

        state = {"calls": 0}

        def fake_read_outbox(path: Path) -> list[Dict[str, Any]]:
            assert path == outbox_path.resolve()
            state["calls"] += 1
            return [] if state["calls"] == 1 else [event]

        def fake_run_watcher_tick_with_timeout(timeout_seconds: int, **kwargs: Any) -> tuple[Dict[str, Any], list[str]]:
            assert timeout_seconds == 30
            assert os.environ["PANEL_AGENT_DECIDER"] == "rule"
            return {"changed": 1, "panel_runs": 1, "errors": 0}, ["watcher ok"]

        class DummyWatcher:
            def __init__(self, vault_root: Path, snapshot_path: Path | None = None) -> None:
                self.vault_root = vault_root
                self.snapshot_path = snapshot_path

            def refresh_snapshot(self) -> None:
                progress_lines.append("snapshot refreshed")

        monkeypatch.setattr("app.cli.latency_harness.read_outbox", fake_read_outbox)
        monkeypatch.setattr(
            "app.cli.latency_harness._run_watcher_tick_with_timeout",
            fake_run_watcher_tick_with_timeout,
        )
        monkeypatch.setattr("app.cli.latency_harness.consume_promotion_intents", lambda outbox_path: None)
        monkeypatch.setattr("app.cli.latency_harness.VaultWatcher", DummyWatcher)

        summary = run_latency_harness(
            vault_root=vault_root,
            folder="AgenticPKM-UAT-2026-03-19",
            outbox_path=outbox_path,
            panel_decider="rule",
            timeout_seconds=30,
            progress=progress_lines.append,
        )

        assert summary.execution_mode == "panel-rule"
        assert summary.latency_results
        assert summary.latency_results[0].note_uuid == "note-123"
        assert any("panel_decider=rule" in line for line in progress_lines)

    def test_run_latency_harness_timeout_writes_empty_report(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        vault_root = tmp_path / "vault"
        scenario_path = vault_root / "Test" / "AgenticPKM-UAT-2026-03-19"
        scenario_path.mkdir(parents=True)
        outbox_path = tmp_path / "outbox.jsonl"
        report_path = tmp_path / "report.json"

        monkeypatch.setattr("app.cli.latency_harness.read_outbox", lambda path: [])
        monkeypatch.setattr(
            "app.cli.latency_harness._run_watcher_tick_with_timeout",
            lambda timeout_seconds, **kwargs: (_ for _ in ()).throw(
                LatencyHarnessTimeoutError("Timed out after 3s while waiting for watcher/panel convergence.")
            ),
        )

        with pytest.raises(LatencyHarnessTimeoutError):
            run_latency_harness(
                vault_root=vault_root,
                folder="AgenticPKM-UAT-2026-03-19",
                outbox_path=outbox_path,
                report_path=report_path,
                timeout_seconds=3,
                progress=lambda _: None,
            )

        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["execution_mode"] == "panel-rule"
        assert report["latency_count"] == 0
        assert any("timeout_seconds=3" in warning for warning in report["warnings"])
