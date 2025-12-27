from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Optional

import psycopg
from psycopg import sql

from app.db import choose_object_table
from app.db.db import conn_rw as _conn_rw
from app.db.dsn import connect as _db_connect
from app.events.models import new_trace_id
from app.events.types import INGEST_OBJECT_CREATED


@dataclass
class DomainObject:
    uuid: str
    kind: str
    payload: dict[str, Any]
    source_ref: Optional[str]
    created_at: datetime


_MEMORY_STORE: dict[str, DomainObject] = {}


def _normalize_ts(ts: datetime | None) -> datetime:
    if ts is None:
        return datetime.now(timezone.utc)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _pg_available() -> bool:
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


def _table_columns(table: str) -> tuple[str, str]:
    if table == "store_objects":
        return "object_id", "object_id"
    return "id", "uuid"


def _row_to_domain(row: dict[str, Any]) -> DomainObject:
    uuid_val = row.get("uuid") or row.get("object_id") or row.get("id")
    if uuid_val is None:
        raise ValueError("missing uuid in object row")
    return DomainObject(
        uuid=str(uuid_val),
        kind=row["kind"],
        payload=row.get("payload") or {},
        source_ref=row.get("source_ref"),
        created_at=row["created_at"],
    )


def _list_from_memory(kind: Optional[str] = None, limit: int = 100) -> List[DomainObject]:
    values = list(_MEMORY_STORE.values())
    if kind is not None:
        values = [o for o in values if o.kind == kind]
    values.sort(key=lambda o: o.created_at, reverse=True)
    return values[:limit]


def _fetch_db_rows(conn: psycopg.Connection, table: str, kind: Optional[str], limit: int) -> list[dict[str, Any]]:
    id_col, uuid_col = _table_columns(table)
    stmt = sql.SQL(
        """
        SELECT
            {id_col} AS object_id,
            {uuid_col} AS uuid,
            kind,
            source_ref,
            payload,
            created_at
        FROM {table}
        """
    ).format(
        id_col=sql.Identifier(id_col),
        uuid_col=sql.Identifier(uuid_col),
        table=sql.Identifier(table),
    )
    params: list[Any] = []
    if kind is not None:
        stmt = sql.SQL("{stmt} WHERE kind = %s").format(stmt=stmt)
        params.append(kind)
    stmt = sql.SQL("{stmt} ORDER BY created_at DESC LIMIT %s").format(stmt=stmt)
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(stmt, params)
        rows = cur.fetchall()
    return [dict(row) if isinstance(row, dict) else dict(row) for row in rows]


class ObjectStore:
    def _active_table(self, conn: psycopg.Connection) -> str:
        return choose_object_table(conn)

    def _db_list_objects(self, conn: psycopg.Connection, kind: Optional[str], limit: int) -> List[DomainObject]:
        table = self._active_table(conn)
        rows = _fetch_db_rows(conn, table, kind, limit)
        return [_row_to_domain(row) for row in rows]

    def get_object(self, object_id: str) -> DomainObject | None:
        if object_id in _MEMORY_STORE:
            return _MEMORY_STORE[object_id]

        if not _pg_available():
            return _MEMORY_STORE.get(object_id)

        try:
            with _conn_rw() as conn:
                table = self._active_table(conn)
                id_col, uuid_col = _table_columns(table)
                stmt = sql.SQL(
                    """
                    SELECT
                        {id_col} AS object_id,
                        {uuid_col} AS uuid,
                        kind,
                        source_ref,
                        payload,
                        created_at
                    FROM {table}
                    WHERE {id_col} = %s OR {uuid_col} = %s
                    LIMIT 1
                    """
                ).format(
                    id_col=sql.Identifier(id_col),
                    uuid_col=sql.Identifier(uuid_col),
                    table=sql.Identifier(table),
                )
                with conn.cursor() as cur:
                    cur.execute(stmt, (object_id, object_id))
                    row = cur.fetchone()
                    if not row:
                        return None
                    record = row if isinstance(row, dict) else dict(row)
                    return _row_to_domain(record)
        except Exception:
            return _MEMORY_STORE.get(object_id)

        return None

    def save_object(
        self,
        obj: DomainObject,
        emit_outbox: bool = True,
        trace_id: Optional[str] = None,
    ) -> None:
        if trace_id is None:
            trace_id = new_trace_id()
        obj.created_at = _normalize_ts(obj.created_at)
        _MEMORY_STORE[obj.uuid] = obj
        if not _pg_available():
            return
        with _conn_rw() as conn:
            with conn.cursor() as cur:
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
                        obj.uuid,
                        obj.uuid,
                        obj.kind,
                        obj.source_ref,
                        json.dumps(obj.payload),
                        obj.created_at,
                    ),
                )
                if emit_outbox:
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
        _MEMORY_STORE[obj.uuid] = obj

    def list_objects(
        self,
        kind: Optional[str] = None,
        limit: int = 100,
    ) -> List[DomainObject]:
        if not _pg_available():
            return _list_from_memory(kind, limit)
        try:
            with _conn_rw() as conn:
                return self._db_list_objects(conn, kind, limit)
        except Exception:
            return _list_from_memory(kind, limit)
