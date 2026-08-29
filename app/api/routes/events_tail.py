from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.events.outbox import default_outbox_path
from app.services.outbox import JsonlOutboxCorruptionError, read_jsonl_outbox_records

router = APIRouter()
_EVENTS_TAIL_BYTES = 8 * 1024 * 1024


def _resolve_outbox_path() -> Path:
    raw = os.getenv("INDEX_OUTBOX_PATH")
    if raw:
        return Path(raw).expanduser()
    return default_outbox_path().expanduser()


def _load_events(path: Path) -> list[dict[str, Any]]:
    return read_jsonl_outbox_records(
        path,
        max_bytes=_EVENTS_TAIL_BYTES,
        read_only=True,
    )


@router.get("/events/tail")
async def events_tail(
    limit: int = Query(default=50, ge=1, le=500),
    event_prefix: str | None = Query(default=None),
    trace_id: str | None = Query(default=None),
) -> dict[str, Any]:
    path = _resolve_outbox_path()
    try:
        records = _load_events(path)
    except JsonlOutboxCorruptionError as exc:
        raise HTTPException(
            status_code=503,
            detail="configured event outbox is unreadable",
        ) from exc
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
