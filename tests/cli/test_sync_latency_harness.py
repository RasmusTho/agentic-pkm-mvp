from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from app.cli.latency_harness import run_latency_harness


pytestmark = pytest.mark.not_pg


def test_harness_records_measurement_when_summary_action_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    scenario_path = vault_root / "Test" / "AgenticPKM-UAT-2026-03-19"
    scenario_path.mkdir(parents=True)
    outbox_path = tmp_path / "outbox.jsonl"
    progress_lines: list[str] = []
    state = {"calls": 0}

    event = {
        "event": "sync.latency.summary",
        "trace_id": "trace-summary-001",
        "payload": {
            "note_uuid": "summary-note-001",
            "note_path": "Test/AgenticPKM-UAT-2026-03-19/summary.md",
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

    def fake_read_outbox(path: Path) -> list[dict[str, Any]]:
        assert path == outbox_path.resolve()
        state["calls"] += 1
        return [] if state["calls"] == 1 else [event]

    def fake_run_watcher_tick_with_timeout(timeout_seconds: int, **kwargs: Any) -> tuple[dict[str, Any], list[str]]:
        assert timeout_seconds == 30
        assert os.environ["WATCHER_MEASUREMENT_MODE"] == "1"
        return {"changed": 1, "panel_runs": 1, "errors": 0}, ["watcher ok"]

    class DummyWatcher:
        def __init__(self, vault_root: Path, snapshot_path: Path | None = None) -> None:
            self.vault_root = vault_root
            self.snapshot_path = snapshot_path

        def refresh_snapshot(self) -> None:
            progress_lines.append("snapshot refreshed")

    monkeypatch.delenv("WATCHER_MEASUREMENT_MODE", raising=False)
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

    assert summary.latency_results
    assert summary.latency_results[0].note_uuid == "summary-note-001"
    assert "WATCHER_MEASUREMENT_MODE" not in os.environ
