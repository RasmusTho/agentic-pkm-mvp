"""Tests for watcher scan event timestamp emission."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.watcher.watcher import _emit_scan_event


class TestWatcherScanEventTimestamps:
    """Test that watcher emits timestamps for latency tracking."""

    def test_emit_scan_event_includes_mtime_iso(self, tmp_path: Path) -> None:
        """panel.scan.requested event includes mtime_iso field."""
        outbox_path = tmp_path / "outbox.jsonl"
        vault_root = tmp_path / "vault"
        vault_root.mkdir()

        rel_path = Path("Notes/test.md")

        # Use a fixed mtime for reproducibility
        mtime = 1700000000.0

        trace_id = _emit_scan_event(
            outbox_path=outbox_path,
            vault_root=vault_root,
            rel_path=rel_path,
            mtime=mtime,
            content_hash="abc123",
        )

        # Read the emitted event
        assert outbox_path.exists()
        with outbox_path.open("r") as f:
            event_line = f.read().strip()

        event = json.loads(event_line)

        # Verify structure
        assert event["event"] == "panel.scan.requested"
        assert event["trace_id"] == trace_id
        assert "timestamp" in event
        assert "payload" in event

        # Verify mtime_iso field is present in payload
        payload = event["payload"]
        assert "mtime" in payload
        assert "mtime_iso" in payload
        assert payload["mtime"] == mtime
        assert isinstance(payload["mtime_iso"], str)

        # Verify mtime_iso is a valid ISO timestamp
        try:
            # Should be able to parse as ISO 8601
            if payload["mtime_iso"].endswith("Z"):
                dt = datetime.fromisoformat(payload["mtime_iso"].rstrip("Z") + "+00:00")
            else:
                dt = datetime.fromisoformat(payload["mtime_iso"])
            assert dt is not None
        except ValueError:
            pytest.fail(f"mtime_iso '{payload['mtime_iso']}' is not valid ISO 8601")

    def test_mtime_iso_matches_mtime_value(self, tmp_path: Path) -> None:
        """mtime_iso represents the same time as mtime float."""
        outbox_path = tmp_path / "outbox.jsonl"
        vault_root = tmp_path / "vault"
        vault_root.mkdir()

        mtime = 1700000000.0
        _emit_scan_event(
            outbox_path=outbox_path,
            vault_root=vault_root,
            rel_path=Path("test.md"),
            mtime=mtime,
            content_hash="abc123",
        )

        with outbox_path.open("r") as f:
            event = json.loads(f.read())

        payload = event["payload"]
        mtime_float = payload["mtime"]
        mtime_iso = payload["mtime_iso"]

        # Parse the ISO timestamp back to seconds
        iso_str = mtime_iso.rstrip("Z")
        dt = datetime.fromisoformat(iso_str + "+00:00")
        iso_timestamp = dt.timestamp()

        # Should be the same (within 1 second due to rounding)
        assert abs(iso_timestamp - mtime_float) < 1.0

    def test_scan_event_has_all_required_fields(self, tmp_path: Path) -> None:
        """panel.scan.requested event contains all required fields for latency tracking."""
        outbox_path = tmp_path / "outbox.jsonl"
        vault_root = tmp_path / "vault"
        vault_root.mkdir()

        _emit_scan_event(
            outbox_path=outbox_path,
            vault_root=vault_root,
            rel_path=Path("test.md"),
            mtime=1700000000.0,
            content_hash="abc123",
        )

        with outbox_path.open("r") as f:
            event = json.loads(f.read())

        # Top-level event fields
        assert "event" in event
        assert "event_id" in event
        assert "trace_id" in event
        assert "timestamp" in event
        assert "source" in event
        assert "payload" in event

        # Payload fields for latency tracking
        payload = event["payload"]
        assert "vault_path" in payload
        assert "relative_path" in payload
        assert "mtime" in payload
        assert "mtime_iso" in payload
        assert "hash" in payload
