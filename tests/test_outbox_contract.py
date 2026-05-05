import json
from datetime import datetime, timezone

from app.events.panel import NoteRef, PanelInfo, PanelIntentExecutedEvent, PanelIntentExecutedPayload
from app.events.models import new_event
from app.events.schema import OutboxEvent
from app.events.types import INGEST_OBJECT_CREATED
from app.services.outbox import append_jsonl_outbox_event, coerce_outbox_event, serialize_outbox_record, write_outbox_event


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


def test_write_outbox_event_accepts_panel_event_source_models():
    conn = FakeConn()
    event = PanelIntentExecutedEvent(
        payload=PanelIntentExecutedPayload(
            note=NoteRef(uuid="note-1", path="Inbox/note.md"),
            panel=PanelInfo(panel_id="panel-1", instruction="Promote"),
        )
    )

    write_outbox_event(event, conn)

    assert len(conn.executed) == 1
    sql, params = conn.executed[0]
    assert "insert into outbox" in sql.lower()
    topic, payload_json, created_at, attempts = params

    assert topic == "panel.intent.executed"
    data = json.loads(payload_json)
    assert data["source"] == "panel_agent"
    assert data["payload"]["note"]["uuid"] == "note-1"
    assert data["payload"]["panel"]["panel_id"] == "panel-1"
    assert attempts == 0


def test_coerce_outbox_event_uses_typed_payload_not_full_event_envelope(tmp_path):
    event = PanelIntentExecutedEvent(
        payload=PanelIntentExecutedPayload(
            note=NoteRef(uuid="note-1", path="Inbox/note.md"),
            panel=PanelInfo(panel_id="panel-1", instruction="Promote"),
        )
    )

    outbox_event = coerce_outbox_event(event, default_source="panel_agent.runtime")

    assert outbox_event is not None
    assert outbox_event.source == "panel_agent"
    assert outbox_event.payload["note"]["uuid"] == "note-1"
    assert "event" not in outbox_event.payload

    outbox_path = tmp_path / "outbox.jsonl"
    assert append_jsonl_outbox_event(outbox_path, event, default_source="panel_agent.runtime") is True
    records = [json.loads(line) for line in outbox_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert records[0]["payload"]["panel"]["panel_id"] == "panel-1"


def test_coerce_outbox_event_preserves_context_dimensions_from_event() -> None:
    event = new_event(
        event_type=INGEST_OBJECT_CREATED,
        payload={"uuid": "abc-123"},
        trace_id="trace-ctx",
        context_dimensions={
            "scope": "work",
            "sphere_memberships": ["team"],
            "situated_identity": "maker",
        },
    )

    outbox_event = coerce_outbox_event(event)

    assert outbox_event is not None
    assert outbox_event.context_dimensions is not None
    assert outbox_event.context_dimensions["scope"] == "work"
    assert outbox_event.context_dimensions["sphere_memberships"] == ["team"]
    assert outbox_event.context_dimensions["situated_identity"] == "maker"


# --- AC: serialize_outbox_record null-omission contract (issue #756) ---


def test_serialize_outbox_record_omits_context_dimensions_when_absent() -> None:
    """OutboxEvent without context_dimensions must not emit the key at all."""
    ev = OutboxEvent(event="test.event", source="app", payload={"x": 1})
    assert ev.context_dimensions is None

    result = serialize_outbox_record(ev)

    assert result is not None
    assert "context_dimensions" not in result, (
        f"context_dimensions must be omitted when None, got: {result.get('context_dimensions')!r}"
    )


def test_serialize_outbox_record_includes_context_dimensions_when_present() -> None:
    """OutboxEvent with context_dimensions must emit the block correctly."""
    ev = OutboxEvent(
        event="test.event",
        source="app",
        payload={"x": 1},
        context_dimensions={"scope": "work", "sphere_memberships": ["team"], "situated_identity": "maker"},
    )

    result = serialize_outbox_record(ev)

    assert result is not None
    assert "context_dimensions" in result
    assert result["context_dimensions"]["scope"] == "work"
    assert result["context_dimensions"]["sphere_memberships"] == ["team"]
    assert result["context_dimensions"]["situated_identity"] == "maker"


def test_serialize_outbox_record_omits_context_dimensions_via_event_coercion() -> None:
    """Event without context_dimensions coerced through serialize_outbox_record must not emit the key."""
    event = new_event(event_type=INGEST_OBJECT_CREATED, payload={"uuid": "abc"})

    result = serialize_outbox_record(event)

    assert result is not None
    assert "context_dimensions" not in result, (
        f"context_dimensions must be omitted when None (coercion path), got: {result.get('context_dimensions')!r}"
    )


def test_append_jsonl_outbox_event_omits_context_dimensions_when_absent(tmp_path) -> None:
    """JSONL audit path must also omit context_dimensions when absent."""
    event = new_event(event_type=INGEST_OBJECT_CREATED, payload={"uuid": "abc"})
    outbox_path = tmp_path / "outbox.jsonl"

    assert append_jsonl_outbox_event(outbox_path, event) is True

    records = [json.loads(line) for line in outbox_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(records) == 1
    assert "context_dimensions" not in records[0], (
        f"JSONL record must not include context_dimensions when absent, got: {records[0].get('context_dimensions')!r}"
    )
