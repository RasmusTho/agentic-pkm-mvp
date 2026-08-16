"""Lean worker/watcher heartbeat probe used by Docker healthchecks.

This module deliberately imports only the standard library.  It is invoked by
Docker directly, so importing ``app.cli`` here would make every healthcheck
load the API, HTTP, LLM, and database stacks.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

_TRUE_VALUES = {"1", "true", "yes", "on"}
_DEFAULT_TIMEOUT_SECONDS = 10


def _env_float(name: str, fallback: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return fallback
    try:
        return float(raw)
    except (TypeError, ValueError):
        return fallback


def _is_enabled(env_name: str, default: bool = True) -> bool:
    raw = os.getenv(env_name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


def _heartbeat_status(
    *, name: str, path: Path, stale_seconds: float, now: float, skip: bool = False
) -> dict[str, Any]:
    """Return the existing heartbeat freshness payload without runtime imports."""
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
    except TimeoutError:
        raise
    except Exception as exc:
        return {
            "ok": False,
            "detail": f"{name} heartbeat malformed ({type(exc).__name__})",
            "path": str(path),
            "status": "malformed",
        }
    try:
        ts_value = float(raw.get("ts"))
    except (TypeError, ValueError):
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
    reported_status = str(raw.get("status") or "").strip().lower()
    binding_blocked = (
        name == "worker"
        and reported_status == "blocked_pending_mvr06"
        and ok
    )
    if binding_blocked:
        ok = False
    paused_value = bool(raw.get("paused", False))
    payload: dict[str, Any] = {
        "ok": ok,
        "detail": (
            f"{name} blocked by pending binding-incompatible outbox rows"
            if binding_blocked
            else f"{name} running (fresh {freshness:.1f}s, paused={paused_value})"
            if ok
            else f"{name} stale (last seen {freshness:.1f}s ago)"
        ),
        "path": str(path),
        "freshness_seconds": freshness,
        "paused": paused_value,
        "status": (
            "blocked_pending_mvr06"
            if binding_blocked
            else "ok"
            if ok
            else "stale"
        ),
    }
    for key in (
        "pid", "scope_glob", "ticks_total", "errors_total", "vault_path", "outbox_path",
        "processed_total", "enqueue_failures_total",
        "binding_blocked_pending",
    ):
        if key in raw:
            payload[key] = raw[key]
    if isinstance(raw.get("watchers"), dict):
        payload["watchers"] = raw["watchers"]
    return payload


def _watcher_runtime_status(now: float | None = None) -> dict[str, Any]:
    return _heartbeat_status(
        name="watcher",
        path=_resolve_watcher_heartbeat_path(),
        stale_seconds=_env_float("WATCHER_HEARTBEAT_STALE_SECONDS", 60.0),
        now=time.time() if now is None else now,
    )


def _worker_runtime_status(now: float | None = None) -> dict[str, Any]:
    backend = (os.getenv("STORE_BACKEND") or "memory").strip().lower()
    return _heartbeat_status(
        name="worker",
        path=_resolve_worker_heartbeat_path(),
        stale_seconds=_env_float("WORKER_HEARTBEAT_STALE_SECONDS", 60.0),
        now=time.time() if now is None else now,
        skip=not _is_enabled("WORKER_ENABLE", default=backend != "memory"),
    )


def _resolve_watcher_heartbeat_path() -> Path:
    """Use the configured host resolver when Compose has not set the path.

    Containers provide ``WATCHER_HEARTBEAT_PATH`` explicitly.  Keeping the
    settings-backed resolver as the unset fallback preserves the CLI/API
    contract for host invocations without adding that import to the probe's
    module-load graph.
    """
    raw = os.getenv("WATCHER_HEARTBEAT_PATH")
    if raw and raw.strip():
        return Path(raw.strip()).expanduser()
    from app.watcher.heartbeat import resolve_heartbeat_path

    return resolve_heartbeat_path()


def _resolve_worker_heartbeat_path() -> Path:
    """Use the configured host resolver when Compose has not set the path."""
    raw = os.getenv("WORKER_HEARTBEAT_PATH")
    if raw and raw.strip():
        return Path(raw.strip()).expanduser()
    from app.runtime.worker_heartbeat import resolve_worker_heartbeat_path

    return resolve_worker_heartbeat_path()


def _timeout_handler(_signum: int, _frame: object) -> None:
    raise TimeoutError("health probe deadline exceeded")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] not in {"worker", "watcher"}:
        print("usage: python -m app.runtime.health_probe worker|watcher", file=sys.stderr)
        return 64
    timeout = max(1, int(_env_float("HEALTH_PROBE_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS)))
    previous = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(timeout)
    try:
        status = _worker_runtime_status() if argv[0] == "worker" else _watcher_runtime_status()
        return 0 if status.get("ok") else 1
    except TimeoutError:
        return 2
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


if __name__ == "__main__":
    raise SystemExit(main())
