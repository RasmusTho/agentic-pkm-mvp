"""Lean, self-terminating container healthcheck probe for the worker/watcher.

This module is the canonical home for the runtime *heartbeat* status logic
(`_worker_runtime_status` / `_watcher_runtime_status`) and the executable probe
invoked by the Docker `healthcheck` of the worker and watcher containers.

Why this lives here and not in `app.cli.health`
------------------------------------------------
The Docker healthcheck runs a *fresh* Python process every interval. Importing
`app.cli.health` (the old probe) transitively imports the `app.cli` package,
whose ``__init__`` pulls in ``click``, ``httpx``, ``watchfiles`` and the entire
ingest/LLM/DB stack, plus ``app.cli.health``'s own heavy imports (httpx, LLM
fabric, DB health, eval client, api seams). A cold import of that graph under a
resource-constrained runtime can take longer than the healthcheck ``timeout``.

That slow probe caused a real, unbounded resource leak on the test channel:

* The containers run without an init/reaper (``docker ... --init`` / compose
  ``init: true`` was unset), so PID 1 is the entrypoint shell — it never
  ``wait()``s on orphaned children.
* The healthcheck was invoked via ``CMD-SHELL`` (``sh -c "python ..."``). On
  timeout Docker kills the ``sh`` wrapper, but the heavy ``python`` import child
  is reparented to the non-reaping PID 1 and keeps running.
* Every interval spawns another one. Under load they get slower, time out more,
  and accumulate — a thundering-herd feedback loop (observed load average in the
  hundreds with dozens of stuck probes), while the container reports
  ``unhealthy`` regardless of the actual heartbeat freshness.

This module breaks that loop three ways, in addition to the compose-level fixes
(direct ``CMD`` exec form + ``init: true`` + ``interval > timeout``):

1. **Tiny import graph.** Only stdlib is imported at module load; the heartbeat
   path resolvers are imported lazily inside the probe, *after* the self-timeout
   alarm is armed. No ``app.cli``, no httpx, no LLM/DB stack.
2. **Self-imposed hard deadline.** ``main`` arms ``SIGALRM`` before doing any
   work, so the probe process terminates itself well within budget even if an
   import wedges — it can never accumulate, independent of Docker's (historically
   unreliable) timeout enforcement.
3. **Single source of truth.** ``app.cli.health`` re-imports the status
   functions from here, so the CLI/`/api/health` path and the container probe
   can never disagree on the heartbeat computation.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict

_TRUE_VALUES = {"1", "true", "yes", "on"}


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


def _exception_kind(exc: Exception) -> str:
    return type(exc).__name__


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
            "detail": f"{name} heartbeat malformed ({_exception_kind(exc)})",
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
    watchers_raw = raw.get("watchers")
    if isinstance(watchers_raw, dict):
        payload["watchers"] = watchers_raw
    return payload


def _watcher_runtime_status(now: float | None = None) -> Dict[str, Any]:
    # Lazy import: keeps this module's top-level import graph stdlib-only so the
    # probe process arms its self-timeout before touching settings/YAML loading.
    from app.watcher.heartbeat import resolve_heartbeat_path

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
    # Lazy import: see `_watcher_runtime_status`.
    from app.runtime.worker_heartbeat import resolve_worker_heartbeat_path

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


_TARGETS = {
    "worker": _worker_runtime_status,
    "watcher": _watcher_runtime_status,
}


def _probe_timeout_seconds() -> float:
    # Self-imposed deadline, independent of Docker's `timeout`. Kept comfortably
    # below the compose healthcheck timeout so the process exits on its own
    # terms (non-zero) rather than being force-killed — or, on a broken runtime,
    # never killed at all.
    return _env_float("HEALTHCHECK_PROBE_TIMEOUT_SECONDS", 10.0)


def main(argv: list[str] | None = None) -> int:
    """Entry point for `python -m app.runtime.health_probe worker|watcher`.

    Exit 0 when the target runtime heartbeat is fresh/ok, 1 otherwise (including
    on self-timeout). Never blocks past the self-imposed deadline.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    target = args[0].strip().lower() if args else ""
    status_fn = _TARGETS.get(target)
    if status_fn is None:
        sys.stderr.write(
            f"health_probe: unknown target {target!r}; expected one of {sorted(_TARGETS)}\n"
        )
        return 2

    # Arm the self-timeout FIRST, before the lazy settings imports and the file
    # read, so a wedged import or I/O can never let this process linger and
    # accumulate. SIGALRM is only available on POSIX, which is the only place
    # containers run.
    deadline = _probe_timeout_seconds()
    armed = hasattr(signal, "SIGALRM") and deadline > 0
    if armed:

        def _on_timeout(signum: int, frame: Any) -> None:  # noqa: ARG001
            sys.stderr.write(
                f"health_probe: {target} probe exceeded self-timeout "
                f"({deadline:.1f}s); exiting unhealthy\n"
            )
            os._exit(1)

        signal.signal(signal.SIGALRM, _on_timeout)
        signal.setitimer(signal.ITIMER_REAL, deadline)

    try:
        result = status_fn()
    except Exception as exc:  # pragma: no cover - defensive; probe must not crash-hang
        sys.stderr.write(f"health_probe: {target} probe error ({_exception_kind(exc)})\n")
        return 1
    else:
        return 0 if result.get("ok") else 1
    finally:
        # Disarm the itimer once the work is done. The container process exits
        # immediately after `main`, but when `main` is called in-process (tests,
        # or any embedding caller) a still-armed itimer would fire later and the
        # `os._exit(1)` handler would kill the *host* process. Always disarm.
        if armed:
            signal.setitimer(signal.ITIMER_REAL, 0)


__all__ = [
    "_env_float",
    "_is_enabled",
    "_heartbeat_status",
    "_worker_runtime_status",
    "_watcher_runtime_status",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
