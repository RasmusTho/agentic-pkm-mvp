from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

router = APIRouter()


def _resolve_outbox_path() -> Path:
    raw = os.getenv("INDEX_OUTBOX_PATH", "./tmp/index-outbox.jsonl")
    return Path(raw).expanduser()


def _load_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


@router.get("/events/tail")
async def events_tail(
    limit: int = Query(default=50, ge=1, le=500),
    event_prefix: str | None = Query(default=None),
    trace_id: str | None = Query(default=None),
) -> dict[str, Any]:
    path = _resolve_outbox_path()
    records = _load_events(path)
    filtered: list[dict[str, Any]] = []
    for rec in records:
        ev = rec.get("event") or rec.get("event_type") or rec.get("topic") or ""
        if event_prefix and not str(ev).startswith(event_prefix):
            continue
        if trace_id and rec.get("trace_id") != trace_id:
            continue
        filtered.append(rec)

    selected = filtered[-limit:][::-1]
    return {
        "events": selected,
        "count": len(selected),
        "source_path": str(path),
        "limit": limit,
    }


__all__ = ["router"]
