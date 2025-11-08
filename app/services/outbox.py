from __future__ import annotations

import os
from datetime import datetime, timezone
import json
from typing import Any, Callable, Dict, Optional, Tuple

# Optional DB helpers (tests kan ge FakeConn)
try:
    from app.db import conn_rw, ensure_schema  # type: ignore
except Exception:  # pragma: no cover
    conn_rw = None  # type: ignore
    def ensure_schema(_):  # type: ignore
        return None

def _open_conn():
    if conn_rw:
        return conn_rw()
    import psycopg
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg.connect(url)

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
        def fetchone(self): return None
        def fetchall(self): return []
    return _Dummy()

def bootstrap(conn: Any = None) -> None:
    """Initiera outbox-tabellen. Valfritt extern conn för tester."""
    conn, close = _use_conn(conn)
    try:
        try:
            ensure_schema(conn)  # type: ignore[arg-type]
        except Exception:
            pass
        _exec(conn, """
        create table if not exists outbox (
            id uuid primary key default gen_random_uuid(),
            topic text not null,
            payload jsonb not null,
            created_at timestamptz not null default now(),
            delivered_at timestamptz,
            attempts int not null default 0
        )""")
        _exec(conn, "create index if not exists outbox_created_idx on outbox (created_at)")
        _exec(conn, "create index if not exists outbox_delivered_idx on outbox (delivered_at)")
    finally:
        if close:
            conn.close()

def write_outbox_event(*args, **kwargs) -> str:
    """
    Stödjer både:
      write_outbox_event(conn, topic, payload)
      write_outbox_event(topic, payload)
    """
    if len(args) == 3:
        conn, topic, payload = args
        close = False
    elif len(args) == 2:
        topic, payload = args
        conn, close = _use_conn(None)
    else:
        # kwargs-stöd som nödlösning
        conn = kwargs.get("conn")
        topic = kwargs["topic"]
        payload = kwargs["payload"]
        conn, close = _use_conn(conn)

    stored = payload if isinstance(payload, str) else json.dumps(payload or {})
    created_at = datetime.now(timezone.utc)
    try:
        cur = _exec(conn,
              "insert into outbox (topic, payload, created_at, attempts) values (%s, %s::jsonb, %s, %s) returning id",
              (topic, stored, created_at, 0))
        if hasattr(cur, "fetchone"):
            row = cur.fetchone()
            if row:
                return str(row[0])
        return ""
    finally:
        if close:
            conn.close()

def insert_object_and_outbox(*args, **kwargs) -> str:
    """
    Stödjer:
      insert_object_and_outbox(conn, object_id, topic, payload)
      insert_object_and_outbox(object_id, topic, payload)
    """
    if len(args) == 4:
        conn, object_id, topic, payload = args
        close = False
    elif len(args) == 3:
        object_id, topic, payload = args
        conn, close = _use_conn(None)
    else:
        conn = kwargs.get("conn")
        object_id = kwargs["object_id"]
        topic = kwargs["topic"]
        payload = kwargs["payload"]
        conn, close = _use_conn(conn)

    data = dict(payload or {})
    data.setdefault("object_id", object_id)
    try:
        return write_outbox_event(conn, topic, data)
    finally:
        if close:
            conn.close()

def poll_outbox_one(conn: Any = None, handler: Optional[Callable[[str, Dict[str, Any]], None]] = None) -> Optional[Dict[str, Any]]:
    """
    Returnerar nästa odelivererade meddelande som dict, eller None.
    Om handler ges: handler(topic, payload) anropas, men dict returneras ändå.
    """
    conn, close = _use_conn(conn)
    try:
        cur = _exec(conn,
            "select id, topic, payload from outbox where delivered_at is null order by created_at asc limit 1")
        row = cur.fetchone()
        if not row:
            return None
        msg = {"id": str(row[0]), "topic": row[1], "payload": row[2]}
        if handler:
            try:
                handler(msg["topic"], msg["payload"])
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
        cur = _exec(conn,
            "update outbox set delivered_at = now() where id = %s and delivered_at is null returning 1",
            (msg_id,))
        return bool(cur.fetchone())
    finally:
        if close:
            conn.close()
