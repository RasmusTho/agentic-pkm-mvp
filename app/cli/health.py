from __future__ import annotations

import importlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

import httpx

from app.events.types import INGEST_VAULT_CHANGED
from app.obs.log import span, with_trace_id
from app.runtime.worker_heartbeat import resolve_worker_heartbeat_path
from app.stores.db_health import ping_postgres, resolve_dsn
from app.watcher.heartbeat import resolve_heartbeat_path

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _result(ok: bool, detail: str, *, data: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": ok, "detail": detail}
    if data:
        out["data"] = data
    return out


def _env_float(name: str, fallback: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return fallback
    try:
        return float(raw)
    except Exception:
        return fallback


def _env_bool(name: str, *, fallback: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return fallback
    return raw.strip().lower() in _TRUE_VALUES


def _check_ffmpeg() -> dict[str, Any]:
    ok = shutil.which("ffmpeg") is not None
    detail = "ffmpeg hittades i PATH" if ok else "ffmpeg saknas i PATH"
    return _result(ok, detail)


def _check_yt_dlp() -> dict[str, Any]:
    try:
        importlib.import_module("yt_dlp")
        return _result(True, "yt-dlp kan importeras")
    except Exception as exc:  # pragma: no cover - import side-effects differ per env
        return _result(False, f"yt-dlp import misslyckades: {exc!s}")


def _check_outbox_path() -> dict[str, Any]:
    path = Path(os.environ.get("INDEX_OUTBOX_PATH", "./tmp/index-outbox.jsonl")).expanduser()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8"):
            ...
        return _result(True, f"Skrivåtkomst bekräftad: {path}")
    except Exception as exc:
        return _result(False, f"Kan inte skriva till {path}: {exc!s}")


def _check_ollama() -> dict[str, Any]:
    provider = os.environ.get("LLM_PROVIDER", "ollama").lower()
    base = os.environ.get(
        "OLLAMA_URL",
        os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
    ).rstrip("/")
    if provider != "ollama":
        result = _result(
            True,
            "Hoppar över Ollama-koll (LLM_PROVIDER != ollama)",
            data={"skipped": True},
        )
        result["provider"] = provider
        result["base_url"] = base
        return result
    try:
        resp = httpx.get(f"{base}/api/tags", timeout=float(os.environ.get("LLM_TIMEOUT", "5")))
        resp.raise_for_status()
        data = resp.json()
        models = None
        if isinstance(data, dict):
            models = [m.get("name") for m in data.get("models", [])]
        result = _result(True, f"Ollama nåddes ({base})", data={"models": models})
    except Exception as exc:
        result = _result(False, f"Ollama svarade inte ({base}): {exc!s}")
    result["provider"] = provider
    result["base_url"] = base
    return result


def _watcher_runtime_status(now: float | None = None) -> dict[str, Any]:
    now = now if now is not None else time.time()
    heartbeat_path = resolve_heartbeat_path()
    stale_seconds = _env_float("WATCHER_HEARTBEAT_STALE_SECONDS", 60.0)
    if not heartbeat_path.exists():
        return {
            "ok": False,
            "detail": "watcher not running (no heartbeat)",
            "path": str(heartbeat_path),
        }
    try:
        raw = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "ok": False,
            "detail": f"watcher heartbeat unreadable ({exc})",
            "path": str(heartbeat_path),
        }
    ts_raw = raw.get("ts")
    try:
        ts_value = float(ts_raw)
    except Exception:
        return {
            "ok": False,
            "detail": "watcher heartbeat missing timestamp",
            "path": str(heartbeat_path),
        }
    freshness = max(0.0, now - ts_value)
    paused = bool(raw.get("paused"))
    ok = freshness <= stale_seconds
    if ok:
        detail = f"watcher running (fresh {freshness:.1f}s, paused={paused})"
    else:
        detail = f"watcher stale (last seen {freshness:.1f}s ago)"
    payload: dict[str, Any] = {
        "ok": ok,
        "detail": detail,
        "path": str(heartbeat_path),
        "freshness_seconds": freshness,
        "paused": paused,
    }
    keys = (
        "pid",
        "scope_glob",
        "ticks_total",
        "errors_total",
        "vault_path",
        "outbox_path",
        "status",
    )
    for key in keys:
        if key in raw:
            payload[key] = raw[key]
    watchers = raw.get("watchers") if isinstance(raw, dict) else None
    if isinstance(watchers, dict):
        payload["watchers"] = sorted(watchers.keys())
    return payload


def _worker_runtime_status(now: float | None = None) -> dict[str, Any]:
    backend = (os.getenv("STORE_BACKEND") or "memory").strip().lower()
    worker_raw = os.getenv("WORKER_ENABLE")
    if worker_raw is None and backend != "pg":
        return {"ok": True, "detail": "skipped (memory mode)", "status": "skipped"}
    if worker_raw is not None and not _env_bool("WORKER_ENABLE", fallback=False):
        return {"ok": True, "detail": "skipped (WORKER_ENABLE=0)", "status": "skipped"}

    now = now if now is not None else time.time()
    heartbeat_path = resolve_worker_heartbeat_path()
    stale_seconds = _env_float("WORKER_HEARTBEAT_STALE_SECONDS", 60.0)
    if not heartbeat_path.exists():
        return {
            "ok": False,
            "detail": "worker not running (no heartbeat)",
            "path": str(heartbeat_path),
        }
    try:
        raw = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "ok": False,
            "detail": f"worker heartbeat unreadable ({exc})",
            "path": str(heartbeat_path),
        }
    ts_raw = raw.get("ts")
    try:
        ts_value = float(ts_raw)
    except Exception:
        return {
            "ok": False,
            "detail": "worker heartbeat missing timestamp",
            "path": str(heartbeat_path),
        }
    freshness = max(0.0, now - ts_value)
    ok = freshness <= stale_seconds
    if ok:
        detail = f"worker running (fresh {freshness:.1f}s)"
    else:
        detail = f"worker stale (last seen {freshness:.1f}s ago)"

    payload: dict[str, Any] = {
        "ok": ok,
        "detail": detail,
        "path": str(heartbeat_path),
        "freshness_seconds": freshness,
    }
    keys = (
        "pid",
        "status",
        "ticks_total",
        "errors_total",
        "processed_total",
        "processed_by_event",
        "last_processed",
        "outbox_path",
    )
    for key in keys:
        if key in raw:
            payload[key] = raw[key]

    require_ingest = _env_bool("HEALTH_REQUIRE_INGEST_WORKER", fallback=False)
    if require_ingest:
        ingest_stale = _env_float("INGEST_WORKER_STALE_SECONDS", 300.0)
        last_processed_raw = raw.get("last_processed")
        last_processed_map = last_processed_raw if isinstance(last_processed_raw, dict) else {}
        last_seen = last_processed_map.get(INGEST_VAULT_CHANGED)
        try:
            last_seen_val = float(last_seen) if last_seen is not None else None
        except Exception:
            last_seen_val = None
        if last_seen_val is None:
            payload["ok"] = False
            payload["detail"] = f"{INGEST_VAULT_CHANGED} not processed yet"
        else:
            age = max(0.0, now - last_seen_val)
            if age > ingest_stale:
                payload["ok"] = False
                payload["detail"] = f"{INGEST_VAULT_CHANGED} stale (last seen {age:.1f}s ago)"
    return payload


def _db_runtime_status() -> dict[str, Any]:
    backend = (os.getenv("STORE_BACKEND") or "memory").strip().lower()
    dsn_value = resolve_dsn()
    if backend != "pg" and not dsn_value:
        return {"ok": True, "detail": "skipped (memory mode)", "status": "skipped"}
    if not dsn_value:
        return {
            "ok": False,
            "detail": "DATABASE_URL missing for postgres backend",
            "status": "missing",
        }
    ok, detail = ping_postgres(timeout=1.0)
    return {"ok": ok, "detail": detail, "dsn": dsn_value}


def _llm_runtime_status(check_result: dict[str, Any]) -> dict[str, Any]:
    provider = check_result.get("provider") or os.getenv("LLM_PROVIDER", "ollama")
    base_url = check_result.get("base_url")
    detail = check_result.get("detail", "")
    ok = bool(check_result.get("ok"))
    if (provider or "").lower() != "ollama":
        return {
            "ok": True,
            "detail": detail or f"LLM_PROVIDER != ollama ({provider})",
            "provider": provider,
            "base_url": base_url,
            "status": "skipped",
        }
    return {
        "ok": ok,
        "detail": detail,
        "provider": provider,
        "base_url": base_url,
        "status": "ok" if ok else "fail",
    }


@span("health.check")
def run_health(*, trace_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
    trace_id = with_trace_id(trace_id)
    checks = {
        "ffmpeg": _check_ffmpeg(),
        "yt_dlp": _check_yt_dlp(),
        "index_outbox": _check_outbox_path(),
        "ollama": _check_ollama(),
    }
    runtime = {
        "watcher": _watcher_runtime_status(),
        "worker": _worker_runtime_status(),
        "db": _db_runtime_status(),
        "llm": _llm_runtime_status(checks["ollama"]),
    }
    checks_ok = all(item.get("ok") for item in checks.values())
    runtime_ok = all(item.get("ok") for item in runtime.values())
    ok = bool(checks_ok and runtime_ok)
    return {"ok": ok, "checks": checks, "runtime": runtime, "trace_id": trace_id}


__all__ = ["run_health"]
