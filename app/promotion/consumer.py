from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.events.schema import OutboxEvent, make_outbox_event
from app.events.types import PROMOTE_DONE, PROMOTE_ERROR, PROMOTE_INTENT_CREATED
from app.outbox.events import INDEX_OUTBOX_PATH
from app.services.note_update import apply_promotion_frontmatter
from app.store.object_store import DomainObject, ObjectStore


def _read_outbox(path: Path, start: int = 0) -> Iterable[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines[start:] if line.strip()]


def _write_outbox(path: Path, events: Iterable[OutboxEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for ev in events:
            handle.write(json.dumps(ev.model_dump(mode="json"), ensure_ascii=False) + "\n")


def _resolve_cursor_path(outbox_path: Path, cursor_path: Path | None, snapshot_path: Path | None) -> Path | None:
    if cursor_path is not None:
        return Path(cursor_path)
    if snapshot_path is not None:
        return Path(str(snapshot_path) + ".outbox_cursor.json")
    return outbox_path.with_suffix(outbox_path.suffix + ".cursor.json")


def _load_cursor(cursor_path: Path | None, outbox_path: Path, total_lines: int) -> int:
    if cursor_path is None or not cursor_path.exists():
        return 0
    try:
        data = json.loads(cursor_path.read_text(encoding="utf-8"))
        if data.get("outbox_path") != str(outbox_path):
            return 0
        idx = int(data.get("line_index", 0))
        if idx < 0 or idx > total_lines:
            return 0
        return idx
    except Exception:
        return 0


def _save_cursor(cursor_path: Path | None, outbox_path: Path, line_index: int) -> None:
    if cursor_path is None:
        return
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"outbox_path": str(outbox_path), "line_index": line_index}
    cursor_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _apply_promotion_to_store(note_uuid: str, desired_state: str, trace_id: str | None, note_path: Path | None) -> None:
    store = ObjectStore()
    existing = store.get_object(note_uuid)
    payload = dict(existing.payload or {}) if existing else {}
    promotion_meta = {
        "state": desired_state,
        "applied_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    payload["promotion"] = promotion_meta
    payload["review_state"] = desired_state
    if existing is None:
        obj = DomainObject(
            uuid=note_uuid,
            kind="note",
            payload=payload,
            source_ref=str(note_path) if note_path else None,
            created_at=datetime.now(timezone.utc),
        )
    else:
        existing.payload = payload
        if note_path and not existing.source_ref:
            existing.source_ref = str(note_path)
        obj = existing
    store.save_object(obj, emit_outbox=False, trace_id=trace_id)


def consume_promotion_intents(
    *,
    outbox_path: Path | None = None,
    limit: int | None = None,
    cursor_path: Path | None = None,
    snapshot_path: Path | None = None,
) -> dict:
    resolved_outbox = Path(outbox_path) if outbox_path else Path(INDEX_OUTBOX_PATH)
    lines = resolved_outbox.read_text(encoding="utf-8").splitlines() if resolved_outbox.exists() else []
    resolved_cursor = _resolve_cursor_path(resolved_outbox, cursor_path, snapshot_path)
    start_idx = _load_cursor(resolved_cursor, resolved_outbox, len(lines))

    records = []
    for line in lines[start_idx:]:
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            continue

    emitted: list[OutboxEvent] = []
    summary = {"intents_seen": 0, "applied": 0, "errors": 0, "emitted": 0}

    for rec in records:
        if rec.get("event") != PROMOTE_INTENT_CREATED:
            continue
        summary["intents_seen"] += 1
        if limit is not None and summary.get("applied", 0) >= limit:
            continue
        payload = rec.get("payload") or {}
        note = payload.get("note") or {}
        note_uuid = str(note.get("uuid") or "").strip()
        note_path_value = note.get("path") or payload.get("note_path")
        desired_state = str(payload.get("maturity") or payload.get("action", {}).get("id") or "promoted")
        trace_id = rec.get("trace_id")
        event_id = rec.get("event_id")
        title = note.get("title") if isinstance(note, dict) else None

        if not note_uuid:
            summary["errors"] += 1
            emitted.append(
                make_outbox_event(
                    PROMOTE_ERROR,
                    source="promotion.consumer",
                    payload={"reason": "missing_uuid", "source_event": event_id},
                    trace_id=trace_id,
                )
            )
            continue

        if not note_path_value:
            summary["errors"] += 1
            emitted.append(
                make_outbox_event(
                    PROMOTE_ERROR,
                    source="promotion.consumer",
                    payload={"reason": "missing_note_path", "note_uuid": note_uuid, "source_event": event_id},
                    trace_id=trace_id,
                )
            )
            continue

        note_path = Path(note_path_value)
        if not apply_promotion_frontmatter(note_path, note_uuid, desired_state, optional_title=title):
            summary["errors"] += 1
            emitted.append(
                make_outbox_event(
                    PROMOTE_ERROR,
                    source="promotion.consumer",
                    payload={"reason": "path_not_found", "note_uuid": note_uuid, "note_path": str(note_path)},
                    trace_id=trace_id,
                )
            )
            continue

        _apply_promotion_to_store(note_uuid, desired_state, trace_id, note_path)
        summary["applied"] += 1
        emitted.append(
            make_outbox_event(
                PROMOTE_DONE,
                source="promotion.consumer",
                payload={
                    "note_uuid": note_uuid,
                    "note_path": str(note_path),
                    "state": desired_state,
                    "source_event": event_id,
                },
                trace_id=trace_id,
            )
        )

    if emitted:
        _write_outbox(resolved_outbox, emitted)
        summary["emitted"] = len(emitted)

    _save_cursor(resolved_cursor, resolved_outbox, len(lines))
    return summary


__all__ = ["consume_promotion_intents"]
