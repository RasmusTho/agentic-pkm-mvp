from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app

_INGEST_EVENT = "ingest.vault.changed"


def _write_watcher_heartbeat(
    path: Path,
    *,
    ts: float,
    paused: bool = False,
    watchers: dict | None = None,
) -> None:
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
    if watchers is not None:
        heartbeat["watchers"] = watchers
    path.write_text(json.dumps(heartbeat, ensure_ascii=False), encoding="utf-8")


def _write_worker_heartbeat(
    path: Path,
    *,
    ts: float,
    processed_by_event: dict | None = None,
    last_processed: dict | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat = {
        "ts": ts,
        "pid": 123,
        "status": "running",
        "ticks_total": 2,
        "errors_total": 0,
        "outbox_path": "tmp/index-outbox.jsonl",
        "processed_total": 1,
    }
    if processed_by_event is not None:
        heartbeat["processed_by_event"] = processed_by_event
    if last_processed is not None:
        heartbeat["last_processed"] = last_processed
    path.write_text(json.dumps(heartbeat, ensure_ascii=False), encoding="utf-8")


def test_health_endpoint_returns_runtime_checks(monkeypatch, tmp_path) -> None:
    watcher = tmp_path / "watcher-heartbeat.json"
    worker = tmp_path / "worker-heartbeat.json"
    _write_watcher_heartbeat(
        watcher,
        ts=time.time(),
        watchers={
            "panel": {
                "ticks_total": 1,
                "changed_total": 0,
                "emitted_total": 0,
                "errors_total": 0,
            }
        },
    )
    _write_worker_heartbeat(
        worker,
        ts=time.time(),
        processed_by_event={_INGEST_EVENT: 1},
        last_processed={_INGEST_EVENT: time.time()},
    )
    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(watcher))
    monkeypatch.setenv("WATCHER_HEARTBEAT_STALE_SECONDS", "60")
    monkeypatch.setenv("WORKER_HEARTBEAT_PATH", str(worker))
    monkeypatch.setenv("WORKER_HEARTBEAT_STALE_SECONDS", "60")
    monkeypatch.setenv("WORKER_ENABLE", "1")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "memory")
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "runtime" in data
    runtime = data["runtime"]
    watcher_status = runtime["watcher"]
    assert watcher_status.get("ok") is True
    assert isinstance(watcher_status.get("freshness_seconds"), float)
    assert watcher_status.get("path", "").endswith("watcher-heartbeat.json")
    assert "panel" in (watcher_status.get("watchers") or [])
    worker_status = runtime["worker"]
    assert worker_status.get("ok") is True
    assert isinstance(worker_status.get("freshness_seconds"), float)
    assert worker_status.get("path", "").endswith("worker-heartbeat.json")
    assert runtime.get("db", {}).get("status") == "skipped"
    assert runtime.get("llm", {}).get("status") == "skipped"


def test_health_runtime_detects_stale_watchers(monkeypatch, tmp_path) -> None:
    watcher = tmp_path / "watcher-heartbeat.json"
    worker = tmp_path / "worker-heartbeat.json"
    _write_watcher_heartbeat(watcher, ts=time.time() - 120)
    _write_worker_heartbeat(worker, ts=time.time())
    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(watcher))
    monkeypatch.setenv("WATCHER_HEARTBEAT_STALE_SECONDS", "5")
    monkeypatch.setenv("WORKER_HEARTBEAT_PATH", str(worker))
    monkeypatch.setenv("WORKER_HEARTBEAT_STALE_SECONDS", "60")
    monkeypatch.setenv("WORKER_ENABLE", "1")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "memory")
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    watcher_status = resp.json()["runtime"]["watcher"]
    assert watcher_status.get("ok") is False
    assert "stale" in watcher_status.get("detail", "")


def test_health_strict_ingest_worker(monkeypatch, tmp_path) -> None:
    watcher = tmp_path / "watcher-heartbeat.json"
    worker = tmp_path / "worker-heartbeat.json"
    _write_watcher_heartbeat(watcher, ts=time.time())
    _write_worker_heartbeat(
        worker,
        ts=time.time(),
        processed_by_event={_INGEST_EVENT: 1},
        last_processed={_INGEST_EVENT: time.time() - 120},
    )
    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(watcher))
    monkeypatch.setenv("WATCHER_HEARTBEAT_STALE_SECONDS", "60")
    monkeypatch.setenv("WORKER_HEARTBEAT_PATH", str(worker))
    monkeypatch.setenv("WORKER_HEARTBEAT_STALE_SECONDS", "60")
    monkeypatch.setenv("WORKER_ENABLE", "1")
    monkeypatch.setenv("HEALTH_REQUIRE_INGEST_WORKER", "1")
    monkeypatch.setenv("INGEST_WORKER_STALE_SECONDS", "5")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "memory")
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    worker_status = resp.json()["runtime"]["worker"]
    assert worker_status.get("ok") is False
    assert _INGEST_EVENT in worker_status.get("detail", "")
