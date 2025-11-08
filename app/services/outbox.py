from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Tuple

__all__ = [
    "bootstrap",
    "poll_outbox_one",
    "write_outbox_event",
    "insert_object_and_outbox",
]

# --------- helpers (DB-agnostisk) ---------
def _is_conn(x: Any) -> bool:
    return hasattr(x, "execute") or (hasattr(x, "cursor") and callable(getattr(x, "cursor", None)))

def _exec(conn: Any, sql: str, params: Optional[Tuple[Any, ...]] = None):
    try:
        return conn.execute(sql, params) if params is not None else conn.execute(sql)
    except TypeError:
        if params is None:
            return conn.execute(sql)
        return conn.execute(sql.replace("%s", "?"), params)

def _now() -> datetime:
    return datetime.now(timezone.utc)

def _file_fallback(topic: str, payload: dict[str, Any]) -> None:
    line = json.dumps({"ts": _now().isoformat(), "topic": topic, "payload": payload, "sink": "file:fallback"})
    with open("events.jsonl", "a", encoding="utf-8") as f:
        f.write(line + "\n")

# --------- public API ---------
def bootstrap(conn: Any | None = None) -> None:
    if conn is None:
        try:
            from app.db import conn_rw as _conn_rw
            conn = _conn_rw()
        except Exception:
            pass
    _exec(conn, """
        create table if not exists outbox(
          id bigserial primary key,
          topic text not null,
          payload jsonb not null,
          created_at timestamptz not null default now(),
          delivered_at timestamptz null,
          attempts int not null default 0
        )
    """)
    _exec(conn, "create index if not exists outbox_delivered_idx on outbox(delivered_at)")

def write_outbox_event(conn_or_none: Any, topic: str, payload: dict[str, Any]) -> None:
    safe_payload = json.loads(json.dumps(payload))
    if _is_conn(conn_or_none):
        _exec(
            conn_or_none,
            "insert into outbox (topic, payload, created_at, attempts) values (%s, %s, %s, %s)",
            (topic, json.dumps(safe_payload), _now(), 0),
        )
    else:
        _file_fallback(topic, safe_payload)

def insert_object_and_outbox(*args, **kwargs) -> None:
    # New signature: (conn, obj_uuid, event)
    # Legacy signature(s): (event_dict, topic=None, trace_id=None, conn=None)  OR (payload, topic, trace_id)
    if not args:
        raise TypeError("insert_object_and_outbox requires at least one argument")

    conn = None
    obj_uuid = None
    event: dict[str, Any] = {}

    if _is_conn(args[0]):  # new style
        if len(args) < 3:
            raise TypeError("insert_object_and_outbox(conn, obj_uuid, event) requires 3 positional args")
        conn, obj_uuid, event = args[0], args[1], args[2]
        if not isinstance(event, dict):
            raise TypeError("event must be a dict")
    else:  # legacy styles
        maybe_event = args[0]
        if isinstance(maybe_event, dict):
            event = dict(maybe_event)
        else:
            event = {}
        if len(args) > 1 and isinstance(args[1], str):
            event.setdefault("event", args[1])
        conn = kwargs.get("conn")
        obj_uuid = kwargs.get("obj_uuid") or kwargs.get("uuid") or event.get("uuid") or event.get("object_id")

    topic = event.get("event") or kwargs.get("topic") or "unknown.event"
    payload = dict(event)
    if obj_uuid is not None and "object_id" not in payload:
        payload["object_id"] = str(obj_uuid)

    write_outbox_event(conn, topic, payload)

def poll_outbox_one(conn: Any | None = None, handler: callable | None = None):
    if conn is None:
        try:
            from app.db import conn_rw as _conn_rw
            conn = _conn_rw()
        except Exception:
            pass
    row = _exec(conn, "select id, topic, payload from outbox where delivered_at is null order by created_at asc limit 1").fetchone()
if not row:
    return False if handler else None if handler else None if handler else None
    eid, topic, payload = row
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {"raw": payload}

    try:
        handler(topic, payload)
        _exec(conn, "update outbox set delivered_at=%s, attempts=attempts+1 where id=%s", (_now(), eid))
    except Exception:
        _exec(conn, "update outbox set attempts=attempts+1 where id=%s", (eid,))
        raise
    return True

# __OUTBOX_COMPAT_WRAPPERS__
# Tillåt både nya (bootstrap(conn), poll_outbox_one(conn, handler)->bool)
# och gamla (bootstrap(), poll_outbox_one()->dict|None) anropsmönster.
try:
    _bootstrap_impl = bootstrap  # type: ignore[name-defined]
except Exception:
    _bootstrap_impl = None

def _outbox_conn():
    try:
        from app.db import conn_rw
        return conn_rw()
    except Exception:
        return None

if _bootstrap_impl is not None:
    def bootstrap(*args, **kwargs):  # type: ignore[override]
        if args or kwargs:
            return _bootstrap_impl(*args, **kwargs)
        conn = _outbox_conn()
        if conn is None:
            return None
        return _bootstrap_impl(conn)

try:
    _poll_impl = poll_outbox_one  # type: ignore[name-defined]
except Exception:
    _poll_impl = None

if _poll_impl is not None:
    def poll_outbox_one(*args, **kwargs):  # type: ignore[override]
        # Ny signatur? Delegera som vanligt.
        if args or kwargs:
            return _poll_impl(*args, **kwargs)
        # Gammal signatur: hämta ett meddelande och returnera dict.
        conn = _outbox_conn()
        if conn is None:
            return None
        captured = {}
        def _cap(topic, payload):
            captured["topic"] = topic
            captured["payload"] = payload
        processed = _poll_impl(conn, _cap)
        if not processed:
            return None
        return captured
