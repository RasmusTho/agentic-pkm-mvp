from __future__ import annotations

import importlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict

import httpx

from app.obs.log import span, with_trace_id
from app.stores.db_health import ping_postgres, resolve_dsn
from app.watcher.heartbeat import resolve_heartbeat_path

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _result(ok: bool, detail: str, *, data: Dict[str, Any] | None = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": ok, "detail": detail}
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


def _watcher_required() -> bool:
    raw = os.getenv("WATCHER_HEARTBEAT_REQUIRED")
    if not raw:
        return False
    return raw.strip().lower() in _TRUE_VALUES


def _check_ffmpeg() -> Dict[str, Any]:
    ok = shutil.which("ffmpeg") is not None
    detail = "ffmpeg hittades i PATH" if ok else "ffmpeg saknas i PATH"
    return _result(ok, detail)


def _check_yt_dlp() -> Dict[str, Any]:
    try:
        importlib.import_module("yt_dlp")
        return _result(True, "yt-dlp kan importeras")
    except Exception as exc:  # pragma: no cover - import side-effects differ per env
        return _result(False, f"yt-dlp import misslyckades: {exc!s}")


def _check_outbox_path() -> Dict[str, Any]:
    path = Path(os.environ.get("INDEX_OUTBOX_PATH", "./tmp/index-outbox.jsonl")).expanduser()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8"):
            ...
        return _result(True, f"Skrivåtkomst bekräftad: {path}")
    except Exception as exc:
        return _result(False, f"Kan inte skriva till {path}: {exc!s}")


def _check_ollama() -> Dict[str, Any]:
    provider = os.environ.get("LLM_PROVIDER", "ollama").lower()
    base = os.environ.get("OLLAMA_URL", os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")
    if provider != "ollama":
        result = _result(True, "Hoppar över Ollama-koll (LLM_PROVIDER != ollama)", data={"skipped": True})
        result["provider"] = provider
        result["base_url"] = base
        return result
    try:
        resp = httpx.get(f"{base}/api/tags", timeout=float(os.environ.get("LLM_TIMEOUT", "5")))
        resp.raise_for_status()
        data = resp.json()
        result = _result(
            True,
            f"Ollama nåddes ({base})",
            data={"models": [m.get("name") for m in data.get("models", [])] if isinstance(data, dict) else None},
        )
    except Exception as exc:
        result = _result(False, f"Ollama svarade inte ({base}): {exc!s}")
    result["provider"] = provider
    result["base_url"] = base
    return result


def _watcher_runtime_status(now: float | None = None) -> Dict[str, Any]:
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
    payload: Dict[str, Any] = {
        "ok": ok,
        "detail": detail,
        "path": str(heartbeat_path),
        "freshness_seconds": freshness,
        "paused": paused,
    }
    for key in ("pid", "scope_glob", "ticks_total", "errors_total", "vault_path", "outbox_path"):
        if key in raw:
            payload[key] = raw[key]
    return payload


def _db_runtime_status() -> Dict[str, Any]:
    backend = (os.getenv("STORE_BACKEND") or "memory").strip().lower()
    dsn_value = resolve_dsn()
    if backend != "pg" and not dsn_value:
        return {"ok": True, "detail": "skipped (memory mode)", "status": "skipped"}
    if not dsn_value:
        return {"ok": False, "detail": "DATABASE_URL missing for postgres backend", "status": "missing"}
    ok, detail = ping_postgres(timeout=1.0)
    return {"ok": ok, "detail": detail, "dsn": dsn_value}


def _llm_runtime_status(check_result: Dict[str, Any]) -> Dict[str, Any]:
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


def _runtime_ok(runtime: dict[str, dict[str, Any]]) -> bool:
    base_ok = bool(runtime.get("db", {}).get("ok") and runtime.get("llm", {}).get("ok"))
    if _watcher_required():
        return base_ok and bool(runtime.get("watcher", {}).get("ok"))
    return base_ok


@span("health.check")
def run_health(*, trace_id: str | None = None, **kwargs: Any) -> Dict[str, Any]:
    trace_id = with_trace_id(trace_id)
    checks = {
        "ffmpeg": _check_ffmpeg(),
        "yt_dlp": _check_yt_dlp(),
        "index_outbox": _check_outbox_path(),
        "ollama": _check_ollama(),
    }
    runtime = {
        "watcher": _watcher_runtime_status(),
        "db": _db_runtime_status(),
        "llm": _llm_runtime_status(checks["ollama"]),
    }
    checks_ok = all(item.get("ok") for item in checks.values())
    runtime_ok = _runtime_ok(runtime)
    ok = bool(checks_ok and runtime_ok)
    return {"ok": ok, "checks": checks, "runtime": runtime, "trace_id": trace_id}


__all__ = ["run_health"]
