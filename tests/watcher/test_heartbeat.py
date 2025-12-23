from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.watcher.heartbeat import write_runtime_heartbeat


def test_runtime_heartbeat_writes_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "watcher_heartbeat.json"
    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(target))

    path = write_runtime_heartbeat(ticks=5, changed=2, errors=0)

    assert path == target
    assert target.exists(), "heartbeat file should be created"

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload.get("ticks") == 5
    assert payload.get("changed") == 2
    assert payload.get("errors") == 0
    assert payload.get("status") == "running"
    assert "ts" in payload
    assert "pid" in payload
