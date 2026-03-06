from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app
from app.vault.paths import get_vault_inbox_dir_rel


def _write_watcher_heartbeat(path: Path, *, ts: float, paused: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    scope_glob = f"{get_vault_inbox_dir_rel(path.parent)}/**"
    heartbeat = {
        "ts": ts,
        "pid": 999,
        "paused": paused,
        "vault_path": "/tmp/vault",
        "scope_glob": scope_glob,
        "outbox_path": "tmp/index-outbox.jsonl",
        "ticks_total": 1,
        "errors_total": 0,
    }
    path.write_text(json.dumps(heartbeat, ensure_ascii=False), encoding="utf-8")


def test_health_handles_malformed_heartbeat_json(tmp_path, monkeypatch) -> None:
    """
    Health endpoint MUST handle corrupted heartbeat files gracefully.

    See: docs/OBSERVABILITY.md §Heartbeat locations and freshness
    """
    heartbeat = tmp_path / "watcher-heartbeat.json"
    heartbeat.write_text("{ invalid json", encoding="utf-8")

    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(heartbeat))
    monkeypatch.setenv("KNOWLEDGE_PRIMARY_ADAPTER", "fs_vault")
    monkeypatch.setenv("KNOWLEDGE_STRICT_STARTUP", "0")
    client = TestClient(app)
    resp = client.get("/api/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["runtime"]["watcher"]["ok"] is False
    assert "malformed" in data["runtime"]["watcher"]["status"].lower()


def test_health_handles_future_heartbeat_timestamp(tmp_path, monkeypatch) -> None:
    """
    Health MUST reject heartbeats with timestamps in the future.

    See: docs/OBSERVABILITY.md §Heartbeat locations and freshness
    """
    heartbeat = tmp_path / "watcher-heartbeat.json"
    future_ts = time.time() + 3600
    _write_watcher_heartbeat(heartbeat, ts=future_ts)

    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(heartbeat))
    monkeypatch.setenv("KNOWLEDGE_PRIMARY_ADAPTER", "fs_vault")
    monkeypatch.setenv("KNOWLEDGE_STRICT_STARTUP", "0")
    client = TestClient(app)
    resp = client.get("/api/health")

    assert resp.status_code == 200
    data = resp.json()
    watcher = data["runtime"]["watcher"]
    assert watcher["ok"] is False
    status = str(watcher.get("status") or "")
    assert status in {"future", "invalid", "stale"}
    assert "future" in str(watcher.get("detail") or "").lower() or status == "future"
