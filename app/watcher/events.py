from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from pydantic import BaseModel, Field

from app.version import SOT_FORWARD


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


class WatcherEventSource(BaseModel):
    component: str = "watcher"
    trigger: str = "runtime_loop"
    sot: str = SOT_FORWARD


class WatcherRunPayload(BaseModel):
    changed: int
    ingest_attempted: int
    ingested: int
    panel_candidates: int
    panel_runs: int
    panel_promotions: int
    panel_skipped_policy: int
    panel_skipped_limit: int
    errors: int
    dry_run: bool
    limit_exceeded: bool
    snapshot_path: str
    vault_root: str


class WatcherRunEvent(BaseModel):
    event: str = "watcher.run"
    version: str = "1.0"
    timestamp: str = Field(default_factory=_now_iso)
    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    source: WatcherEventSource
    payload: WatcherRunPayload


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def build_watcher_run_event(
    summary: Mapping[str, Any],
    *,
    vault_root: Path,
    snapshot_path: str | Path | None,
    trigger: str,
    trace_id: str | None = None,
) -> WatcherRunEvent:
    payload = WatcherRunPayload(
        changed=_coerce_int(summary.get("changed")),
        ingest_attempted=_coerce_int(summary.get("ingest_attempted")),
        ingested=_coerce_int(summary.get("ingested")),
        panel_candidates=_coerce_int(summary.get("panel_candidates")),
        panel_runs=_coerce_int(summary.get("panel_runs")),
        panel_promotions=_coerce_int(summary.get("panel_promotions")),
        panel_skipped_policy=_coerce_int(summary.get("panel_skipped_policy")),
        panel_skipped_limit=_coerce_int(summary.get("panel_skipped_limit")),
        errors=_coerce_int(summary.get("errors")),
        dry_run=bool(summary.get("dry_run")),
        limit_exceeded=bool(summary.get("limit_exceeded")),
        snapshot_path=str(snapshot_path or summary.get("snapshot_path") or ""),
        vault_root=str(vault_root),
    )
    return WatcherRunEvent(
        trace_id=trace_id or uuid4().hex,
        source=WatcherEventSource(trigger=trigger),
        payload=payload,
    )


def emit_watcher_run_event(
    summary: Mapping[str, Any],
    *,
    vault_root: Path,
    snapshot_path: str | Path | None,
    outbox_path: Path,
    trigger: str,
    trace_id: str | None = None,
) -> WatcherRunEvent:
    event = build_watcher_run_event(
        summary,
        vault_root=vault_root,
        snapshot_path=snapshot_path,
        trigger=trigger,
        trace_id=trace_id,
    )
    path = Path(outbox_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False))
        handle.write("\n")
    return event


__all__ = [
    "WatcherEventSource",
    "WatcherRunPayload",
    "WatcherRunEvent",
    "build_watcher_run_event",
    "emit_watcher_run_event",
]
