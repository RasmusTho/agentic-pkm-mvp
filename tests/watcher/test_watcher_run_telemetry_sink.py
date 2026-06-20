"""Tests for #2253: watcher.run telemetry must route to a dedicated log, never index-outbox.jsonl.

AC1: watcher.run events are NOT written to index-outbox.jsonl.
AC2: The dedicated telemetry sink is size-bounded / rotated.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.watcher.events import emit_watcher_run_event

pytestmark = pytest.mark.not_pg

_MINIMAL_SUMMARY: dict = {
    "changed": 0,
    "ingest_attempted": 0,
    "ingested": 0,
    "panel_candidates": 0,
    "panel_runs": 0,
    "panel_promotions": 0,
    "panel_skipped_policy": 0,
    "panel_skipped_limit": 0,
    "errors": 0,
    "dry_run": False,
    "limit_exceeded": False,
    "snapshot_path": "",
}


def _emit_one(telemetry_log: Path, vault_root: Path) -> None:
    emit_watcher_run_event(
        _MINIMAL_SUMMARY,
        vault_root=vault_root,
        snapshot_path=None,
        telemetry_log_path=telemetry_log,
        trigger="test",
    )


def test_watcher_run_not_written_to_index_outbox(tmp_path: Path) -> None:
    """AC1: emit_watcher_run_event writes to telemetry_log_path, NOT index-outbox."""
    index_outbox = tmp_path / "index-outbox.jsonl"
    telemetry_log = tmp_path / "watcher_run.jsonl"
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    _emit_one(telemetry_log, vault_root)

    # Telemetry log must exist and contain the watcher.run record.
    assert telemetry_log.exists(), "telemetry log must be created"
    lines = [ln for ln in telemetry_log.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record.get("event") == "watcher.run"

    # index-outbox must NOT be touched.
    assert not index_outbox.exists(), (
        "emit_watcher_run_event must never write to index-outbox.jsonl; "
        "found content in index-outbox"
    )


def test_watcher_run_log_is_size_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC2: When the telemetry log exceeds the size limit it is rotated (not grown unboundedly)."""
    telemetry_log = tmp_path / "watcher_run.jsonl"
    backup = tmp_path / "watcher_run.jsonl.1"
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    # Lower the rotation threshold so we can trigger it cheaply.
    small_limit = 50  # bytes — one watcher.run JSON line is ~400 bytes, so any write triggers rotation
    monkeypatch.setenv("WATCHER_RUN_LOG_MAX_BYTES", str(small_limit))

    # First write: file starts empty, no rotation yet.
    _emit_one(telemetry_log, vault_root)
    assert telemetry_log.exists()
    first_content = telemetry_log.read_text()

    # Second write: file now exceeds limit, rotation must occur before appending.
    _emit_one(telemetry_log, vault_root)

    # After rotation the backup must exist and the active log contains only the new record.
    assert backup.exists(), "backup watcher_run.jsonl.1 must exist after rotation"
    assert backup.read_text() == first_content, "backup must contain the pre-rotation content"

    active_lines = [ln for ln in telemetry_log.read_text().splitlines() if ln.strip()]
    assert len(active_lines) == 1, (
        "active telemetry log must contain only the post-rotation record, not unbounded accumulation"
    )
    record = json.loads(active_lines[0])
    assert record.get("event") == "watcher.run"
