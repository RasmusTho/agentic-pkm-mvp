from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app
from app.runtime.worker_heartbeat import resolve_worker_heartbeat_path
from app.watcher.heartbeat import resolve_heartbeat_path


def _write_watcher_heartbeat(path: Path, *, ts: float, paused: bool = False) -> None:
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


def _write_worker_heartbeat(path: Path, *, ts: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat = {
        "ts": ts,
        "pid": 123,
        "status": "running",
        "ticks_total": 3,
        "errors_total": 0,
        "processed_total": 2,
        "outbox_path": "/app/tmp/index-outbox.jsonl",
    }
    path.write_text(json.dumps(heartbeat, ensure_ascii=False), encoding="utf-8")


def _clear_default_heartbeat(monkeypatch) -> Path:
    monkeypatch.delenv("WATCHER_HEARTBEAT_PATH", raising=False)
    path = resolve_heartbeat_path()
    path.unlink(missing_ok=True)
    return path


def _clear_worker_heartbeat(monkeypatch) -> Path:
    monkeypatch.delenv("WORKER_HEARTBEAT_PATH", raising=False)
    path = resolve_worker_heartbeat_path()
    path.unlink(missing_ok=True)
    return path


def _health_client(
    monkeypatch,
    tmp_path,
    *,
    watcher_path: Path | None = None,
    worker_path: Path | None = None,
    worker_enabled: bool | None = False,
) -> TestClient:
    if watcher_path is not None:
        monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(watcher_path))
    else:
        monkeypatch.delenv("WATCHER_HEARTBEAT_PATH", raising=False)
    if worker_path is not None:
        monkeypatch.setenv("WORKER_HEARTBEAT_PATH", str(worker_path))
    else:
        monkeypatch.delenv("WORKER_HEARTBEAT_PATH", raising=False)
    if worker_enabled is None:
        monkeypatch.delenv("WORKER_ENABLE", raising=False)
    else:
        monkeypatch.setenv("WORKER_ENABLE", "1" if worker_enabled else "0")
    monkeypatch.setenv("WATCHER_HEARTBEAT_STALE_SECONDS", "60")
    monkeypatch.setenv("WORKER_HEARTBEAT_STALE_SECONDS", "60")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "memory")
    client = TestClient(app)
    return client


def _assert_check_metadata(payload: dict) -> None:
    checks = payload.get("checks") or {}
    assert "ffmpeg" in checks
    assert "required" in checks["ffmpeg"]
    assert "severity" in checks["ffmpeg"]
    assert "llm_router" in checks
    assert "selected_defaults" in checks["llm_router"]
    assert "llm_providers" in checks
    assert "providers" in checks["llm_providers"]


def test_health_success(monkeypatch, tmp_path) -> None:
    heartbeat = tmp_path / "watcher-heartbeat.json"
    _write_watcher_heartbeat(heartbeat, ts=time.time())
    worker_hb = tmp_path / "worker-heartbeat.json"
    _write_worker_heartbeat(worker_hb, ts=time.time())
    client = _health_client(monkeypatch, tmp_path, watcher_path=heartbeat, worker_path=worker_hb, worker_enabled=True)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("required_ok") is True
    runtime = data["runtime"]
    watcher = runtime["watcher"]
    worker = runtime["worker"]
    assert watcher.get("ok") is True
    assert worker.get("ok") is True
    assert isinstance(worker.get("freshness_seconds"), float)
    assert worker.get("processed_total") == 2
    _assert_check_metadata(data)


def test_health_allows_stale(monkeypatch, tmp_path) -> None:
    heartbeat = tmp_path / "watcher-heartbeat.json"
    _write_watcher_heartbeat(heartbeat, ts=time.time() - 61)
    client = _health_client(monkeypatch, tmp_path, watcher_path=heartbeat, worker_enabled=False)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    watcher = resp.json()["runtime"]["watcher"]
    assert watcher.get("ok") is False
    assert "stale" in watcher.get("detail", "")


def test_health_ok_without_watcher(monkeypatch, tmp_path) -> None:
    _clear_default_heartbeat(monkeypatch)
    client = _health_client(monkeypatch, tmp_path, worker_enabled=False)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("required_ok") is True
    assert data["runtime"]["watcher"]["ok"] is False


def test_health_requires_watcher_when_flagged(monkeypatch, tmp_path) -> None:
    _clear_default_heartbeat(monkeypatch)
    monkeypatch.setenv("WATCHER_HEARTBEAT_REQUIRED", "1")
    client = _health_client(monkeypatch, tmp_path, worker_enabled=False)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json().get("required_ok") is False


def test_health_reads_repo_heartbeat(monkeypatch, tmp_path) -> None:
    default_path = _clear_default_heartbeat(monkeypatch)
    worker_path = _clear_worker_heartbeat(monkeypatch)
    try:
        _write_watcher_heartbeat(default_path, ts=time.time())
        _write_worker_heartbeat(worker_path, ts=time.time())
        client = _health_client(monkeypatch, tmp_path, worker_path=worker_path, worker_enabled=True)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        payload = resp.json()["runtime"]
        assert payload["watcher"]["ok"] is True
        assert payload["worker"]["ok"] is True
    finally:
        default_path.unlink(missing_ok=True)
        worker_path.unlink(missing_ok=True)


def test_health_skips_worker_when_disabled(monkeypatch, tmp_path) -> None:
    worker_path = tmp_path / "worker-heartbeat.json"
    _write_worker_heartbeat(worker_path, ts=time.time())
    client = _health_client(monkeypatch, tmp_path, worker_path=worker_path, worker_enabled=False)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    worker = resp.json()["runtime"]["worker"]
    assert worker.get("status") == "skipped"
    assert resp.json().get("required_ok") is True


def test_health_skips_worker_by_default_in_memory_mode(monkeypatch, tmp_path) -> None:
    _clear_default_heartbeat(monkeypatch)
    _clear_worker_heartbeat(monkeypatch)
    client = _health_client(monkeypatch, tmp_path, worker_enabled=None)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("required_ok") is True
    worker = payload["runtime"]["worker"]
    assert worker.get("status") == "skipped"


def test_health_worker_missing(monkeypatch, tmp_path) -> None:
    worker_path = _clear_worker_heartbeat(monkeypatch)
    try:
        _write_worker_heartbeat(worker_path, ts=time.time())
        client = _health_client(monkeypatch, tmp_path, worker_path=worker_path, worker_enabled=True)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        payload = resp.json()["runtime"]
        assert payload["worker"]["ok"] is True
        worker_path.unlink(missing_ok=True)
        resp = client.get("/api/health")
        assert resp.json()["runtime"]["worker"]["ok"] is False
    finally:
        worker_path.unlink(missing_ok=True)
