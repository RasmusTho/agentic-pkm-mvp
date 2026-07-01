"""Tests for GitHub API call structured logging and kill switch.

AC1: Every GitHub call emits a structured record with op, read/write,
     remaining, reset, status, retry, latency.
AC2: When remaining < threshold, the kill switch disables scan and
     non-essential reconcile.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.dispatcher.github_call_logger import (
    get_last_known_remaining,
    is_kill_switch_active,
    log_github_call,
)
from app.dispatcher.sync_github import (
    PullSyncAdapter,
    GhCliIssueSource,
    get_sync_meta,
)


# ---------------------------------------------------------------------------
# AC1 — test_each_gh_call_emits_structured_record
# ---------------------------------------------------------------------------

class TestEachGhCallEmitsStructuredRecord:
    """Every GitHub call emits a structured record with required fields."""

    def test_log_github_call_writes_jsonl_record(self, tmp_path: Path) -> None:
        log_file = tmp_path / "github_api_calls.jsonl"
        with patch.dict(os.environ, {"GITHUB_CALL_LOG_PATH": str(log_file)}):
            log_github_call(
                operation="gh issue list --label agent:ready",
                direction="read",
                status=200,
                remaining=450,
                reset="2026-07-01T12:00:00Z",
                retry_count=0,
                latency_ms=123.4,
            )

        assert log_file.exists(), "log file must be created"
        records = [json.loads(line) for line in log_file.read_text().splitlines() if line.strip()]
        assert len(records) == 1
        rec = records[0]

        # Required fields per AC1
        assert rec["schema"] == "github_call/v1"
        assert rec["operation"] == "gh issue list --label agent:ready"
        assert rec["direction"] == "read"
        assert rec["remaining"] == 450
        assert rec["reset"] == "2026-07-01T12:00:00Z"
        assert rec["retry_count"] == 0
        assert rec["latency_ms"] == pytest.approx(123.4)
        assert "timestamp" in rec

    def test_log_github_call_write_direction(self, tmp_path: Path) -> None:
        log_file = tmp_path / "calls.jsonl"
        with patch.dict(os.environ, {"GITHUB_CALL_LOG_PATH": str(log_file)}):
            log_github_call(
                operation="gh issue edit --add-label",
                direction="write",
                status=200,
                remaining=499,
            )
        records = [json.loads(l) for l in log_file.read_text().splitlines()]
        assert records[0]["direction"] == "write"

    def test_log_github_call_captures_error(self, tmp_path: Path) -> None:
        log_file = tmp_path / "calls.jsonl"
        with patch.dict(os.environ, {"GITHUB_CALL_LOG_PATH": str(log_file)}):
            log_github_call(
                operation="gh issue list",
                direction="read",
                error="connection refused",
            )
        records = [json.loads(l) for l in log_file.read_text().splitlines()]
        assert records[0]["error"] == "connection refused"

    def test_pull_adapter_emits_log_records_during_pull(self, tmp_path: Path) -> None:
        """PullSyncAdapter.pull() emits structured records for each gh call."""
        log_file = tmp_path / "gh_calls.jsonl"

        mock_store = MagicMock()
        mock_store.get_task.return_value = None
        mock_store.list_tasks.return_value = []

        mock_source = MagicMock()
        mock_source.get_rate_limit.return_value = {"remaining": 800, "reset": "2026-07-01T13:00:00Z"}
        mock_source.list_issues.return_value = []
        mock_source.list_open_issues.return_value = []

        adapter = PullSyncAdapter(store=mock_store, source=mock_source)

        with patch.dict(os.environ, {"GITHUB_CALL_LOG_PATH": str(log_file)}):
            adapter.pull("owner/repo")

        assert log_file.exists(), "log file must be created after pull"
        records = [json.loads(l) for l in log_file.read_text().splitlines() if l.strip()]
        assert len(records) >= 2, "expected at least rate_limit + list_issues calls"
        ops = [r["operation"] for r in records]
        assert any("rate_limit" in op for op in ops)
        assert any("agent:ready" in op or "list_issues" in op.lower() or "issue list" in op for op in ops)


# ---------------------------------------------------------------------------
# AC2 — test_kill_switch_disables_scan_below_threshold
# ---------------------------------------------------------------------------

class TestKillSwitchDisablesScanBelowThreshold:
    """When remaining < threshold, expensive scans are skipped."""

    def test_is_kill_switch_active_below_threshold(self) -> None:
        with patch.dict(os.environ, {"GITHUB_RATELIMIT_KILL_THRESHOLD": "200"}):
            assert is_kill_switch_active(199) is True
            assert is_kill_switch_active(0) is True

    def test_is_kill_switch_inactive_above_threshold(self) -> None:
        with patch.dict(os.environ, {"GITHUB_RATELIMIT_KILL_THRESHOLD": "200"}):
            assert is_kill_switch_active(200) is False
            assert is_kill_switch_active(5000) is False

    def test_is_kill_switch_inactive_when_remaining_unknown(self) -> None:
        # Fails safe: unknown remaining → allow essential reads
        assert is_kill_switch_active(None) is False

    def test_kill_switch_skips_open_issues_scan(self, tmp_path: Path) -> None:
        """When kill switch is active, list_open_issues must NOT be called."""
        log_file = tmp_path / "gh_calls.jsonl"

        mock_store = MagicMock()
        mock_store.get_task.return_value = None
        mock_store.list_tasks.return_value = []

        mock_source = MagicMock()
        # remaining=50 → below default threshold of 200 → kill switch active
        mock_source.get_rate_limit.return_value = {"remaining": 50, "reset": "2026-07-01T13:00:00Z"}
        mock_source.list_issues.return_value = []
        mock_source.list_open_issues.return_value = []

        adapter = PullSyncAdapter(store=mock_store, source=mock_source)

        with patch.dict(os.environ, {
            "GITHUB_CALL_LOG_PATH": str(log_file),
            "GITHUB_RATELIMIT_KILL_THRESHOLD": "200",
        }):
            adapter.pull("owner/repo")

        # The expensive open-issues scan must be skipped
        mock_source.list_open_issues.assert_not_called()

    def test_kill_switch_still_allows_essential_read(self, tmp_path: Path) -> None:
        """Even when kill switch active, agent:ready list_issues still runs."""
        log_file = tmp_path / "gh_calls.jsonl"

        mock_store = MagicMock()
        mock_store.get_task.return_value = None
        mock_store.list_tasks.return_value = []

        mock_source = MagicMock()
        mock_source.get_rate_limit.return_value = {"remaining": 10}
        mock_source.list_issues.return_value = []

        adapter = PullSyncAdapter(store=mock_store, source=mock_source)

        with patch.dict(os.environ, {
            "GITHUB_CALL_LOG_PATH": str(log_file),
            "GITHUB_RATELIMIT_KILL_THRESHOLD": "200",
        }):
            result = adapter.pull("owner/repo")

        # Essential read was performed
        mock_source.list_issues.assert_called_once()
        # No error path taken
        assert result == []  # empty repo is fine

    def test_kill_switch_flag_recorded_in_sync_meta(self, tmp_path: Path) -> None:
        """kill_switch_active is recorded in the sync-meta extra blob."""
        log_file = tmp_path / "gh_calls.jsonl"

        captured_extra: dict[str, Any] = {}

        def fake_record_sync_success(store, provider, pull_at, *, rate_limit_remaining=None,
                                     rate_limit_reset=None, extra=None):
            captured_extra.update(extra or {})

        mock_store = MagicMock()
        mock_store.get_task.return_value = None
        mock_store.list_tasks.return_value = []

        mock_source = MagicMock()
        mock_source.get_rate_limit.return_value = {"remaining": 50}
        mock_source.list_issues.return_value = []

        adapter = PullSyncAdapter(store=mock_store, source=mock_source)

        with patch.dict(os.environ, {
            "GITHUB_CALL_LOG_PATH": str(log_file),
            "GITHUB_RATELIMIT_KILL_THRESHOLD": "200",
        }), patch(
            "app.dispatcher.sync_github.record_sync_success",
            side_effect=fake_record_sync_success,
        ):
            adapter.pull("owner/repo")

        assert captured_extra.get("kill_switch_active") is True

    def test_get_last_known_remaining_from_sync_meta(self) -> None:
        meta = {
            "last_pull_at": "2026-07-01T00:00:00Z",
            "sync_result": "ok",
            "extra": {"rate_limit_remaining": 300, "reconciled_count": 5},
        }
        assert get_last_known_remaining(meta) == 300

    def test_get_last_known_remaining_none_on_missing(self) -> None:
        assert get_last_known_remaining(None) is None
        assert get_last_known_remaining({}) is None
