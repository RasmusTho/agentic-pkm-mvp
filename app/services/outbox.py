from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple

from app.events.models import Event, new_event
from app.events.schema import OutboxEvent

# Optional DB helpers (tests kan ge FakeConn)
try:
    from app.db import conn_rw, ensure_schema  # type: ignore
except Exception:  # pragma: no cover
    conn_rw = None  # type: ignore

    def ensure_schema(_):  # type: ignore
        return None


def _open_conn():
    if conn_rw:
        try:
            return conn_rw()
        except Exception:
            pass
    import psycopg

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    try:
        from app.db.dsn import resolve_dsn

        url = resolve_dsn(url)
    except Exception:
        if url.startswith("postgresql+psycopg://"):
            url = "postgresql://" + url.split("postgresql+psycopg://", 1)[1]
    return psycopg.connect(url, autocommit=True)


def _use_conn(maybe_conn: Any) -> Tuple[Any, bool]:
    """Return (conn, should_close)."""
    if maybe_conn is None:
        return _open_conn(), True
    return maybe_conn, False


def _exec(conn: Any, sql: str, params: tuple = ()) -> Any:
    if hasattr(conn, "cursor"):
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur
    if hasattr(conn, "execute"):
        return conn.execute(sql, params)

    class _Dummy:
        def fetchone(self):
            return None

        def fetchall(self):
            return []

    return _Dummy()


def bootstrap(conn: Any = None) -> None:
    """Initiera outbox-tabellen. Valfritt extern conn för tester."""
    conn, close = _use_conn(conn)
    try:
        try:
            ensure_schema(conn)  # type: ignore[arg-type]
        except Exception:
            pass
        _exec(conn, "create extension if not exists pgcrypto")
        _exec(
            conn,
            """
        create table if not exists outbox (
            id uuid primary key default gen_random_uuid(),
            topic text not null,
            payload jsonb not null,
            created_at timestamptz not null default now(),
            delivered_at timestamptz,
            attempts int not null default 0
        )""",
        )
        _exec(conn, "create index if not exists outbox_created_idx on outbox (created_at)")
        _exec(conn, "create index if not exists outbox_delivered_idx on outbox (delivered_at)")
    finally:
        if close:
            conn.close()


def _coerce_event(event: Event | OutboxEvent) -> Event:
    if isinstance(event, Event):
        return event
    return new_event(
        event_type=event.event,
        payload=dict(event.payload),
        trace_id=event.trace_id,
        source=event.source,
        event_id=event.event_id,
        created_at=event.timestamp,
    )


def write_outbox_event(event: Event | OutboxEvent, conn: Any = None) -> str:
    envelope = _coerce_event(event)
    conn, close = _use_conn(conn)
    stored = envelope.model_dump_json()
    created_at = envelope.created_at or datetime.now(timezone.utc)
    try:
        cur = _exec(
            conn,
            "insert into outbox (topic, payload, created_at, attempts) values (%s, %s::jsonb, %s, %s) returning id",
            (envelope.event_type, stored, created_at, 0),
        )
        if hasattr(cur, "fetchone"):
            row = cur.fetchone()
            if row:
                return str(row[0])
        return ""
    finally:
        if close:
            conn.close()


def insert_object_and_outbox(
    payload: Dict[str, Any],
    topic: str,
    trace_id: str | None = None,
    *,
    object_id: str | None = None,
    source: str | None = None,
    conn: Any = None,
) -> str:
    """Helper som bygger ett Event och skickar det till outbox."""
    data = dict(payload or {})
    if object_id:
        data.setdefault("object_id", object_id)
    if trace_id:
        data.setdefault("trace_id", trace_id)
    data.setdefault("event", topic)
    event = new_event(event_type=topic, payload=data, trace_id=trace_id, source=source)
    return write_outbox_event(event, conn=conn)


def _coerce_event_from_db(raw_payload: Any, topic: str) -> Event:
    if isinstance(raw_payload, Event):
        return raw_payload
    if isinstance(raw_payload, OutboxEvent):
        return _coerce_event(raw_payload)
    if isinstance(raw_payload, str):
        try:
            raw_payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            raw_payload = {"event": topic}
    if isinstance(raw_payload, dict) and "event_type" in raw_payload:
        return Event.model_validate(raw_payload)
    payload = dict(raw_payload or {}) if isinstance(raw_payload, dict) else {}
    event_type = payload.get("event") or topic
    trace_id = payload.get("trace_id")
    source = payload.get("agent")
    return new_event(event_type=event_type, payload=payload, trace_id=trace_id, source=source)


def poll_outbox_one(
    conn: Any = None,
    handler: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Returnerar nästa odelivererade meddelande som dict, eller None.
    Om handler ges: handler(topic, payload) anropas, men dict returneras ändå.
    """
    conn, close = _use_conn(conn)
    try:
        cur = _exec(conn, "select id, topic, payload from outbox where delivered_at is null order by created_at asc limit 1")
        row = cur.fetchone()
        if not row:
            return None
        event = _coerce_event_from_db(row[2], row[1])
        msg = {"id": str(row[0]), "topic": event.event_type, "payload": dict(event.payload), "event": event}
        if handler:
            try:
                handler(event.event_type, event.payload)
            except Exception:
                # Handler-fel får inte blocka polling i worker
                pass
        return msg
    finally:
        if close:
            conn.close()


def ack_outbox(*args, **kwargs) -> bool:
    """
    Stödjer:
      ack_outbox(conn, msg_id)
      ack_outbox(msg_id)
    """
    if len(args) == 2:
        conn, msg_id = args
        close = False
    elif len(args) == 1:
        msg_id = args[0]
        conn, close = _use_conn(None)
    else:
        conn = kwargs.get("conn")
        msg_id = kwargs["msg_id"]
        conn, close = _use_conn(conn)

    try:
        cur = _exec(
            conn,
            "update outbox set delivered_at = now() where id = %s and delivered_at is null returning 1",
            (msg_id,),
        )
        return bool(cur.fetchone())
    finally:
        if close:
            conn.close()


__all__ = ["write_outbox_event", "insert_object_and_outbox", "poll_outbox_one", "ack_outbox", "bootstrap"]
