from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.config import llm as llm_config
from app.runtime.worker_heartbeat import resolve_worker_heartbeat_path
from app.settings.models import SettingsBundle
from app.vault.paths import get_vault_inbox_dir_rel
from app.watcher.heartbeat import resolve_heartbeat_path


@pytest.fixture(autouse=True)
def _isolate_llm_routing_settings(monkeypatch) -> None:
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: SettingsBundle())


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
    outbox_path = tmp_path / "index-outbox.jsonl"
    outbox_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
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
    monkeypatch.setenv("KNOWLEDGE_PRIMARY_ADAPTER", "fs_vault")
    monkeypatch.setenv("KNOWLEDGE_FALLBACK_ADAPTER", "obsidian_cli")
    monkeypatch.setenv("KNOWLEDGE_ALLOW_FALLBACK", "0")
    monkeypatch.setenv("KNOWLEDGE_STRICT_STARTUP", "0")
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
    assert "route_policies" in checks["llm_router"]
    assert "llm_task_routes" in checks
    assert "routes" in checks["llm_task_routes"]
    assert "embedding_index" in checks
    assert "rebuild_required" in checks["embedding_index"]
    assert "llm_providers" in checks
    assert "providers" in checks["llm_providers"]
    assert "obsidian" in checks
    assert "required" in checks["obsidian"]


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
    actions = data.get("suggested_actions")
    assert isinstance(actions, list)
    assert any(action.get("id") == "llm_mock" for action in actions if isinstance(action, dict))


def test_health_allows_stale(monkeypatch, tmp_path) -> None:
    heartbeat = tmp_path / "watcher-heartbeat.json"
    _write_watcher_heartbeat(heartbeat, ts=time.time() - 3600)
    client = _health_client(monkeypatch, tmp_path, watcher_path=heartbeat, worker_enabled=False)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("required_ok") is True
    assert data["runtime"]["watcher"]["ok"] is False


def test_health_missing_heartbeat(monkeypatch, tmp_path) -> None:
    _clear_default_heartbeat(monkeypatch)
    client = _health_client(monkeypatch, tmp_path, watcher_path=None, worker_enabled=False)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["runtime"]["watcher"]["ok"] is False
    assert data["runtime"]["watcher"]["status"] == "missing"


def test_health_respects_optional_worker(monkeypatch, tmp_path) -> None:
    heartbeat = tmp_path / "watcher-heartbeat.json"
    _write_watcher_heartbeat(heartbeat, ts=time.time())
    worker_hb = tmp_path / "worker-heartbeat.json"
    _write_worker_heartbeat(worker_hb, ts=time.time())
    client = _health_client(monkeypatch, tmp_path, watcher_path=heartbeat, worker_path=worker_hb, worker_enabled=False)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["runtime"]["worker"]["status"] == "disabled"


def test_health_requires_worker_when_enabled(monkeypatch, tmp_path) -> None:
    heartbeat = tmp_path / "watcher-heartbeat.json"
    _write_watcher_heartbeat(heartbeat, ts=time.time())
    worker_hb = tmp_path / "worker-heartbeat.json"
    _write_worker_heartbeat(worker_hb, ts=time.time() - 3600)
    client = _health_client(monkeypatch, tmp_path, watcher_path=heartbeat, worker_path=worker_hb, worker_enabled=True)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["runtime"]["worker"]["ok"] is False


def test_health_suggests_index_rebuild(monkeypatch, tmp_path) -> None:
    heartbeat = tmp_path / "watcher-heartbeat.json"
    _write_watcher_heartbeat(heartbeat, ts=time.time())
    worker_hb = tmp_path / "worker-heartbeat.json"
    _write_worker_heartbeat(worker_hb, ts=time.time())

    monkeypatch.setattr(
        "app.index.doctor.diagnose_index",
        lambda: {
            "backend": "pg",
            "expected_identity": {"provider": "mock", "model": "mock", "dim": 8},
            "stored_identity": {"provider": "mock", "model": "mock", "dim": 7},
            "stored_identity_present": True,
            "compatible_identity": False,
            "empty_index": False,
            "rebuild_required": True,
            "rebuild_reason": "Identity mismatch",
            "issues": ["Identity mismatch"],
            "warnings": [],
            "status": "error",
        },
    )

    client = _health_client(monkeypatch, tmp_path, watcher_path=heartbeat, worker_path=worker_hb, worker_enabled=True)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    actions = data.get("suggested_actions")
    assert isinstance(actions, list)
    assert any(
        action.get("id") == "index_rebuild" and action.get("severity") == "required"
        for action in actions
        if isinstance(action, dict)
    )
    assert data["checks"]["embedding_index"]["rebuild_required"] is True


def test_health_requires_task_route_configuration(monkeypatch, tmp_path) -> None:
    heartbeat = tmp_path / "watcher-heartbeat.json"
    _write_watcher_heartbeat(heartbeat, ts=time.time())
    worker_hb = tmp_path / "worker-heartbeat.json"
    _write_worker_heartbeat(worker_hb, ts=time.time())
    client = _health_client(monkeypatch, tmp_path, watcher_path=heartbeat, worker_path=worker_hb, worker_enabled=True)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("EMBED_MODEL", "text-embedding-test")
    monkeypatch.delenv("OPENAI_BASE", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(llm_config, "_ACTIVE_PROVIDER", None)

    resp = client.get("/api/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["required_ok"] is False
    assert data["checks"]["llm_task_routes"]["ok"] is False
    assert data["checks"]["llm_task_routes"]["routes"]["decide"]["status"] == "fail"


def test_health_includes_v6_0_seams_optional(monkeypatch, tmp_path) -> None:
    client = _health_client(monkeypatch, tmp_path, worker_enabled=False)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "v6_0_seams" in data
    seams = data["v6_0_seams"]
    assert isinstance(seams, dict)
    for key in ("orientation", "resurfacing", "commitments", "canvas"):
        assert key in seams
        assert seams[key] in ("enabled", "disabled")


def test_disabled_seam_not_blocking(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("CANVAS_ENABLED", raising=False)
    client = _health_client(monkeypatch, tmp_path, worker_enabled=False)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("required_ok") is True
    seams = data.get("v6_0_seams") or {}
    assert seams.get("canvas") == "disabled"


def test_health_skips_eval_route_by_default(monkeypatch, tmp_path) -> None:
    heartbeat = tmp_path / "watcher-heartbeat.json"
    _write_watcher_heartbeat(heartbeat, ts=time.time())
    worker_hb = tmp_path / "worker-heartbeat.json"
    _write_worker_heartbeat(worker_hb, ts=time.time())
    client = _health_client(monkeypatch, tmp_path, watcher_path=heartbeat, worker_path=worker_hb, worker_enabled=True)

    resp = client.get("/api/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["checks"]["llm_task_routes"]["routes"]["eval"]["status"] == "skipped"
