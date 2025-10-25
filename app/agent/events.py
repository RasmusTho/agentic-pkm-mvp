from dataclasses import dataclass
from typing import Any, Dict, Optional
import time
import uuid

EventName = str

def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def new_trace_id() -> str:
    return uuid.uuid4().hex

@dataclass
class Event:
    name: EventName
    payload: Dict[str, Any]
    trace_id: str
    occurred_at: str

INGEST_OBJECT_CREATED: EventName = "ingest.object.created"
INDEX_OBJECT_EMBEDDED: EventName = "index.object.embedded"

def make_event(name: EventName, payload: Dict[str, Any], trace_id: Optional[str] = None) -> Event:
    return Event(name=name, payload=payload, trace_id=trace_id or new_trace_id(), occurred_at=now_iso())
