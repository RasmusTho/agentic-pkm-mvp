from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from app.domain.state_axes import normalize_promotion_payload, resolve_promotion_axes
from app.events.schema import OutboxEvent, make_outbox_event
from app.events.types import PROMOTE_DONE, PROMOTE_ERROR, PROMOTE_INTENT_CREATED, PROMOTION_TRANSITION_APPLIED
from app.events.models import new_event
from app.outbox.events import INDEX_OUTBOX_PATH
from app.services.note_update import apply_promotion_frontmatter
from app.components.concurrency import EventDedupStore
from app.objects import DomainObject, ObjectStore
from app.services.outbox import write_outbox_event


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

_PROMOTION_DEDUP = EventDedupStore()


def _apply_promotion_to_store(
    note_uuid: str,
    maturity: str | None,
    review_state: str,
    trace_id: str | None,
    note_path: Path | None,
) -> None:
    store = ObjectStore()
    existing = store.get_object(note_uuid)
    payload = dict(existing.payload or {}) if existing else {}
    promotion_meta = {
        "state": maturity or review_state,
        "applied_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    payload["promotion"] = promotion_meta
    if maturity:
        payload["maturity"] = maturity
    payload["review_state"] = review_state
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


def _emit_jsonl_event(events: list[OutboxEvent], event_type: str, payload: dict, trace_id: str | None) -> None:
    events.append(make_outbox_event(event_type, source="promotion.consumer", payload=payload, trace_id=trace_id))


def _emit_db_event(event_type: str, payload: dict, trace_id: str | None) -> None:
    event = new_event(event_type=event_type, payload=payload, trace_id=trace_id, source="promotion.consumer")
    write_outbox_event(event)


def _handle_promotion_payload(
    payload: Mapping[str, object],
    *,
    trace_id: str | None,
    event_id: str | None,
    emit,
) -> dict:
    summary = {"intents_seen": 1, "applied": 0, "errors": 0, "emitted": 0, "skipped_duplicates": 0}
    if event_id and _PROMOTION_DEDUP.seen(event_id):
        summary["skipped_duplicates"] += 1
        return summary

    note = payload.get("note") or {}
    note_uuid = str(note.get("uuid") or "").strip() if isinstance(note, dict) else ""
    note_path_value = None
    if isinstance(note, dict):
        note_path_value = note.get("path")
        title = note.get("title")
    else:
        title = None
    if not note_path_value:
        note_path_value = payload.get("note_path") if isinstance(payload, dict) else None
    normalized_payload = normalize_promotion_payload(payload)
    axes = resolve_promotion_axes(
        maturity=normalized_payload.get("maturity"),
        review_state=normalized_payload.get("review_state"),
    )

    if not note_uuid:
        summary["errors"] += 1
        emit(
            PROMOTE_ERROR,
            {"reason": "missing_uuid", "source_event": event_id},
            trace_id,
        )
        summary["emitted"] += 1
        return summary

    if not note_path_value:
        summary["errors"] += 1
        emit(
            PROMOTE_ERROR,
            {"reason": "missing_note_path", "note_uuid": note_uuid, "source_event": event_id},
            trace_id,
        )
        summary["emitted"] += 1
        return summary

    note_path = Path(str(note_path_value))
    if not apply_promotion_frontmatter(
        note_path,
        note_uuid,
        axes.review_state,
        optional_title=title,
        maturity=axes.maturity,
    ):
        summary["errors"] += 1
        emit(
            PROMOTE_ERROR,
            {
                "reason": "path_not_found",
                "note_uuid": note_uuid,
                "note_path": str(note_path),
                "source_event": event_id,
            },
            trace_id,
        )
        summary["emitted"] += 1
        return summary

    _apply_promotion_to_store(
        note_uuid,
        axes.maturity,
        axes.review_state,
        trace_id,
        note_path,
    )
    summary["applied"] += 1
    emit(
        PROMOTE_DONE,
        {
            "note_uuid": note_uuid,
            "note_path": str(note_path),
            "state": axes.maturity or axes.review_state,
            "maturity": axes.maturity,
            "review_state": axes.review_state,
            "source_event": event_id,
        },
        trace_id,
    )
    summary["emitted"] += 1
    transition = payload.get("transition") if isinstance(payload, Mapping) else None
    transition_family = "promotion"
    target_maturity = axes.maturity
    if isinstance(transition, Mapping):
        transition_family = str(transition.get("family") or transition_family)
        target_maturity = str(transition.get("target_maturity") or target_maturity or "") or target_maturity
    emit(
        PROMOTION_TRANSITION_APPLIED,
        {
            "intent_event_id": event_id,
            "trace_id": trace_id,
            "note_uuid": note_uuid,
            "note_path": str(note_path),
            "transition_family": transition_family,
            "target_maturity": target_maturity,
            "executor": "promotion.consumer",
            "effect": "applied",
            "source_event": event_id,
            "verb": str(payload.get("trust_verb") or "APPLY").strip().upper(),
            "authority": {
                "mode": "governed_execution",
                "component": "panel_agent.runtime",
                "executor": "promotion.consumer",
            },
            "basis": {
                "source_event": event_id,
                "intent_type": "promotion",
            },
            "outcome": {
                "status": "applied",
                "review_state": axes.review_state,
                "maturity": axes.maturity,
            },
            "artifact_linkage": {
                "note_uuid": note_uuid,
                "note_path": str(note_path),
            },
            "instance_provenance": {
                "source": "promotion.consumer",
                "trace_id": trace_id,
            },
        },
        trace_id,
    )
    summary["emitted"] += 1
    return summary


def consume_promotion_intent_payload(
    payload: Mapping[str, object],
    *,
    trace_id: str | None = None,
    event_id: str | None = None,
) -> dict:
    return _handle_promotion_payload(
        payload,
        trace_id=trace_id,
        event_id=event_id,
        emit=_emit_db_event,
    )


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
    summary = {"intents_seen": 0, "applied": 0, "errors": 0, "emitted": 0, "skipped_duplicates": 0}

    for rec in records:
        if rec.get("event") != PROMOTE_INTENT_CREATED:
            continue
        summary["intents_seen"] += 1
        if limit is not None and summary.get("applied", 0) >= limit:
            continue
        payload = rec.get("payload") or {}
        trace_id = rec.get("trace_id")
        event_id = rec.get("event_id")
        result = _handle_promotion_payload(
            payload,
            trace_id=trace_id,
            event_id=event_id,
            emit=lambda event_type, payload, trace: _emit_jsonl_event(emitted, event_type, payload, trace),
        )
        summary["applied"] += result.get("applied", 0)
        summary["errors"] += result.get("errors", 0)
        summary["emitted"] += result.get("emitted", 0)
        summary["skipped_duplicates"] += result.get("skipped_duplicates", 0)

    if emitted:
        _write_outbox(resolved_outbox, emitted)

    _save_cursor(resolved_cursor, resolved_outbox, len(lines))
    return summary



def reset_promotion_dedup_store() -> None:
    _PROMOTION_DEDUP.clear()

__all__ = ["consume_promotion_intents", "consume_promotion_intent_payload", "reset_promotion_dedup_store"]
