from __future__ import annotations

import hashlib
import json
import os
import uuid as uuid_module
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from app.events.models import Event, new_event
from app.events.schema import OutboxEvent
from app.events.topic_schema_registry import (
    current_schema_ref,
    is_registered_topic,
    validate_topic_payload,
)

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

    url = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
    if not url:
        raise RuntimeError("DATABASE_URL or DB_DSN not set")
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


def event_source_name(value: Any, *, default: str = "app") -> str:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or default
    component = getattr(value, "component", None)
    if component:
        return str(component)
    return default


def event_payload_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dict(dumped) if isinstance(dumped, dict) else {}
    if hasattr(value, "dict"):
        dumped = value.dict()  # type: ignore[call-arg]
        return dict(dumped) if isinstance(dumped, dict) else {}
    try:
        return dict(value)
    except Exception:
        return {}


def coerce_outbox_event(event: Any, *, default_source: str = "app") -> OutboxEvent | None:
    if isinstance(event, OutboxEvent):
        return event
    if isinstance(event, Event):
        return OutboxEvent(
            event=event.event_type,
            event_id=event.event_id,
            trace_id=event.trace_id or "",
            source=event_source_name(event.source, default=default_source),
            timestamp=event.created_at,
            payload=event_payload_dict(event.payload),
            context_dimensions=getattr(event, "context_dimensions", None),
        )
    event_name = getattr(event, "event", None) or getattr(event, "event_type", None)
    if not event_name:
        return None
    payload = event_payload_dict(getattr(event, "payload", None))
    trace_id = getattr(event, "trace_id", None) or ""
    event_id = getattr(event, "event_id", None) or ""
    timestamp = getattr(event, "timestamp", None) or getattr(event, "created_at", None) or ""
    return OutboxEvent(
        event=str(event_name),
        event_id=str(event_id),
        trace_id=str(trace_id),
        source=event_source_name(getattr(event, "source", None), default=default_source),
        timestamp=str(timestamp),
        payload=payload,
    )


def serialize_outbox_record(event: Any, *, default_source: str = "app") -> dict[str, Any] | None:
    if isinstance(event, dict):
        return dict(event)
    if hasattr(event, "model_dump"):
        dumped = event.model_dump(mode="json", exclude_none=True)
        if isinstance(dumped, dict):
            return dumped
    coerced = coerce_outbox_event(event, default_source=default_source)
    if coerced is None:
        return None
    return coerced.model_dump(mode="json", exclude_none=True)


def append_jsonl_outbox_event(outbox_path: Path, event: Any, *, default_source: str = "app") -> bool:
    record = serialize_outbox_record(event, default_source=default_source)
    if record is None:
        return False
    outbox_path.parent.mkdir(parents=True, exist_ok=True)
    with outbox_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False))
        handle.write("\n")
    return True


def _coerce_event(event: Event | OutboxEvent) -> Event:
    if isinstance(event, Event):
        return event
    payload = event_payload_dict(getattr(event, "payload", None))
    meta = getattr(event, "meta", None)
    return new_event(
        event_type=event.event,
        payload=dict(payload),
        context_dimensions=getattr(event, "context_dimensions", None),
        trace_id=event.trace_id,
        source=event_source_name(getattr(event, "source", None), default="app"),
        event_id=event.event_id,
        created_at=event.timestamp,
        meta=dict(meta) if isinstance(meta, dict) else None,
    )


# Fixed UUIDv5 namespace for deterministic outbox idempotency keys (KERNEL-02).
# Changing this value changes every derived key and breaks replay dedup — never rotate it.
OUTBOX_IDEMPOTENCY_NAMESPACE = uuid_module.UUID("6f0f5a5e-2764-5b8e-9d3a-1c9e02764a02")

# Canonical content-fingerprint label for emissions keyed on their own
# ``event_id`` (panel projections, capture receipts, index-embedding requests).
# Honest scope: event_id is random per constructed event, so this dedups only
# a double-insert of the SAME in-memory event object (producer retry after a
# partial failure) — it does NOT dedup a logical re-emission that rebuilds the
# event. Logical replay dedup requires a content-derived fingerprint, adopted
# per-topic as each topic's semantics allow.
EVENT_ID_FINGERPRINT = "event-id"


