from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import httpx
import pytest
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
    monkeypatch.setenv("KNOWLEDGE_FALLBACK_ADAPTER", "obsidian_cli")
    monkeypatch.setenv("KNOWLEDGE_ALLOW_FALLBACK", "0")
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
    monkeypatch.setenv("KNOWLEDGE_FALLBACK_ADAPTER", "obsidian_cli")
    monkeypatch.setenv("KNOWLEDGE_ALLOW_FALLBACK", "0")
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


@pytest.mark.asyncio
async def test_slow_api_health_does_not_block_healthz(monkeypatch) -> None:
    """
    /api/health MUST run its (potentially slow, blocking-I/O) checks off the
    event loop so a slow or hung upstream probe (e.g. Ollama) cannot starve
    the trivial /healthz endpoint that container healthchecks depend on.

    Regression for the 2026-07-11 prod outage: run_health() was called
    inline inside `async def health()`, so its blocking httpx calls to
    Ollama (once directly, again per LLM task route) froze the single
    uvicorn event loop and took /healthz down with it.
    """
    import app.api.routes.health as health_route

    def _slow_blocking_run_health() -> dict:
        # Simulate the blocking I/O run_health() performs (e.g. httpx.get
        # to Ollama) with a plain time.sleep so it would starve the loop
        # if it ran inline instead of on a worker thread.
        time.sleep(1.0)
        return {"ok": True, "required_ok": True, "checks": {}, "runtime": {}}

    monkeypatch.setattr(health_route, "run_health", _slow_blocking_run_health)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        start = time.monotonic()
        # Fire the slow request first without yielding, so the event loop
        # picks it up before the cheap probe below — mirroring real
        # concurrent load where a poller's in-flight request is already
        # executing when /healthz arrives. If run_health() runs inline on
        # the loop, this blocking call monopolizes the *only* OS thread and
        # /healthz cannot even begin until it releases the thread.
        slow_task = asyncio.create_task(client.get("/api/health"))
        healthz_resp = await client.get("/healthz")
        healthz_elapsed = time.monotonic() - start

        slow_resp = await slow_task

    assert healthz_resp.status_code == 200
    assert healthz_resp.json() == {"ok": True}
    # /healthz must stay cheap regardless of how long /api/health takes —
    # if the event loop were blocked, this would take ~1s (or more, under
    # concurrent load) instead of resolving near-instantly.
    assert healthz_elapsed < 0.5, f"/healthz took {healthz_elapsed:.3f}s while /api/health was in flight"

    assert slow_resp.status_code == 200
    assert slow_resp.json()["ok"] is True
