from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.events.schema import OutboxEvent, make_outbox_event
from app.events.types import PROMOTE_DONE, PROMOTE_ERROR, PROMOTE_INTENT_CREATED
from app.outbox.events import INDEX_OUTBOX_PATH
from app.store.object_store import ObjectStore


def _read_outbox(path: Path) -> Iterable[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            continue
    return records


def _write_outbox(path: Path, events: Iterable[OutboxEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for ev in events:
            handle.write(json.dumps(ev.model_dump(mode="json"), ensure_ascii=False) + "\n")


def _apply_promotion(note_uuid: str, desired_state: str, trace_id: str | None) -> bool:
    store = ObjectStore()
    obj = store.get_object(note_uuid)
    if obj is None:
        return False
    payload = dict(obj.payload or {})
    promotion_meta = {
        "state": desired_state,
        "applied_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    payload["promotion"] = promotion_meta
    payload["review_state"] = desired_state
    obj.payload = payload
    store.save_object(obj, emit_outbox=False, trace_id=trace_id)
    return True


def consume_promotion_intents(*, outbox_path: Path | None = None, limit: int | None = None) -> dict:
    resolved_outbox = Path(outbox_path) if outbox_path else Path(INDEX_OUTBOX_PATH)
    records = _read_outbox(resolved_outbox)
    emitted: list[OutboxEvent] = []
    summary = {"intents_seen": 0, "applied": 0, "errors": 0, "emitted": 0}

    for rec in records:
        if rec.get("event") != PROMOTE_INTENT_CREATED:
            continue
        summary["intents_seen"] += 1
        if limit is not None and summary["applied"] >= limit:
            continue
        payload = rec.get("payload") or {}
        note = payload.get("note") or {}
        note_uuid = str(note.get("uuid") or "").strip()
        desired_state = str(payload.get("maturity") or payload.get("action", {}).get("id") or "promoted")
        trace_id = rec.get("trace_id")
        event_id = rec.get("event_id")

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

        if _apply_promotion(note_uuid, desired_state, trace_id):
            summary["applied"] += 1
            emitted.append(
                make_outbox_event(
                    PROMOTE_DONE,
                    source="promotion.consumer",
                    payload={
                        "note_uuid": note_uuid,
                        "state": desired_state,
                        "source_event": event_id,
                    },
                    trace_id=trace_id,
                )
            )
        else:
            summary["errors"] += 1
            emitted.append(
                make_outbox_event(
                    PROMOTE_ERROR,
                    source="promotion.consumer",
                    payload={"reason": "not_found", "note_uuid": note_uuid, "source_event": event_id},
                    trace_id=trace_id,
                )
            )

    if emitted:
        _write_outbox(resolved_outbox, emitted)
        summary["emitted"] = len(emitted)
    return summary


__all__ = ["consume_promotion_intents"]