def derive_idempotency_key(topic: str, source_id: str, content_fingerprint: str) -> str:
    """Derive the deterministic outbox idempotency key for one logical emission.

    The single shared derivation scheme (KERNEL-02, audit invariant I-E1):
    ``uuid5(namespace, sha256(topic \\x1f source_id \\x1f content_fingerprint))``.
    Producers must not invent ad-hoc key schemes; choose the fingerprint
    deliberately per topic:

    - ingest events: ``source_id`` = note uuid/path, fingerprint = content hash
      plus a per-observation marker (the observed file mtime). Dedup scope is
      the SAME OBSERVATION (crash/retry re-emission), never all-time content
      recurrence: an A→B→A revert is a new observation (new stat mtime) and
      MUST emit — a bare content key would swallow it against the original A
      row (over-dedup = silent projection divergence, worse than duplicates).
      Suppressing no-op emissions (pure metadata touch) is the upstream change
      detector's job (hash comparison), not the key's.
    - watcher-run audit events: ``source_id`` = relative path, fingerprint =
      run-window payload hash (mtime + content hash)
    - retry / dead-letter events: ``source_id`` = original outbox/event id,
      fingerprint = attempt-scoped (``retry:<n>`` / ``poison:<attempts>``) so
      genuine re-emissions are NOT swallowed
    - event-id-keyed emissions: ``source_id`` = the event's ``event_id``,
      fingerprint = :data:`EVENT_ID_FINGERPRINT`. This protects against
      double-insert of the same constructed event only, not logical replay
      (event_id is random per construction); move such topics to content-derived
      fingerprints as their semantics allow.
    """
    parts = {"topic": topic, "source_id": source_id, "content_fingerprint": content_fingerprint}
    for name, value in parts.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"derive_idempotency_key requires a non-empty string {name!r}, got {value!r}")
    digest = hashlib.sha256("\x1f".join((topic, source_id, content_fingerprint)).encode("utf-8")).hexdigest()
    return str(uuid_module.uuid5(OUTBOX_IDEMPOTENCY_NAMESPACE, digest))


