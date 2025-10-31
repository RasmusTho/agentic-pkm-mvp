import json
from datetime import datetime, timezone
from app.services.outbox import write_outbox_event

class FakeConn:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params):
        self.executed.append((sql.strip(), params))

def test_write_outbox_event_serializes_payload():
    conn = FakeConn()
    payload = {
        "event": "ingest.object.created",
        "uuid": "abc-123",
        "kind": "capture_note",
        "trace_id": "trace-1",
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    write_outbox_event(conn, "ingest.object.created", payload)

    assert len(conn.executed) == 1
    sql, params = conn.executed[0]

    assert "insert into outbox" in sql.lower()
    topic, payload_json, created_at, attempts = params

    assert topic == "ingest.object.created"
    data = json.loads(payload_json)
    assert data["uuid"] == "abc-123"
    assert data["kind"] == "capture_note"
    assert data["event"] == "ingest.object.created"
    assert attempts == 0
