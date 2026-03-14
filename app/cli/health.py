from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict

import httpx

from app.components.llm.fabric import describe_default_routes
from app.knowledge.errors import KnowledgeConfigError
from app.knowledge.health import obsidian_dependency_status
from app.knowledge.settings import KnowledgeAdapter, load_knowledge_settings
from app.obs.log import span, with_trace_id
from app.runtime.worker_heartbeat import resolve_worker_heartbeat_path
from app.settings.panel_actions import get_panel_actions_diagnostics
from app.stores.db_health import ping_postgres, resolve_dsn
from app.watcher.heartbeat import resolve_heartbeat_path

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _result(ok: bool, detail: str, *, data: Dict[str, Any] | None = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": ok, "detail": detail}
    if data:
        out["data"] = data
    return out


def _annotate_required(payload: Dict[str, Any], *, required: bool, severity: str | None = None) -> Dict[str, Any]:
    payload["required"] = required
    payload["severity"] = severity or ("required" if required else "optional")
    return payload


def _env_float(name: str, fallback: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return fallback
    try:
        return float(raw)
    except Exception:
        return fallback


def _is_enabled(env_name: str, default: bool = True) -> bool:
    raw = os.getenv(env_name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


def _watcher_required() -> bool:
    raw = os.getenv("WATCHER_HEARTBEAT_REQUIRED")
    if not raw:
        return False
    return raw.strip().lower() in _TRUE_VALUES


def _ollama_required() -> bool:
    provider = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    return provider in {"ollama", "llm"}


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


def _check_panel_actions() -> Dict[str, Any]:
    diag = get_panel_actions_diagnostics()
    count = diag.get("panel_actions_mappings_count") or 0
    resolved = diag.get("resolved_panel_actions_root")
    error = diag.get("last_panel_mapping_load_error")
    if count > 0:
        detail = f"panel actions loaded ({count})"
    elif resolved is None:
        detail = "panel actions root not resolved"
    elif error:
        detail = f"panel actions load error: {error}"
    else:
        detail = "panel actions root missing or empty"
    return _result(True, detail, data={"resolved_root": resolved, "count": count})


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
    base = os.environ.get("OLLAMA_URL", os.environ.get("OLLAMA_HOST", "")).rstrip("/")
    if provider != "ollama":
        result = _result(True, "Hoppar över Ollama-koll (LLM_PROVIDER != ollama)", data={"skipped": True})
        result["provider"] = provider
        result["base_url"] = base
        return result
    if not base:
        return _result(False, "OLLAMA_URL eller OLLAMA_HOST saknas", data={"provider": provider})
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


def _check_llm_router() -> Dict[str, Any]:
    forced_provider = os.getenv("LLM_FORCE_PROVIDER")
    forced_model = os.getenv("LLM_FORCE_MODEL")
    return {
        "ok": True,
        "detail": "router ready",
        "selected_defaults": describe_default_routes(),
        "forced_overrides": {
            "provider": forced_provider or "",
            "model": forced_model or "",
        },
    }


def _check_llm_providers(ollama_check: Dict[str, Any]) -> Dict[str, Any]:
    provider = (os.getenv("LLM_PROVIDER") or "mock").strip().lower()
    providers: list[dict[str, Any]] = [{"name": "mock", "ok": True, "detail": "deterministic"}]
    if provider in {"ollama", "llm", ""}:
        providers.append(
            {
                "name": "ollama",
                "ok": bool(ollama_check.get("ok")),
                "detail": ollama_check.get("detail", ""),
            }
        )
    elif provider and provider != "mock":
        providers.append({"name": provider, "ok": False, "detail": "unknown provider"})

    overall = all(entry.get("ok") for entry in providers)
    detail = "providers ready" if overall else "one or more providers unavailable"
    return {
        "ok": overall,
        "detail": detail,
        "providers": providers,
        "active_provider": provider or "mock",
    }


def _obsidian_required() -> bool:
    explicit_policy = any(
        os.getenv(name) is not None
        for name in ("KNOWLEDGE_PRIMARY_ADAPTER", "KNOWLEDGE_STRICT_STARTUP", "KNOWLEDGE_ALLOW_FALLBACK")
    )
    if not explicit_policy:
        return False
    try:
        settings = load_knowledge_settings()
    except KnowledgeConfigError:
        return True
    if settings.strict_startup:
        return True
    if settings.primary_adapter != KnowledgeAdapter.OBSIDIAN_CLI:
        return False
    return not settings.allow_fallback


def _get_obsidian_installer_version() -> str | None:
    env_version = (os.getenv("OBSIDIAN_INSTALLER_VERSION") or "").strip()
    if env_version:
        return env_version
    try:
        proc = subprocess.run(
            ["obsidian", "version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3.0,
        )
        raw = (proc.stdout or proc.stderr or "").strip()
        return raw or None
    except Exception:
        return None


def _check_obsidian_dependencies() -> Dict[str, Any]:
    try:
        settings = load_knowledge_settings()
    except KnowledgeConfigError as exc:
        return _result(False, f"knowledge settings invalid: {exc}")
    status = obsidian_dependency_status(get_installer_version=_get_obsidian_installer_version)
    data = {
        **status.details,
        "primary_adapter": settings.primary_adapter.value,
        "fallback_adapter": settings.fallback_adapter.value,
        "strict_startup": settings.strict_startup,
        "allow_fallback": settings.allow_fallback,
    }
    if status.ok:
        return _result(True, "Obsidian dependency checks passed", data=data)
    return _result(False, "Obsidian dependency checks failed", data=data)


def _heartbeat_status(
    *,
    name: str,
    path: Path,
    stale_seconds: float,
    now: float,
    skip: bool = False,
) -> Dict[str, Any]:
    if skip:
        return {"ok": True, "detail": "disabled (skipped)", "status": "disabled"}

    if not path.exists():
        return {
            "ok": False,
            "detail": f"{name} not running (no heartbeat)",
            "path": str(path),
            "status": "missing",
        }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "ok": False,
            "detail": f"{name} heartbeat malformed ({exc})",
            "path": str(path),
            "status": "malformed",
        }
    ts_raw = raw.get("ts")
    try:
        ts_value = float(ts_raw)
    except Exception:
        return {
            "ok": False,
            "detail": f"{name} heartbeat missing timestamp",
            "path": str(path),
            "status": "invalid",
        }
    if ts_value > now:
        return {
            "ok": False,
            "detail": f"{name} heartbeat timestamp is in the future",
            "path": str(path),
            "status": "future",
        }
    freshness = max(0.0, now - ts_value)
    ok = freshness <= stale_seconds
    paused_value = bool(raw.get("paused", False))
    detail = (
        f"{name} running (fresh {freshness:.1f}s, paused={paused_value})"
        if ok
        else f"{name} stale (last seen {freshness:.1f}s ago)"
    )
    payload: Dict[str, Any] = {
        "ok": ok,
        "detail": detail,
        "path": str(path),
        "freshness_seconds": freshness,
        "paused": paused_value,
        "status": "ok" if ok else "stale",
    }
    for key in (
        "pid",
        "scope_glob",
        "ticks_total",
        "errors_total",
        "vault_path",
        "outbox_path",
        "processed_total",
        "enqueue_failures_total",
    ):
        if key in raw:
            payload[key] = raw[key]
    return payload


def _watcher_runtime_status(now: float | None = None) -> Dict[str, Any]:
    now = now if now is not None else time.time()
    heartbeat_path = resolve_heartbeat_path()
    stale_seconds = _env_float("WATCHER_HEARTBEAT_STALE_SECONDS", 60.0)
    return _heartbeat_status(
        name="watcher",
        path=heartbeat_path,
        stale_seconds=stale_seconds,
        now=now,
    )


def _worker_runtime_status(now: float | None = None) -> Dict[str, Any]:
    backend = (os.getenv("STORE_BACKEND") or "memory").strip().lower()
    enabled_default = backend != "memory"
    skip = not _is_enabled("WORKER_ENABLE", default=enabled_default)
    now = now if now is not None else time.time()
    heartbeat_path = resolve_worker_heartbeat_path()
    stale_seconds = _env_float("WORKER_HEARTBEAT_STALE_SECONDS", 60.0)
    return _heartbeat_status(
        name="worker",
        path=heartbeat_path,
        stale_seconds=stale_seconds,
        now=now,
        skip=skip,
    )


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
    base_ok = bool(
        runtime.get("db", {}).get("ok")
        and runtime.get("llm", {}).get("ok")
        and runtime.get("worker", {}).get("ok")
    )
    if _watcher_required():
        return base_ok and bool(runtime.get("watcher", {}).get("ok"))
    return base_ok


def _checks_ok(checks: dict[str, dict[str, Any]]) -> bool:
    return all(item.get("ok") for item in checks.values() if item.get("required", True))


def _required_checks_ok(checks: dict[str, dict[str, Any]]) -> bool:
    return _checks_ok(checks)


def _suggested_actions(checks: dict[str, dict[str, Any]], runtime: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []

    ffmpeg = checks.get("ffmpeg", {})
    if ffmpeg.get("ok") is False:
        actions.append(
            {
                "id": "ffmpeg_missing",
                "severity": "optional",
                "message": "ffmpeg missing; media transcription features disabled",
                "command_hint": "",
            }
        )

    try:
        from app.index.doctor import diagnose_index

        diag = diagnose_index()
        issues = diag.get("issues") or []
        if issues:
            actions.append(
                {
                    "id": "index_rebuild",
                    "severity": "required",
                    "message": "Embedding/index identity mismatch detected",
                    "command_hint": "python -m app.cli index rebuild --profile default",
                }
            )
    except Exception:
        pass

    llm_providers = checks.get("llm_providers", {})
    active_provider = (llm_providers.get("active_provider") or "").lower()
    if active_provider == "mock":
        actions.append(
            {
                "id": "llm_mock",
                "severity": "optional",
                "message": "LLM provider is mock; LLM features are deterministic only",
                "command_hint": "LLM_PROVIDER=ollama",
            }
        )

    watcher_runtime = runtime.get("watcher", {})
    enqueue_failures = watcher_runtime.get("enqueue_failures_total")
    if isinstance(enqueue_failures, int) and enqueue_failures > 0:
        actions.append(
            {
                "id": "watcher_outbox_enqueue_failed",
                "severity": "required",
                "message": "Watcher failed to enqueue DB outbox events",
                "command_hint": "Check DATABASE_URL and watcher logs",
            }
        )

    worker_runtime = runtime.get("worker", {})
    worker_status = str(worker_runtime.get("status") or "").lower()
    if worker_status in {"missing", "stale", "invalid", "malformed", "future"}:
        actions.append(
            {
                "id": "worker_restart",
                "severity": "required",
                "message": "Worker heartbeat unhealthy; restart the worker service",
                "command": "docker compose restart worker",
            }
        )

    obsidian = checks.get("obsidian", {})
    if obsidian.get("ok") is False and obsidian.get("required"):
        actions.append(
            {
                "id": "obsidian_dependency_missing",
                "severity": "required",
                "message": "Obsidian CLI/installer dependency check failed",
                "command_hint": "Install/update Obsidian installer (>=1.12.4) and ensure `obsidian` is in PATH",
            }
        )

    return actions


@span("health.check")
def run_health(*, trace_id: str | None = None, **kwargs: Any) -> Dict[str, Any]:
    trace_id = with_trace_id(trace_id)
    checks = {
        "ffmpeg": _annotate_required(_check_ffmpeg(), required=False),
        "yt_dlp": _annotate_required(_check_yt_dlp(), required=False),
        "index_outbox": _annotate_required(_check_outbox_path(), required=True),
        "panel_actions": _annotate_required(_check_panel_actions(), required=False),
        "ollama": _annotate_required(_check_ollama(), required=_ollama_required()),
        "obsidian": _annotate_required(_check_obsidian_dependencies(), required=_obsidian_required()),
    }
    checks["llm_router"] = _annotate_required(_check_llm_router(), required=False)
    checks["llm_providers"] = _annotate_required(_check_llm_providers(checks["ollama"]), required=False)

    runtime = {
        "watcher": _watcher_runtime_status(),
        "worker": _worker_runtime_status(),
        "db": _db_runtime_status(),
        "llm": _llm_runtime_status(checks["ollama"]),
    }
    checks_ok = _checks_ok(checks)
    runtime_ok = _runtime_ok(runtime)
    ok = bool(checks_ok and runtime_ok)
    required_ok = bool(_required_checks_ok(checks) and runtime_ok)
    suggested_actions = _suggested_actions(checks, runtime)
    return {"ok": ok, "required_ok": required_ok, "checks": checks, "runtime": runtime, "trace_id": trace_id, "suggested_actions": suggested_actions}
__all__ = ["run_health"]
