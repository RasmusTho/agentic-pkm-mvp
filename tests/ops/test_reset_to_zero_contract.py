from __future__ import annotations

from pathlib import Path


def test_reset_to_zero_clears_watcher_stop_state() -> None:
    script = Path("scripts/reset_to_zero.sh").read_text(encoding="utf-8")
    assert "tmp/WATCHER_STOP" in script
    assert "cleaned tmp/index-outbox* + WATCHER_STOP + heartbeat/health state files" in script

    runbook = Path("docs/runbooks/RUNBOOK_RESET_TO_ZERO.md").read_text(encoding="utf-8")
    assert "tmp/WATCHER_STOP" in runbook
    assert "stale paused-watcher state" in runbook
