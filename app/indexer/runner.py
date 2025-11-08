from __future__ import annotations

import json
from pathlib import Path
from typing import List

from app.indexer.consumer import process_event
from app.outbox import events as outbox_events


def _load_events(path: Path) -> List[dict]:
    if not path.exists():
        return []
    events: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(evt, dict):
                events.append(evt)
    # Truncate file after reading
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return events


def main() -> None:
    path = outbox_events.INDEX_OUTBOX_PATH
    events = _load_events(path)
    if not events:
        print("indexer: no events found")
        return

    processed = 0
    for evt in events:
        process_event(evt)
        processed += 1
    print(f"indexer: processed {processed} events")


if __name__ == "__main__":
    main()
