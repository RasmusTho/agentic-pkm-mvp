from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from app.settings.watcher_settings import load_watcher_settings

logger = logging.getLogger(__name__)

_DEFAULT_ENV = "WATCHER_HEARTBEAT_PATH"
DEFAULT_HEARTBEAT_PATH = load_watcher_settings().paths.watcher_heartbeat

# World-writable (rw-rw-rw-) so any future uid on a shared runtime-tmp volume
# (#3118) can truncate/overwrite this file without hitting the root-owned,
# owner-only-write default a bare `open(..., "w")` would otherwise leave
# behind. This does not by itself fix a file that is ALREADY root-owned with
# restrictive perms from a prior write context (see `_write_payload` self-heal
# below) — it prevents the *next* fresh write from recreating the same trap.
_HEARTBEAT_FILE_MODE = 0o666


def resolve_heartbeat_path(env_get: Callable[[str], str | None] | None = None) -> Path:
    getter = env_get or os.getenv
    raw = getter(_DEFAULT_ENV)
    if raw and raw.strip():
        return Path(raw.strip()).expanduser()
    return load_watcher_settings().paths.watcher_heartbeat


def _write_payload(path: Path, payload: dict[str, object]) -> None:
    """Write the heartbeat JSON payload, self-healing past a stale root-owned file.

    Background (#3118): a shared `runtime-tmp` volume file can end up owned by
    a different uid than the current writer (e.g. an earlier container run
    under `LOCAL_UID=0`/root before host-uid remapping was wired, or any
    out-of-band root write). `Path.write_text` opens the existing file
    O_TRUNC, which is governed by the FILE's own permission bits versus the
    caller's uid/gid — the parent directory's `chmod 1777` has no bearing on
    an in-place open-for-write, only on creating a NEW directory entry. When
    the existing file is not writable by this process, plain truncate-write
    raises `PermissionError` every tick, forever, with the previous (stale)
    content left on disk — the exact silent, permanently-stale failure mode
    from the issue.

    Self-heal strategy: on `PermissionError`, try to remove the stale file and
    recreate it fresh. This succeeds whenever this process owns the file, owns
    the parent directory, or the parent directory is not sticky (POSIX
    `unlink(2)`/`rename(2)` "restricted deletion" rules: sticky-bit dirs only
    allow the file owner, directory owner, or root/CAP_FOWNER to unlink or
    rename over an existing entry). It cannot succeed against a file that is
    root-owned inside a sticky (mode 1777) directory while this process is a
    non-root, non-owning uid — that specific combination has no unprivileged
    fix (verified against `unlink(2)`/`rename(2)` restricted-deletion
    semantics) and requires an out-of-band chown or a privileged container
    init step, which is out of scope here (see "Out of Scope" on #3118). In
    that unrecoverable case, the failure is logged loudly instead of silently
    discarded, so `/api/health` staleness is diagnosable instead of a silent
    mystery.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        logger.error("heartbeat write failed: could not create parent dir %s", path.parent, exc_info=True)
        return

    encoded = json.dumps(payload, ensure_ascii=False)

    def _write_fresh() -> None:
        path.write_text(encoded, encoding="utf-8")
        try:
            os.chmod(path, _HEARTBEAT_FILE_MODE)
        except OSError:
            # Best-effort: chmod failing (e.g. we don't own the file we just
            # wrote, on a filesystem with unusual semantics) does not mean the
            # write itself failed.
            logger.warning("heartbeat chmod failed for %s", path, exc_info=True)

    try:
        _write_fresh()
        return
    except PermissionError:
        logger.warning(
            "heartbeat write hit PermissionError on %s (likely stale root-owned "
            "file from an earlier write context, #3118) — attempting self-heal "
            "by removing and recreating the file",
            path,
        )
    except Exception:
        logger.error("heartbeat write failed for %s", path, exc_info=True)
        return

    try:
        path.unlink(missing_ok=True)
        _write_fresh()
        logger.info("heartbeat self-heal succeeded for %s", path)
    except Exception:
        logger.error(
            "heartbeat self-heal FAILED for %s — file is likely owned by a "
            "different uid inside a sticky-bit directory and cannot be "
            "recovered without an out-of-band chown (manual remedy: "
            "`chown <runtime-uid> %s`, or delete it as root/owner)",
            path,
            path,
            exc_info=True,
        )


def write_heartbeat(
    *,
    path: Path,
    vault_path: Path,
    scope_glob: str,
    outbox_path: Path,
    ticks_total: int,
    errors_total: int,
    paused: bool,
    now: float | None = None,
) -> None:
    timestamp = now if now is not None else time.time()
    payload = {
        "ts": timestamp,
        "pid": os.getpid(),
        "paused": paused,
        "vault_path": str(vault_path),
        "scope_glob": scope_glob,
        "outbox_path": str(outbox_path),
        "ticks_total": ticks_total,
        "errors_total": errors_total,
    }
    _write_payload(path, payload)


def write_runtime_heartbeat(
    *,
    path: Path | None = None,
    ticks: int,
    changed: int,
    errors: int,
    status: str = "running",
    now: float | None = None,
) -> None:
    resolved = path or resolve_heartbeat_path()
    timestamp = now if now is not None else time.time()
    payload = {
        "ts": timestamp,
        "pid": os.getpid(),
        "status": status,
        "ticks": ticks,
        "changed": changed,
        "errors": errors,
    }
    _write_payload(resolved, payload)
    return resolved


def write_registry_heartbeat(
    *,
    path: Path,
    status: str,
    watchers: Mapping[str, Mapping[str, object]],
    outbox_path: Path | None = None,
    vault_path: Path | None = None,
    config_path: Path | None = None,
    paused: bool | None = None,
    enqueue_failures_total: int | None = None,
    now: float | None = None,
) -> None:
    timestamp = now if now is not None else time.time()
    payload: dict[str, object] = {
        "ts": timestamp,
        "pid": os.getpid(),
        "status": status,
        "watchers": {name: dict(stats) for name, stats in watchers.items()},
    }
    if outbox_path is not None:
        payload["outbox_path"] = str(outbox_path)
    if vault_path is not None:
        payload["vault_path"] = str(vault_path)
    if config_path is not None:
        payload["config_path"] = str(config_path)
    if paused is not None:
        payload["paused"] = paused
    if enqueue_failures_total is not None:
        payload["enqueue_failures_total"] = enqueue_failures_total
    _write_payload(path, payload)


__all__ = [
    "DEFAULT_HEARTBEAT_PATH",
    "resolve_heartbeat_path",
    "write_heartbeat",
    "write_runtime_heartbeat",
    "write_registry_heartbeat",
]
