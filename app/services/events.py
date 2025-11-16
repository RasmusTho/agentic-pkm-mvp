import json
import os
from typing import Any, Dict, Optional

from app.events.models import new_event, new_trace_id

EVENT_LOG = os.getenv("EVENT_LOG", "events.jsonl")


def emit(topic: str, payload: Dict[str, Any], trace_id: Optional[str] = None, source: str | None = None) -> str:
    event = new_event(event_type=topic, payload=payload, trace_id=trace_id or new_trace_id(), source=source)
    record = event.model_dump()
    with open(EVENT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return event.trace_id or ""


__all__ = ["emit"]
