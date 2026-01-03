from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable, Mapping

_DEFAULT_ENV = "WORKER_HEARTBEAT_PATH"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKER_HEARTBEAT_PATH = REPO_ROOT / "tmp" / "worker_heartbeat.json"


def resolve_worker_heartbeat_path(env_get: Callable[[str], str | None] | None = None) -> Path:
    getter = env_get or os.getenv
    raw = getter(_DEFAULT_ENV)
    if raw and raw.strip():
        return Path(raw.strip()).expanduser()
    return DEFAULT_WORKER_HEARTBEAT_PATH


def _write_payload(path: Path, payload: dict[str, object]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        return


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
