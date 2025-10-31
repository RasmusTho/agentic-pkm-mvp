from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

# NOTE:
# We keep insert_object_and_outbox(...) for backward compatibility,
# but ObjectStore will use write_outbox_event(...) instead.


def write_outbox_event(conn, topic: str, payload: dict[str, Any]) -> None:
    """
    Minimal, v4.4-style outbox write.
    Assumes `outbox(topic text, payload jsonb, created_at timestamptz default now(), delivered_at timestamptz, attempts int)`
    """
    # Ensure payload is JSON-serializable before sending to DB
    safe_payload = json.loads(json.dumps(payload))

    conn.execute(
        """
        insert into outbox (topic, payload, created_at, attempts)
        values (%s, %s, %s, %s)
        """,
        (
            topic,
            json.dumps(safe_payload),
            datetime.now(timezone.utc),
            0,
        ),
    )


def insert_object_and_outbox(conn, obj_uuid: str, event: dict[str, Any]) -> None:
    """
    Legacy helper.
    Historically this might have inserted/updated the object row AND emitted the outbox message,
    all in a single transaction.
    In that world it could capture connection state or other rich objects in `event`.

    We are keeping this function so old code paths don't break,
    but new code (ObjectStore, Promotion Agent, etc.) should call write_outbox_event(...)
    with an explicit topic and a clean payload dict.
    """
    # We'll degrade the "legacy" helper to just forward to write_outbox_event
    # with a conventional topic. We assume event["event"] is the topic.
    topic = event.get("event", "unknown.event")

    # remove keys that are obviously non-serializable if they exist
    safe_event = {}
    for k, v in event.items():
        # Skip psycopg connections or other non-serializable objects
        if hasattr(v, "cursor") and hasattr(v, "execute"):
            continue
        safe_event[k] = v

    write_outbox_event(conn, topic, safe_event)
