from __future__ import annotations

import json
import time
import asyncio
import importlib
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import health as health_route
from app.config import llm as llm_config
from app.model_access.health_observer import ProductHealthObserver
from app.runtime.worker_heartbeat import resolve_worker_heartbeat_path
from app.settings.models import SettingsBundle
from app.vault.paths import get_vault_inbox_dir_rel
from app.watcher.heartbeat import resolve_heartbeat_path

health_module = importlib.import_module("app.cli.health")


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


def _write_worker_heartbeat(
    path: Path,
    *,
    ts: float,
    status: str = "running",
    binding_blocked_pending: int | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat = {
        "ts": ts,
        "pid": 123,
        "status": status,
        "ticks_total": 3,
        "errors_total": 0,
        "processed_total": 2,
        "outbox_path": "/app/tmp/index-outbox.jsonl",
    }
    if binding_blocked_pending is not None:
        heartbeat["binding_blocked_pending"] = binding_blocked_pending
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
    outbox_path.touch()
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
    assert checks["llm_router"]["detail"] == "route configuration loaded"
    assert "llm_access" in checks
    assert checks["llm_access"]["required"] is True
    assert "capabilities" in checks["llm_access"]
    assert "llm_task_routes" in checks
    assert "capabilities" in checks["llm_task_routes"]
    assert "embedding_index" in checks
    assert "rebuild_required" in checks["embedding_index"]
    assert "llm_providers" in checks
    assert checks["llm_providers"]["detail"] == "adapter declarations loaded"
    assert "obsidian" in checks
    assert "required" in checks["obsidian"]


def test_health_endpoint_does_not_block_event_loop(monkeypatch) -> None:
    def slow_run_health(**_kwargs) -> dict[str, object]:
        time.sleep(0.2)
        return {"ok": True}

    monkeypatch.setattr(health_route, "run_health", slow_run_health)

    async def assert_nonblocking() -> None:
        health_task = asyncio.create_task(health_route.health())
        await asyncio.sleep(0.01)
        assert not health_task.done()
        assert await health_task == {"ok": True}

    asyncio.run(assert_nonblocking())


def test_health_model_preflight_pending_is_fast_and_fails_closed(
    monkeypatch, tmp_path
) -> None:
    client = _health_client(monkeypatch, tmp_path, worker_enabled=False)
    monkeypatch.setattr(health_module, "PRODUCT_HEALTH_OBSERVER", ProductHealthObserver())
    monkeypatch.setattr(
        health_module,
        "_check_llm_router",
        lambda: {
            "ok": True,
            "route_policies": {
                "qa": {
                    "effective": {
                        "provider": "openai",
                        "model": "gpt-6-luna",
                        "transport_id": "codex_cli_tailscale",
                        "reasoning_effort": "low",
                    },
                    "intent": {},
                }
            },
        },
    )
    monkeypatch.setattr(health_module, "_check_embedding_index", lambda: {"ok": True})
    started = Event()
    release = Event()

    def blocked_probe(_task_kind, _route, _intent, *, timeout_seconds=None):
        assert timeout_seconds == 30.0
        started.set()
        release.wait(2)
        return {
            "status": "available",
            "reason_code": "adapter_ready",
            "capabilities": {},
            "transport_observation": {
                "status": "available",
                "reason_code": "transport_reachable",
            },
        }

    monkeypatch.setattr(health_module, "_probe_selected_route", blocked_probe)

    try:
        started_at = time.monotonic()
        response = client.get("/api/health")
        elapsed = time.monotonic() - started_at

        assert response.status_code == 200
        assert elapsed < 3
        assert started.wait(1)
        assert response.json()["required_ok"] is False
        assert (
            response.json()["checks"]["llm_access"]["capabilities"]["text_generation"]["status"]
            == "unknown"
        )

        release.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            response = client.get("/api/health")
            if response.json()["checks"]["llm_access"]["ok"] is True:
                break
            Event().wait(0.01)
        assert response.json()["required_ok"] is True
    finally:
        release.set()


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
    assert all(action.get("id") != "llm_mock" for action in actions if isinstance(action, dict))


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


def test_health_blocks_readiness_for_binding_incompatible_pending_rows(
    monkeypatch, tmp_path
) -> None:
    heartbeat = tmp_path / "watcher-heartbeat.json"
    _write_watcher_heartbeat(heartbeat, ts=time.time())
    worker_hb = tmp_path / "worker-heartbeat.json"
    _write_worker_heartbeat(
        worker_hb,
        ts=time.time(),
        status="blocked_pending_mvr06",
        binding_blocked_pending=2,
    )
    client = _health_client(
        monkeypatch,
        tmp_path,
        watcher_path=heartbeat,
        worker_path=worker_hb,
        worker_enabled=True,
    )

    data = client.get("/api/health").json()

    assert data["required_ok"] is False
    worker = data["runtime"]["worker"]
    assert worker["ok"] is False
    assert worker["status"] == "blocked_pending_mvr06"
    assert worker["binding_blocked_pending"] == 2
    assert any(
        action.get("id") == "worker_binding_blocked"
        and action.get("severity") == "required"
        for action in data["suggested_actions"]
    )


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
    assert data["checks"]["llm_task_routes"]["capabilities"]["text_generation"]["status"] != "available"


def test_health_luna_route_is_not_blocked_by_unselected_ollama(
    monkeypatch, tmp_path
) -> None:
    client = _health_client(monkeypatch, tmp_path, worker_enabled=False)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    route_policies = {
        "qa": {
            "effective": {
                "provider": "openai",
                "model": "gpt-6-luna",
                "transport_id": "codex_cli_tailscale",
                "reasoning_effort": "low",
            },
            "intent": {},
        },
        "embed": {
            "effective": {
                "provider": "ollama",
                "model": "nomic-embed-text",
                "transport_id": "ollama_http",
            },
            "intent": {},
        },
    }
    monkeypatch.setattr(
        health_module,
        "_check_llm_router",
        lambda: {"ok": True, "route_policies": route_policies},
    )
    monkeypatch.setattr(
        health_module, "_check_embedding_index", lambda: {"ok": True}
    )
    monkeypatch.setattr(health_module, "PRODUCT_HEALTH_OBSERVER", ProductHealthObserver())

    class _Client:
        preflight_transport_observation = {
            "status": "available",
            "reason_code": "transport_reachable",
        }
        model_access_route = SimpleNamespace(
            provider="openai",
            model="gpt-6-luna",
            transport_id="codex_cli_tailscale",
            preflight_status="passed",
        )

        def chat(self, *_args, **_kwargs):
            raise AssertionError("health must never dispatch a completion")

    seen_intents = []

    def _get_chat_client_for_route(
        intent, *, selected_route, allow_fallback, allow_catalog_promotion
    ):
        assert selected_route.model == "gpt-6-luna"
        assert allow_fallback is False
        assert allow_catalog_promotion is False
        seen_intents.append(intent)
        return _Client()

    monkeypatch.setattr(
        health_module, "get_chat_client_for_route", _get_chat_client_for_route
    )

    response = client.get("/api/health")
    assert response.status_code == 200
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not response.json()["required_ok"]:
        Event().wait(0.01)
        response = client.get("/api/health")

    assert response.status_code == 200
    data = response.json()
    checks = data["checks"]
    assert data["required_ok"] is True
    assert "ollama" not in checks
    assert checks["llm_access"]["ok"] is True
    assert checks["llm_access"]["required"] is True
    assert set(checks["llm_access"]["capabilities"]) == {"text_generation"}
    assert checks["llm_task_routes"]["capabilities"] == checks["llm_access"]["capabilities"]
    assert data["runtime"]["llm"]["ok"] is True
    assert data["runtime"]["llm"]["capabilities"] == checks["llm_access"]["capabilities"]
    assert checks["llm_access"]["transport_observation"]["status"] == "available"
    assert (
        data["runtime"]["llm"]["transport_observation"]["status"]
        == "available"
    )
    assert "provider" not in repr(checks["llm_access"])
    assert "openai" not in repr(checks["llm_router"])
    assert [intent.task_kind for intent in seen_intents] == ["health"]


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


def test_canvas_seam_disabled_when_router_import_fails(monkeypatch, tmp_path) -> None:
    """Gate-on but import-broken canvas must report disabled, not enabled."""
    import importlib

    real_import_module = importlib.import_module

    def fake_import_module(name: str, *args, **kwargs):
        if name == "app.api.routes.canvas":
            raise ImportError("simulated broken canvas import")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setenv("CANVAS_ENABLED", "1")
    monkeypatch.setattr(importlib, "import_module", fake_import_module)
    client = _health_client(monkeypatch, tmp_path, worker_enabled=False)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    seams = resp.json().get("v6_0_seams") or {}
    assert seams.get("canvas") == "disabled"


def test_health_skips_eval_route_by_default(monkeypatch, tmp_path) -> None:
    heartbeat = tmp_path / "watcher-heartbeat.json"
    _write_watcher_heartbeat(heartbeat, ts=time.time())
    worker_hb = tmp_path / "worker-heartbeat.json"
    _write_worker_heartbeat(worker_hb, ts=time.time())
    client = _health_client(monkeypatch, tmp_path, watcher_path=heartbeat, worker_path=worker_hb, worker_enabled=True)

    probed: list[str] = []
    real_probe = health_module._probe_selected_route

    def _record_probe(task_kind, effective, intent):
        probed.append(task_kind)
        return real_probe(task_kind, effective, intent)

    monkeypatch.setattr(health_module, "_probe_selected_route", _record_probe)
    resp = client.get("/api/health")

    assert resp.status_code == 200
    assert "eval" not in probed


# --- security: DSN must not appear in health response ---

def test_health_db_dsn_is_masked_in_response(monkeypatch, tmp_path) -> None:
    client = _health_client(monkeypatch, tmp_path, worker_enabled=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:hunter2@host:5432/db")
    monkeypatch.setenv("STORE_BACKEND", "pg")

    from app.stores import db_health as _dh
    monkeypatch.setattr(_dh, "ping_postgres", lambda timeout: (True, "ok"))

    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.text
    assert "hunter2" not in body
    data = resp.json()
    dsn = data.get("runtime", {}).get("db", {}).get("dsn", "")
    assert "hunter2" not in dsn
    assert dsn == "" or "***" in dsn


def test_health_api_sanitizes_exception_details(monkeypatch) -> None:
    client = TestClient(app)

    def fake_run_health(**_kwargs) -> dict[str, object]:
        return {
            "ok": False,
            "required_ok": False,
            "trace_id": "trace-health-redaction",
            "checks": {
                "embedding_index": {
                    "ok": False,
                    "status": "fail",
                    "detail": "Traceback File \"/Users/me/vault/private.py\" fake_secret=hunter2",
                }
            },
            "runtime": {},
            "suggested_actions": [],
        }

    monkeypatch.setattr(health_route, "run_health", fake_run_health)

    resp = client.get("/api/health")

    assert resp.status_code == 200
    body = resp.text
    assert "Traceback" not in body
    assert "/Users/me" not in body
    assert "hunter2" not in body
    data = resp.json()
    check = data["checks"]["embedding_index"]
    assert check["status"] == "fail"
    assert check["detail"] == "health check detail redacted; inspect server logs with trace_id"
    assert data["trace_id"] == "trace-health-redaction"


def test_health_api_omits_selected_route_identity(monkeypatch) -> None:
    client = TestClient(app)

    def fake_run_health(**_kwargs) -> dict[str, object]:
        return {
            "ok": True,
            "required_ok": True,
            "checks": {
                "llm_access": {
                    "ok": True,
                    "transport_observation": {
                        "status": "available",
                        "freshness": "fresh",
                        "reason_code": "transport_reachable",
                        "selected_path_profile": "private_vlan",
                    },
                    "routes": {
                        "qa": {
                            "status": "ok",
                            "base_url": "https://operator:password@api.openai.com/private?token=secret#fragment",
                        }
                    },
                }
            },
            "runtime": {
                "llm": {
                    "ok": True,
                    "providers": ["openai"],
                    "transport_observation": {
                        "status": "available",
                        "freshness": "fresh",
                        "reason_code": "transport_reachable",
                        "selected_path_profile": "private_vlan",
                    },
                }
            },
            "suggested_actions": [],
        }

    monkeypatch.setattr(health_route, "run_health", fake_run_health)

    resp = client.get("/api/health")

    assert resp.status_code == 200
    data = resp.json()
    assert "routes" not in data["checks"]["llm_access"]
    assert "providers" not in data["runtime"]["llm"]
    assert "selected_path_profile" not in data["checks"]["llm_access"]["transport_observation"]
    assert "private_vlan" not in resp.text
    for secret in ("operator", "password", "private", "token", "secret", "fragment"):
        assert secret not in resp.text
    assert "openai" not in resp.text


def test_health_api_exposes_bounded_authority_spine_status(tmp_path, monkeypatch) -> None:
    """Health API exposes bounded authority/provenance posture for governed loops (AC1 for #1601)."""
    client = _health_client(monkeypatch, tmp_path, worker_enabled=False)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    # authority_spine is present and has bounded status fields
    assert "authority_spine" in data
    spine = data["authority_spine"]
    assert "write_guard" in spine
    assert spine["write_guard"] in {"active", "blocked", "unavailable"}
    assert "authority_non_upgrade" in spine
    assert spine["authority_non_upgrade"] == "enforced"
    assert "provenance_required_for_mutations" in spine
    assert spine["provenance_required_for_mutations"] == "yes"
    assert "read_projection_isolation" in spine
    assert spine["read_projection_isolation"] == "active"


def test_health_api_sanitizes_authority_spine_details(tmp_path, monkeypatch) -> None:
    """Health API authority_spine does not expose secrets, paths, or sensitive details (AC2 for #1601)."""
    import json
    import re

    client = _health_client(monkeypatch, tmp_path, worker_enabled=False)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    spine = data.get("authority_spine", {})
    spine_text = json.dumps(spine)
    # No file paths, no secrets, no tokens, no tracebacks
    sensitive = re.compile(r"Traceback|File \"|/[^\"'\s]{5,}|secret|token|password|api[_-]?key", re.IGNORECASE)
    assert not sensitive.search(spine_text), f"authority_spine leaked sensitive details: {spine_text}"
