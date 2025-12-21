from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app


def _write_heartbeat(path: Path, *, ts: float, paused: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat = {
        "ts": ts,
        "pid": 999,
        "paused": paused,
        "vault_path": "/tmp/vault",
        "scope_glob": "@Inbox/**",
        "outbox_path": "tmp/index-outbox.jsonl",
        "ticks_total": 1,
        "errors_total": 0,
    }
    path.write_text(json.dumps(heartbeat, ensure_ascii=False), encoding="utf-8")


def _health_client(monkeypatch, tmp_path) -> TestClient:
    heartbeat = tmp_path / "watcher-heartbeat.json"
    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(heartbeat))
    monkeypatch.setenv("WATCHER_HEARTBEAT_STALE_SECONDS", "60")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "memory")
    client = TestClient(app)
    return client


def test_health_endpoint_returns_runtime_checks(monkeypatch, tmp_path) -> None:
    heartbeat = tmp_path / "watcher-heartbeat.json"
    _write_heartbeat(heartbeat, ts=time.time())
    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(heartbeat))
    client = _health_client(monkeypatch, tmp_path)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    runtime = data["runtime"]
    watcher = runtime["watcher"]
    assert watcher.get("ok") is True
    assert isinstance(watcher.get("freshness_seconds"), float)
    assert watcher.get("path", "").endswith("watcher-heartbeat.json")
    assert runtime.get("db", {}).get("status") == "skipped"
    assert runtime.get("llm", {}).get("status") == "skipped"


def test_health_runtime_detects_stale_watchers(monkeypatch, tmp_path) -> None:
    heartbeat = tmp_path / "watcher-heartbeat.json"
    _write_heartbeat(heartbeat, ts=time.time() - 120)
    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(heartbeat))
    monkeypatch.setenv("WATCHER_HEARTBEAT_STALE_SECONDS", "5")
    client = _health_client(monkeypatch, tmp_path)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    watcher = resp.json()["runtime"]["watcher"]
    assert watcher.get("ok") is False
    assert "stale" in watcher.get("detail", "")


def test_health_ok_without_watcher(monkeypatch, tmp_path) -> None:
    heartbeat = tmp_path / "watcher-heartbeat.json"
    heartbeat.unlink(missing_ok=True)
    client = _health_client(monkeypatch, tmp_path)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    assert data["runtime"]["watcher"]["ok"] is False


def test_health_requires_watcher_when_flagged(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WATCHER_HEARTBEAT_REQUIRED", "1")
    heartbeat = tmp_path / "watcher-heartbeat.json"
    heartbeat.unlink(missing_ok=True)
    client = _health_client(monkeypatch, tmp_path)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json().get("ok") is False
