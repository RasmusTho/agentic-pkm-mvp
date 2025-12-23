from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.outbox.events import INDEX_OUTBOX_PATH


def default_outbox_path() -> Path:
    return Path(INDEX_OUTBOX_PATH)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def read_outbox(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or default_outbox_path()
    return read_jsonl(target.expanduser())


def _timestamp(rec: dict[str, Any]) -> str:
    return str(rec.get("timestamp") or rec.get("created_at") or "").strip()


def _trace_id(rec: dict[str, Any]) -> str:
    return str(rec.get("trace_id") or "").strip()


def _event_name(rec: dict[str, Any]) -> str:
    return str(rec.get("event") or rec.get("event_type") or "").strip()


def _stage(event: str) -> str:
    if not event:
        return "unknown"
    return event.split(".", 1)[0]


def _pick_trace_id(rows: list[dict[str, Any]], trace_id: str, latest: bool) -> str:
    if trace_id:
        return trace_id
    if not latest:
        return ""
    for rec in reversed(rows):
        tid = _trace_id(rec)
        if tid:
            return tid
    return ""


def _build_story(rows: list[dict[str, Any]], trace_id: str) -> dict[str, Any]:
    filtered = [r for r in rows if _trace_id(r) == trace_id] if trace_id else []
    events: list[dict[str, Any]] = []
    stages: list[str] = []
    for r in filtered:
        ev = _event_name(r)
        st = _stage(ev)
        if st not in stages:
            stages.append(st)
        events.append(
            {
                "event": ev,
                "timestamp": _timestamp(r),
                "source": r.get("source"),
                "event_id": r.get("event_id"),
                "stage": st,
            }
        )
    first_ts = events[0]["timestamp"] if events else ""
    last_ts = events[-1]["timestamp"] if events else ""
    return {
        "trace_id": trace_id,
        "count": len(events),
        "stages": stages,
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
        "events": events,
    }


def latest_trace_story(rows: list[dict[str, Any]]) -> dict[str, Any]:
    trace_id = _pick_trace_id(rows, trace_id="", latest=True)
    if not trace_id:
        return {}
    return _build_story(rows, trace_id)


def normalize_timestamp(record: dict[str, Any]) -> str:
    return _timestamp(record)


def event_name(record: dict[str, Any]) -> str:
    return _event_name(record)


__all__ = [
    "default_outbox_path",
    "read_jsonl",
    "read_outbox",
    "latest_trace_story",
    "normalize_timestamp",
    "event_name",
]
