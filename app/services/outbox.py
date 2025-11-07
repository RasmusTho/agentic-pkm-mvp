from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Tuple

# ---------- helpers (no psycopg import at import-time) ----------

def _now() -> datetime:
    return datetime.now(timezone.utc)

def _json_clone(x: Any) -> Any:
    # ensure json-serializable
    return json.loads(json.dumps(x))

def _fallback_events_path() -> Path:
    return Path("events.jsonl")

def _fallback_write(topic: str, payload: dict[str, Any]) -> None:
    p = _fallback_events_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": _now().isoformat(), "topic": topic, "payload": payload, "sink": "file:fallback"}
    p.write_text((p.read_text(encoding="utf-8") if p.exists() else "") + json.dumps(rec) + "\n", encoding="utf-8")

def _connect_if_needed(conn) -> Tuple[Optional[Any], bool]:
    """
    Returns (conn, owned). If owned=True, caller should close it.
    Lazy-import psycopg only if we actually need a connection.
    """
    if conn is not None:
        return conn, False
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        return None, False
    try:
        import psycopg  # type: ignore
        c = psycopg.connect(dsn)
        return c, True
    except Exception:
        return None, False

def _exec(conn, sql: str, params: tuple[Any, ...]) -> None:
    # Support psycopg3 connections (cursor()) and generic .execute()-style
    if hasattr(conn, "execute"):
        conn.execute(sql, params)  # type: ignore[attr-defined]
    else:
        cur = None
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
        finally:
            try:
                cur and cur.close()
            except Exception:
                pass

# ---------- public API ----------

def write_outbox_event(conn, topic: str, payload: dict[str, Any]) -> None:
    """
    Minimal, v4.4-style outbox write.
    Assumes table 'outbox(topic text, payload jsonb, created_at timestamptz default now(), delivered_at timestamptz, attempts int)'
    """
    safe_payload = _json_clone(payload)
    _exec(conn,
          "insert into outbox (topic, payload, created_at, attempts) values (%s, %s, %s, %s)",
          (topic, json.dumps(safe_payload), _now(), 0))

def insert_object_and_outbox(*args, **kwargs) -> None:
    """
    Back-compat shim.

    New style: insert_object_and_outbox(conn, obj_uuid, event_dict_with_event_key)
      -> uses provided conn

    Legacy style: insert_object_and_outbox(payload_dict, topic_str, trace_id=None)
      -> opens a connection from DATABASE_URL if available; otherwise logs to events.jsonl
    """
    # New-style detection: first arg is a connection-like object
    if args and hasattr(args[0], "cursor") or (args and hasattr(args[0], "execute")):
        conn = args[0]
        event = args[2] if len(args) >= 3 else kwargs.get("event", {}) or {}
        topic = event.get("event", "unknown.event")
        safe = {}
        for k, v in event.items():
            # strip obvious connection-like objects
            if hasattr(v, "cursor") and hasattr(v, "execute"):
                continue
            safe[k] = v
        write_outbox_event(conn, topic, safe)
        return

    # Legacy path
    payload = args[0] if len(args) >= 1 and isinstance(args[0], dict) else (kwargs.get("payload") or {})
    topic = args[1] if len(args) >= 2 and isinstance(args[1], str) else (kwargs.get("topic") or "unknown.event")
    trace_id = args[2] if len(args) >= 3 else kwargs.get("trace_id")

    event: dict[str, Any] = dict(payload)
    event.setdefault("event", topic)
    if trace_id is not None:
        event["trace_id"] = trace_id

    conn, owned = _connect_if_needed(kwargs.get("conn"))
    if not conn:
        # no DB available → file fallback
        _fallback_write(topic, event)
        return
    try:
        write_outbox_event(conn, topic, event)
        # Commit if psycopg3 connection
        try:
            conn.commit()
        except Exception:
            pass
    finally:
        if owned:
            try:
                conn.close()
            except Exception:
                pass

def bootstrap(conn=None) -> bool:
    """
    Ensure outbox table exists. Returns True if a DB connection was used.
    """
    sql = """
    create table if not exists outbox(
      id bigserial primary key,
      topic text not null,
      payload jsonb not null default '{}'::jsonb,
      created_at timestamptz not null default now(),
      delivered_at timestamptz null,
      attempts int not null default 0
    );"""
    c, owned = _connect_if_needed(conn)
    if not c:
        return False
    try:
        _exec(c, sql, tuple())
        try:
            c.commit()
        except Exception:
            pass
        return True
    finally:
        if owned:
            try:
                c.close()
            except Exception:
                pass

def poll_outbox_one(conn=None, handler: Optional[Callable[[str, dict[str, Any]], None]] = None) -> bool:
    """
    Poll one undelivered outbox row, call handler(topic, payload), mark delivered.
    Returns True if a row was processed, False otherwise.
    """
    c, owned = _connect_if_needed(conn)
    if not c:
        return False
    try:
        # BEGIN
        try:
            c.execute("begin")
        except Exception:
            pass

        row = None
        try:
            cur = c.cursor()
            cur.execute(
                "select id, topic, payload from outbox where delivered_at is null order by id asc limit 1 for update skip locked"
            )
            row = cur.fetchone()
            cur.close()
        except Exception:
            # fallback to connection-level API if present
            try:
                row = c.execute(
                    "select id, topic, payload from outbox where delivered_at is null order by id asc limit 1 for update skip locked"
                ).fetchone()
            except Exception:
                row = None

        if not row:
            try:
                c.rollback()
            except Exception:
                pass
            return False

        oid, topic, payload = row[0], row[1], row[2]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {"raw": payload}

        if handler:
            handler(topic, payload)

        _exec(c, "update outbox set delivered_at = %s, attempts = attempts + 1 where id = %s", (_now(), oid))
        try:
            c.commit()
        except Exception:
            pass
        return True
    finally:
        if owned:
            try:
                c.close()
            except Exception:
                pass

__all__ = [
    "write_outbox_event",
    "insert_object_and_outbox",
    "bootstrap",
    "poll_outbox_one",
]
