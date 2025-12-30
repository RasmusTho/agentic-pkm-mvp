from __future__ import annotations

import json
from pathlib import Path
from typing import List

from app.components.concurrency import EventDedupStore, SystemClock
from app.indexer.consumer import process_event
from app.outbox import events as outbox_events

_EVENT_DEDUP = EventDedupStore(SystemClock(), ttl_seconds=3600.0)


def _load_events(path: Path) -> List[dict]:
    if not path.exists():
        return []

    to_process: list[dict] = []
    retained: list[dict] = []

    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(evt, dict):
                continue

            event_type = str(evt.get("event") or "").strip()
            is_request = event_type == outbox_events.INDEX_EMBEDDING_REQUESTED
            is_legacy_embedded = "embedding" in evt and "object_id" in evt

            if is_request or is_legacy_embedded:
                to_process.append(evt)
            else:
                retained.append(evt)

    # Rewrite file with retained events only (acts as an append-only log for non-queue records).
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for evt in retained:
            fh.write(json.dumps(evt, ensure_ascii=False) + "\n")

    return to_process


def _event_id_from_record(evt: dict) -> str:
    event_id = evt.get("event_id")
    return str(event_id).strip() if event_id else ""


def main() -> None:
    path = outbox_events.INDEX_OUTBOX_PATH
    events = _load_events(path)
    if not events:
        print("indexer: no events found")
        return

    processed = 0
    for evt in events:
        event_id = _event_id_from_record(evt)
        if event_id and _EVENT_DEDUP.seen(event_id):
            continue
        process_event(evt)
        processed += 1
    print(f"indexer: processed {processed} events")


if __name__ == "__main__":
    main()
