from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable

_DEFAULT_ENV = "WATCHER_HEARTBEAT_PATH"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HEARTBEAT_PATH = REPO_ROOT / "tmp" / "watcher_heartbeat.json"


def resolve_heartbeat_path(env_get: Callable[[str], str | None] | None = None) -> Path:
    getter = env_get or os.getenv
    raw = getter(_DEFAULT_ENV)
    if raw and raw.strip():
        return Path(raw.strip()).expanduser()
    return DEFAULT_HEARTBEAT_PATH


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
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        return


__all__ = ["DEFAULT_HEARTBEAT_PATH", "resolve_heartbeat_path", "write_heartbeat"]
