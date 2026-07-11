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


def test_ollama_probe_bounded_timeout_single_call(monkeypatch) -> None:
    """Ollama health probe must be bounded and evaluated once per run (#3461).

    Two independent defects amplified the outage:
      1. The probe reused `LLM_TIMEOUT` (60–120s for real generation) as its HTTP
         timeout, so one unreachable provider blocked the health path for minutes.
      2. `_check_ollama` was re-invoked once per ollama task-route, stacking those
         blocking probes.

    This asserts the probe now uses a bounded `HEALTH_PROBE_TIMEOUT` decoupled from
    `LLM_TIMEOUT`, and that task-route verification reuses a single precomputed probe
    result instead of re-hitting the provider per route.
    """
    import importlib

    # `app.cli.health` is attribute-shadowed by a CLI command group on the
    # package, so import the real module object explicitly.
    health_cli = importlib.import_module("app.cli.health")

    monkeypatch.setenv("LLM_TIMEOUT", "600")  # generation timeout must NOT leak in
    monkeypatch.setenv("HEALTH_PROBE_TIMEOUT", "2")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.invalid:11434")

    seen_timeouts: list[float] = []

    def _fake_get(url, timeout=None, **kwargs):
        seen_timeouts.append(timeout)
        raise health_cli.httpx.ConnectError("ollama unreachable")

    monkeypatch.setattr(health_cli.httpx, "get", _fake_get)

    # (1) direct probe: bounded timeout, decoupled from LLM_TIMEOUT.
    direct = health_cli._check_ollama()
    assert direct["ok"] is False
    assert seen_timeouts == [2.0]

    # (2) dedup: task-route verification reuses the single precomputed probe and
    # issues no additional provider calls for ollama routes.
    ollama_check = {
        "ok": True,
        "provider": "ollama",
        "base_url": "http://ollama.invalid:11434",
        "detail": "cached ollama probe",
    }
    router_check = {
        "route_policies": {
            "ask": {"effective": {"provider": "ollama", "model": "llama3"}},
            "chat": {"effective": {"provider": "ollama", "model": "llama3"}},
        }
    }
    calls_before = len(seen_timeouts)
    routes = health_cli._check_llm_task_routes(router_check, ollama_check=ollama_check)

    assert routes["ok"] is True
    assert routes["routes"]["ask"]["ok"] is True
    assert routes["routes"]["chat"]["ok"] is True
    assert len(seen_timeouts) == calls_before, "ollama probe re-issued per task-route"
