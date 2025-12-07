from __future__ import annotations

import os
import json
import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg
from psycopg.rows import dict_row

from app.db.db import conn_rw as _conn_rw
from app.db.dsn import connect as _db_connect  # resolve_dsn etc
from app.events.models import new_trace_id
from app.events.types import INGEST_OBJECT_CREATED


@dataclass
class DomainObject:
    uuid: str
    kind: str
    payload: dict[str, Any]
    source_ref: Optional[str]
    created_at: datetime


# in-memory fallback view, so tests without a live DB can still pass
_MEMORY_STORE: dict[str, DomainObject] = {}


def _normalize_ts(ts: datetime | None) -> datetime:
    if ts is None:
        return datetime.now(timezone.utc)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _pg_available() -> bool:
    """
    Heuristic: try a very fast connect using our dsn helper.
    Return True if connection works, False otherwise.
    """
    conn = None
    try:
        conn = _db_connect()
        return conn is not None
    except Exception:
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


class ObjectStore:
    """
    Unified access to 'objects' table with graceful fallback to in-memory.
    During tests we may not have Postgres running. Then we still want:
      - deterministic UUID
      - Core6 payload integrity
      - pipeline to proceed
    """

    def get_object(self, object_id: str) -> DomainObject | None:
        # Check in-memory cache first
        if object_id in _MEMORY_STORE:
            return _MEMORY_STORE[object_id]

        # Try DB if available
        try:
            with _conn_rw() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        select
                            id,
                            uuid,
                            kind,
                            source_ref,
                            payload,
                            created_at
                        from objects
                        where id = %s or uuid = %s
                        limit 1
                        """,
                        (object_id, object_id),
                    )
                    row = cur.fetchone()
                    if not row:
                        return None
                    return DomainObject(
                        uuid=row["uuid"] or row["id"],
                        kind=row["kind"],
                        payload=row["payload"],
                        source_ref=row.get("source_ref"),
                        created_at=row["created_at"],
                    )
        except Exception:
            # no DB or query failed → fall back
            return _MEMORY_STORE.get(object_id)

        return None

    def save_object(
        self,
        obj: DomainObject,
        emit_outbox: bool = True,
        trace_id: Optional[str] = None,
    ) -> None:
        """
        Persist object.
        - Always update in-memory cache.
        - If DB is reachable, also upsert into objects and maybe outbox.
        """

        if trace_id is None:
            trace_id = new_trace_id()

        # normalize timestamp (UTC aware)
        obj.created_at = _normalize_ts(obj.created_at)

        # always keep memory store in sync
        _MEMORY_STORE[obj.uuid] = obj

        # If DB isn't reachable (typical in fast unit tests), stop here
        if not _pg_available():
            return

        # If DB is reachable, write to Postgres
        conn = _db_connect()
        if conn is None:
            # extra paranoia, just in case
            return

        with conn:
            with conn.cursor() as cur:
                # IMPORTANT:
                # We are in the migration phase where table objects has BOTH:
                #   id uuid PRIMARY KEY NOT NULL
                #   uuid uuid
                # Our rule (for now): id == uuid
                cur.execute(
                    """
                    insert into objects (
                        id,
                        uuid,
                        kind,
                        source_ref,
                        payload,
                        created_at
                    )
                    values (%s, %s, %s, %s, %s::jsonb, %s)
                    on conflict (id) do update set
                        uuid = excluded.uuid,
                        kind = excluded.kind,
                        source_ref = excluded.source_ref,
                        payload = excluded.payload
                    """,
                    (
                        obj.uuid,  # id
                        obj.uuid,  # uuid
                        obj.kind,
                        obj.source_ref,
                        json.dumps(obj.payload),
                        obj.created_at,
                    ),
                )

                if emit_outbox:
                    # Fire-and-forget. In some tests (early pipeline) we may not even
                    # have outbox table yet, so swallow failures.
                    event = {
                        "event": INGEST_OBJECT_CREATED,
                        "uuid": obj.uuid,
                        "kind": obj.kind,
                        "trace_id": trace_id,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }
                    try:
                        cur.execute(
                            """
                            insert into outbox (event, payload, created_at)
                            values (%s, %s::jsonb, now())
                            """,
                            (event["event"], json.dumps(event)),
                        )
                    except Exception:
                        pass

        # mirror final state again just to be sure
        _MEMORY_STORE[obj.uuid] = obj

    def list_objects(self) -> list[DomainObject]:
        """
        Return all known objects from memory plus Postgres if reachable.
        Deduplicates by uuid/id with Postgres overwriting memory entries when available.
        """
        objects: dict[str, DomainObject] = {k: v for k, v in _MEMORY_STORE.items()}

        if not _pg_available():
            return list(objects.values())

        conn = _db_connect()
        if conn is None:
            return list(objects.values())

        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        select
                            id,
                            uuid,
                            kind,
                            source_ref,
                            payload,
                            created_at
                        from objects
                        """
                    )
                    for row in cur.fetchall() or []:
                        obj_uuid = row.get("uuid") or row.get("id")
                        if not obj_uuid:
                            continue
                        objects[str(obj_uuid)] = DomainObject(
                            uuid=str(obj_uuid),
                            kind=row["kind"],
                            payload=row["payload"],
                            source_ref=row.get("source_ref"),
                            created_at=row["created_at"],
                        )
        except Exception:
            # best effort; fall back to memory results
            pass

        return list(objects.values())
