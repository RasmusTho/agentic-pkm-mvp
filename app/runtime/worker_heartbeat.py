from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Callable, Mapping

from app.settings.watcher_settings import load_watcher_settings

logger = logging.getLogger(__name__)

_DEFAULT_ENV = "WORKER_HEARTBEAT_PATH"
DEFAULT_WORKER_HEARTBEAT_PATH = load_watcher_settings().paths.worker_heartbeat

# World-writable (rw-rw-rw-) so any future uid on a shared runtime-tmp volume
# (#3118) can truncate/overwrite this file without hitting the root-owned,
# owner-only-write default a bare `open(..., "w")` would otherwise leave
# behind. This does not by itself fix a file that is ALREADY root-owned with
# restrictive perms from a prior write context (see `_write_payload` self-heal
# below) — it prevents the *next* fresh write from recreating the same trap.
_HEARTBEAT_FILE_MODE = 0o666


def resolve_worker_heartbeat_path(env_get: Callable[[str], str | None] | None = None) -> Path:
    getter = env_get or os.getenv
    raw = getter(_DEFAULT_ENV)
    if raw and raw.strip():
        return Path(raw.strip()).expanduser()
    return load_watcher_settings().paths.worker_heartbeat


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


def write_worker_heartbeat(
    *,
    path: Path,
    ticks_total: int,
    errors_total: int,
    outbox_path: Path,
    processed_total: int | None = None,
    processed_by_event: Mapping[str, int] | None = None,
    last_processed: Mapping[str, float] | None = None,
    status: str = "running",
    now: float | None = None,
) -> None:
    timestamp = now if now is not None else time.time()
    payload: dict[str, object] = {
        "ts": timestamp,
        "pid": os.getpid(),
        "status": status,
        "ticks_total": ticks_total,
        "errors_total": errors_total,
        "outbox_path": str(outbox_path),
    }
    if processed_total is not None:
        payload["processed_total"] = processed_total
    if processed_by_event is not None:
        payload["processed_by_event"] = {k: int(v) for k, v in processed_by_event.items()}
    if last_processed is not None:
        payload["last_processed"] = {k: float(v) for k, v in last_processed.items()}
    _write_payload(path, payload)


__all__ = [
    "DEFAULT_WORKER_HEARTBEAT_PATH",
    "resolve_worker_heartbeat_path",
    "write_worker_heartbeat",
]