def payload_fingerprint(payload: Mapping[str, Any] | None, *, exclude: tuple[str, ...] = ("trace_id",)) -> str:
    """Stable sha256 fingerprint of an event payload for key derivation.

    Canonical JSON (sorted keys) over the payload minus volatile keys
    (``trace_id`` by default) so a retried emission of the same content maps to
    the same idempotency key while changed content produces a new one.
    """
    source = {k: v for k, v in dict(payload or {}).items() if k not in exclude}
    canonical = json.dumps(source, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_outbox_event(
    event: Event | OutboxEvent,
    conn: Any = None,
    *,
    idempotency_key: str,
) -> str:
    """Insert one event into the DB outbox, keyed by a mandatory idempotency key.

    ``idempotency_key`` is required (keyless calls are a ``TypeError`` at the
    signature level) and becomes the row ``id`` with ``ON CONFLICT (id) DO
    NOTHING``: duplicate emission with the same key yields exactly one row and
    returns ``""`` for the swallowed duplicate. Derive keys with
    :func:`derive_idempotency_key`.

    Registry coverage validation (KERNEL-08, #2770): when the event's topic has
    a registered schema (``schemas/events/<topic>.v1.schema.json``), the payload
    is validated against it before the insert and ``meta.payload_schema`` is
    stamped ``"<topic>.v1"`` so dispatch-time validation can distinguish
    registry-covered rows from pre-registry ("grandfathered") ones. Topics with
    no registered schema are written unchanged (unvalidated) — coverage over the
    live dispatch table is enforced by
    ``tests/events/test_topic_schema_registry.py::test_every_dispatched_topic_has_schema``,
    not by this write path.
    """
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise ValueError(f"write_outbox_event requires a non-empty idempotency_key, got {idempotency_key!r}")
    envelope = _coerce_event(event)
    if is_registered_topic(envelope.event_type):
        validate_topic_payload(envelope.event_type, envelope.payload)
        # Stamp on a copy: `envelope` may be the caller's own `Event` instance
        # (isinstance branch in `_coerce_event`) and must not be mutated in place.
        stamped_meta = dict(envelope.meta or {})
        stamped_meta["payload_schema"] = current_schema_ref(envelope.event_type)
        envelope = envelope.model_copy(update={"meta": stamped_meta})
    conn, close = _use_conn(conn)
    stored = envelope.model_dump_json()
    created_at = envelope.created_at or datetime.now(timezone.utc)
    try:
        cur = _exec(
            conn,
            "insert into outbox (id, topic, payload, created_at, attempts) values (%s, %s, %s::jsonb, %s, %s) on conflict (id) do nothing returning id",
            (idempotency_key, envelope.event_type, stored, created_at, 0),
        )
        if hasattr(cur, "fetchone"):
            row = cur.fetchone()
            if row:
                return str(row[0])
        return ""
    finally:
        if close:
            conn.close()


# Canonical dead-letter audit topic. Mirrors OUTBOX_EVENT_DEAD_LETTERED in
# app/workers/outbox_worker.py; kept here so read-only health consumers do not
# import the worker module (services must not depend on workers).
OUTBOX_DEAD_LETTER_TOPIC = "outbox.event.dead_lettered"


def dead_letter_stats(conn: Any = None) -> dict[str, Any] | None:
    """Read-only dead-letter/backlog stats from the DB outbox, or None when unavailable.

    Returns ``{"dead_lettered_count": int, "oldest_undelivered_age_seconds": float}``.
    ``dead_lettered_count`` counts audit rows with the dead-letter topic;
    ``oldest_undelivered_age_seconds`` is the age of the oldest row still
    pending delivery (0.0 when the queue is empty). Detection only — this
    helper never mutates the outbox (KERNEL-12 read-only invariant).
    """
    try:
        conn, close = _use_conn(conn)
    except Exception:
        return None
    try:
        cur = _exec(
            conn,
            "select count(*) from outbox where topic = %s",
            (OUTBOX_DEAD_LETTER_TOPIC,),
        )
        row = cur.fetchone() if hasattr(cur, "fetchone") else None
        if row is None:
            return None
        dead_lettered = int(row[0])
        cur = _exec(
            conn,
            "select extract(epoch from (now() - min(created_at))) from outbox where delivered_at is null",
        )
        row = cur.fetchone() if hasattr(cur, "fetchone") else None
        oldest_age = float(row[0]) if row and row[0] is not None else 0.0
        return {
            "dead_lettered_count": dead_lettered,
            "oldest_undelivered_age_seconds": max(oldest_age, 0.0),
        }
    except Exception:
        return None
    finally:
        if close:
            try:
                conn.close()
            except Exception:
                pass


def count_outbox_events(conn: Any = None) -> int | None:
    """Return the total DB outbox row count, or None when the DB is unavailable."""
    try:
        conn, close = _use_conn(conn)
    except Exception:
        return None
    try:
        cur = _exec(conn, "select count(*) from outbox")
        if hasattr(cur, "fetchone"):
            row = cur.fetchone()
            return int(row[0]) if row else 0
        return None
    except Exception:
        return None
    finally:
        if close:
            try:
                conn.close()
            except Exception:
                pass


def insert_object_and_outbox(
    payload: Dict[str, Any],
    topic: str,
    trace_id: str | None = None,
    *,
    object_id: str | None = None,
    source: str | None = None,
    conn: Any = None,
    observation: str | None = None,
) -> str:
    """Helper som bygger ett Event och skickar det till outbox.

    Derives the mandatory idempotency key from ``(topic, object identity,
    content fingerprint [+ observation marker])`` (I-E1). The dedup scope is
    the SAME LOGICAL EMISSION (crash/retry of one observation), not all-time
    content recurrence: outbox rows are never purged, so a bare content key
    would swallow an A→B→A revert against the original A row while the
    object/file_state write still commits (``ON CONFLICT DO NOTHING`` is not
    an error) — silent projection divergence downstream.

    ``observation`` is a per-observation marker mixed into the fingerprint
    (NOT into the event payload). It must re-derive identically on crash-retry
    of the same observation and change for each new observation — the observed
    file's stat mtime qualifies; emission-moment wall clock does not. Callers
    whose payload already embeds the observation (e.g. the watcher payload's
    ``mtime`` field) need not pass it. Suppressing no-op emissions (pure
    metadata touch) belongs to the upstream change detectors, not this key.
    """
    data = dict(payload or {})
    if object_id:
        data.setdefault("object_id", object_id)
    if trace_id:
        data.setdefault("trace_id", trace_id)
    data.setdefault("event", topic)
    fingerprint_source: Dict[str, Any] = dict(data)
    if "__observation__" in fingerprint_source:
        # Reserved name: a payload carrying this key would be silently clobbered
        # by the observation marker below, masking caller data — fail loud.
        raise ValueError("payload field '__observation__' is reserved for observation-scoped keys")
    if observation is not None:
        # Reserved fingerprint-only field: scopes the key to this observation
        # without leaking into the emitted payload.
        fingerprint_source["__observation__"] = observation
    fingerprint = payload_fingerprint(fingerprint_source)
    source_id = str(
        object_id
        or data.get("uuid")
        or data.get("object_id")
        or data.get("path")
        or data.get("relative_path")
        or fingerprint
    )
    key = derive_idempotency_key(topic, source_id, fingerprint)
    event = new_event(event_type=topic, payload=data, trace_id=trace_id, source=source)
    return write_outbox_event(event, conn=conn, idempotency_key=key)


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


def bump_outbox_attempts(*args, **kwargs) -> int:
    """Increment ``attempts`` for an undelivered row and return the new count.

    Supports the same calling conventions as :func:`ack_outbox`::

        bump_outbox_attempts(conn, msg_id)
        bump_outbox_attempts(msg_id)

    Returns the post-increment attempt count, or ``0`` when the row is missing or
    already delivered. This lets the worker bound retries on a poison row instead of
    crash-looping on it forever (head-of-line blocking).
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
            "update outbox set attempts = attempts + 1 where id = %s and delivered_at is null returning attempts",
            (msg_id,),
        )
        if hasattr(cur, "fetchone"):
            row = cur.fetchone()
            if row:
                try:
                    return int(row[0])
                except (TypeError, ValueError):
                    return 0
        return 0
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


__all__ = [
    "EVENT_ID_FINGERPRINT",
    "OUTBOX_DEAD_LETTER_TOPIC",
    "OUTBOX_IDEMPOTENCY_NAMESPACE",
    "dead_letter_stats",
    "derive_idempotency_key",
    "payload_fingerprint",
    "write_outbox_event",
    "insert_object_and_outbox",
    "poll_outbox_one",
    "ack_outbox",
    "bump_outbox_attempts",
    "bootstrap",
    "event_source_name",
    "event_payload_dict",
    "coerce_outbox_event",
    "serialize_outbox_record",
    "append_jsonl_outbox_event",
]
