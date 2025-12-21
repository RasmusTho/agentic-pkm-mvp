from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from app.outbox.events import INDEX_OUTBOX_PATH

router = APIRouter()

_TIMESTAMP_FIELDS: Sequence[str] = ("timestamp", "ts", "time", "created", "emitted_at")


def _resolve_outbox_path() -> Path:
    raw = os.getenv("INDEX_OUTBOX_PATH")
    if raw:
        return Path(raw).expanduser()
    return Path(INDEX_OUTBOX_PATH).expanduser()


def _load_raw_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []


def _normalize_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        iso = value.strip()
        if not iso:
            return None
        if iso.endswith("Z") and not iso.endswith("+00:00"):
            iso = iso[:-1] + "+00:00"
        try:
            datetime.fromisoformat(iso)
            return iso
        except ValueError:
            return iso
    if isinstance(value, int | float):
        try:
            return datetime.fromtimestamp(value, tz=UTC).isoformat()
        except Exception:
            return None
    return None


def _extract_timestamp(payload: dict[str, Any]) -> str | None:
    for key in _TIMESTAMP_FIELDS:
        candidate = payload.get(key)
        normalized = _normalize_timestamp(candidate)
        if normalized:
            return normalized
    return None


def _extract_event(payload: dict[str, Any]) -> str | None:
    candidate = payload.get("event") or payload.get("event_type") or payload.get("topic")
    if candidate is None:
        return None
    value = str(candidate).strip()
    return value if value else None


def _scan_events(path: Path) -> tuple[list[dict[str, Any]], int, int, int]:
    lines = _load_raw_lines(path)
    scanned = 0
    parse_errors = 0
    dropped_missing_fields = 0
    collected: list[dict[str, Any]] = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        scanned += 1
        try:
            payload = json.loads(raw)
        except Exception:
            parse_errors += 1
            continue
        if not isinstance(payload, dict):
            dropped_missing_fields += 1
            continue
        event_name = _extract_event(payload)
        timestamp = _extract_timestamp(payload)
        if not event_name or not timestamp:
            dropped_missing_fields += 1
            continue
        trace_value = payload.get("trace_id")
        collected.append({
            "timestamp": timestamp,
            "event": event_name,
            "trace_id": str(trace_value) if trace_value is not None else None,
            "data": payload,
        })
    return collected, scanned, parse_errors, dropped_missing_fields


@router.get("/events/tail")
async def events_tail(
    limit: int = Query(default=50, ge=1, le=500),
    event_prefix: str | None = Query(default=None),
    trace_id: str | None = Query(default=None),
) -> dict[str, Any]:
    path = _resolve_outbox_path()
    events, scanned, parse_errors, dropped_missing_fields = _scan_events(path)
    filtered: list[dict[str, Any]] = []
    for entry in events:
        if event_prefix and not entry["event"].startswith(event_prefix):
            continue
        if trace_id and entry.get("trace_id") != trace_id:
            continue
        filtered.append(entry)

    selected = filtered[-limit:][::-1]
    return {
        "ok": True,
        "source_path": str(path),
        "returned": len(selected),
        "scanned": scanned,
        "parse_errors": parse_errors,
        "dropped_missing_fields": dropped_missing_fields,
        "limit": limit,
        "events": selected,
    }


@router.get("/events/raw_tail")
async def events_raw_tail(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
    path = _resolve_outbox_path()
    lines = _load_raw_lines(path)
    selected = lines[-limit:][::-1]
    return {
        "ok": True,
        "source_path": str(path),
        "returned": len(selected),
        "limit": limit,
        "lines": selected,
    }


__all__ = ["router"]
