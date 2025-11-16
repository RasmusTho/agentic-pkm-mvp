import json
from datetime import datetime, timezone

from app.events.models import new_event
from app.events.types import INGEST_OBJECT_CREATED
from app.services.outbox import write_outbox_event


class FakeConn:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params):
        self.executed.append((sql.strip(), params))


def test_write_outbox_event_serializes_payload():
    conn = FakeConn()
    payload = {
        "event": INGEST_OBJECT_CREATED,
        "uuid": "abc-123",
        "kind": "capture_note",
        "trace_id": "trace-1",
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    event = new_event(event_type=INGEST_OBJECT_CREATED, payload=payload, trace_id=payload["trace_id"])
    write_outbox_event(event, conn)

    assert len(conn.executed) == 1
    sql, params = conn.executed[0]

    assert "insert into outbox" in sql.lower()
    topic, payload_json, created_at, attempts = params

    assert topic == INGEST_OBJECT_CREATED
    data = json.loads(payload_json)
    assert data["event_type"] == INGEST_OBJECT_CREATED
    assert data["payload"]["uuid"] == "abc-123"
    assert data["payload"]["kind"] == "capture_note"
    assert data["payload"]["event"] == INGEST_OBJECT_CREATED
    assert attempts == 0
