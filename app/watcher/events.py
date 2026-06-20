from __future__ import annotations

import json
import os
from datetime import timezone, datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from pydantic import BaseModel, Field

from app.version import SOT_FORWARD

# Default max size (bytes) for the dedicated watcher_run telemetry log before rotation.
# Overridable via WATCHER_RUN_LOG_MAX_BYTES env variable.
_WATCHER_RUN_LOG_MAX_BYTES_DEFAULT = 10 * 1024 * 1024  # 10 MB


def _watcher_run_log_max_bytes() -> int:
    raw = os.getenv("WATCHER_RUN_LOG_MAX_BYTES", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return _WATCHER_RUN_LOG_MAX_BYTES_DEFAULT


def _rotate_if_needed(path: Path, max_bytes: int) -> None:
    """Rotate path -> path.1 when path exceeds max_bytes. Keeps one backup."""
    try:
        if path.exists() and path.stat().st_size >= max_bytes:
            backup = path.with_suffix(path.suffix + ".1")
            path.replace(backup)
    except OSError:
        pass


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


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
    panel_skipped_auto_exec: int = 0
    panel_skipped_allowed_actions: int = 0
    skipped_dedup: int = 0
    skipped_idempotent: int = 0
    skipped_writes_blocked: int = 0
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
        panel_skipped_auto_exec=_coerce_int(summary.get("panel_skipped_auto_exec")),
        panel_skipped_allowed_actions=_coerce_int(summary.get("panel_skipped_allowed_actions")),
        skipped_dedup=_coerce_int(summary.get("skipped_dedup")),
        skipped_idempotent=_coerce_int(summary.get("skipped_idempotent")),
        skipped_writes_blocked=_coerce_int(summary.get("skipped_writes_blocked")),
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
    telemetry_log_path: Path,
    trigger: str,
    trace_id: str | None = None,
) -> WatcherRunEvent:
    """Emit a watcher.run event to the DEDICATED telemetry log.

    The telemetry log is separate from index-outbox.jsonl (the index/embedding
    audit sink). Per-tick watcher.run records must never land in index-outbox
    because they bloat it unboundedly (observed: 1.78 GB / 2.58M lines).

    A simple size-based rotation is applied before each append: when the log
    exceeds WATCHER_RUN_LOG_MAX_BYTES (default 10 MB) it is moved to
    <path>.1 and a fresh log is started.
    """
    event = build_watcher_run_event(
        summary,
        vault_root=vault_root,
        snapshot_path=snapshot_path,
        trigger=trigger,
        trace_id=trace_id,
    )
    path = Path(telemetry_log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _rotate_if_needed(path, _watcher_run_log_max_bytes())
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
