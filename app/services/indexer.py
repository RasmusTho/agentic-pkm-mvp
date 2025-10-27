from __future__ import annotations

import json
from typing import Any, Dict
import uuid as _uuid

import psycopg

from app.db.dsn import resolve_dsn
from app.services.embedding import deterministic_embedding


def _conn():
    return psycopg.connect(resolve_dsn())


def _is_valid_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        _uuid.UUID(str(value))
    except Exception:
        return False
    return True


def _upsert_object(cur, object_uuid: str, payload_json: str) -> None:
    try:
        cur.execute(
            """
            insert into objects(uuid, kind, payload)
            values (%s, %s, %s::jsonb)
            on conflict (uuid) do update set
              kind = excluded.kind,
              payload = excluded.payload
            """,
            (object_uuid, "note", payload_json),
        )
    except Exception:
        cur.execute(
            """
            insert into objects(id, kind, payload)
            values (%s, %s, %s::jsonb)
            on conflict (id) do update set
              kind = excluded.kind,
              payload = excluded.payload
            """,
            (object_uuid, "note", payload_json),
        )


def _upsert_embedding(cur, object_uuid: str, embedding: list[float]) -> None:
    cur.execute(
        """
        insert into objects_embeddings(uuid, dim, vector)
        values (%s, %s, %s)
        on conflict (uuid) do update set
          dim = excluded.dim,
          vector = excluded.vector
        """,
        (object_uuid, len(embedding), embedding),
    )


def handle_ingest_object_created(obj: Dict[str, Any]) -> None:
    incoming_uuid = obj.get("uuid")
    if not incoming_uuid:
        return

    object_uuid = incoming_uuid if _is_valid_uuid(incoming_uuid) else str(_uuid.uuid4())
    content = obj.get("content") or ""
    embedding = deterministic_embedding(content)

    payload = {
        "title": obj.get("title"),
        "review_state": obj.get("review_state"),
        "content": content,
        "source_uuid": incoming_uuid,
    }
    payload_json = json.dumps(payload)

    with _conn() as conn:
        with conn.cursor() as cur:
            _upsert_object(cur, object_uuid, payload_json)
            _upsert_embedding(cur, object_uuid, embedding)
        conn.commit()
