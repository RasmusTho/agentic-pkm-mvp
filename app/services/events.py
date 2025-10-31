import json, os, uuid, datetime
from typing import Any, Dict, Optional

EVENT_LOG = os.getenv("EVENT_LOG", "events.jsonl")

def new_trace_id() -> str:
    return uuid.uuid4().hex

def emit(topic: str, payload: Dict[str,Any], trace_id: Optional[str] = None) -> str:
    tid = trace_id or new_trace_id()
    rec = {
        "topic": topic,
        "trace_id": tid,
        "ts": datetime.datetime.now(datetime.UTC).isoformat() + "Z",
        "payload": payload,
    }
    with open(EVENT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return tid
