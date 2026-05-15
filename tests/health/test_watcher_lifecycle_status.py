from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.cli.health import run_health


def _write_registry_heartbeat(path: Path, *, watchers: dict, now: float | None = None) -> None:
    ts = now if now is not None else time.time()
    payload = {
        "ts": ts,
        "pid": 12345,
        "status": "running",
        "watchers": watchers,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_health_status_exposes_watcher_emission_and_rate_limit_counters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    heartbeat_path = tmp_path / "watcher_heartbeat.json"
    _write_registry_heartbeat(
        heartbeat_path,
        watchers={
            "panel": {
                "scope_glob": "📥 Inbox/**",
                "ticks_total": 100,
                "changed_total": 42,
                "emitted_total": 15,
                "rate_limited_total": 27,
                "errors_total": 0,
                "last_trace_id": "abc123",
                "last_emitted_event_at": 1_700_000_000.0,
            },
            "ingest": {
                "scope_glob": "/**",
                "ticks_total": 80,
                "changed_total": 10,
                "emitted_total": 9,
                "rate_limited_total": 1,
                "errors_total": 0,
            },
        },
        now=time.time(),
    )

    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(heartbeat_path))

    result = run_health()

    watcher_runtime = result.get("runtime", {}).get("watcher", {})
    assert "watchers" in watcher_runtime, (
        f"Expected 'watchers' in runtime.watcher; got keys: {list(watcher_runtime.keys())}"
    )
    panel = watcher_runtime["watchers"].get("panel", {})
    assert panel.get("changed_total") == 42
    assert panel.get("emitted_total") == 15
    assert panel.get("rate_limited_total") == 27

    ingest = watcher_runtime["watchers"].get("ingest", {})
    assert ingest.get("emitted_total") == 9
    assert ingest.get("rate_limited_total") == 1
