from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from app.events.models import Event, new_event
from app.services.audit import audit_event

_AUDIT_CACHE: list[str] = []
_AUDIT_CACHE_LIMIT = 1024
_AUDIT_LOCK = threading.Lock()


def _serialize_event(event: Event) -> str:
    return event.model_dump_json()


def _append_cache(json_line: str) -> None:
    with _AUDIT_LOCK:
        _AUDIT_CACHE.append(json_line)
        overflow = len(_AUDIT_CACHE) - _AUDIT_CACHE_LIMIT
        if overflow > 0:
            del _AUDIT_CACHE[:overflow]


def _cache_and_maybe_persist(json_line: str) -> None:
    _append_cache(json_line)
    path = _audit_log_path()
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json_line)
        if not json_line.endswith("\n"):
            fh.write("\n")


def _audit_log_path() -> Path | None:
    raw = os.environ.get("AUDIT_LOG_PATH", "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def audit_log(
    *,
    object_id: str | None,
    agent: str,
    action: str,
    trace_id: str | None,
    details: dict | None = None,
) -> None:
    event = new_event(
        event_type=action,
        payload={"object_id": object_id, "agent": agent, "details": details or {}},
        trace_id=trace_id,
        source=agent,
    )
    json_line = _serialize_event(event)

    _cache_and_maybe_persist(json_line)
    try:
        audit_event(
            event=action,
            object_id=object_id,
            agent=agent,
            trace_id=trace_id or "",
            extra=details or {},
        )
    except Exception:
        # Best effort: fall back to cache/file only.
        return


def _audit_ring_snapshot() -> list[dict[str, Any]]:
    with _AUDIT_LOCK:
        return [json.loads(line) for line in _AUDIT_CACHE]


__all__ = ["audit_log", "_audit_ring_snapshot"]
