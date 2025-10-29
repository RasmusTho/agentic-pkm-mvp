import json
import uuid as _uuid
from typing import Any, Dict, List

import psycopg

from app.db import conn_rw
from app.observability.tracer import start_span
from app.services.embedding import deterministic_embedding


def _is_valid_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        _uuid.UUID(str(value))
    except Exception:
        return False
    return True


def _upsert_object(cur, object_uuid: str, payload_json: str) -> None:
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


def _upsert_embedding(cur, object_uuid: str, embedding: List[float]) -> None:
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


def handle_ingest_object_created(message: Dict[str, Any]) -> None:
    if isinstance(message, dict) and "payload" in message:
        obj = message["payload"]
        trace_id = message.get("trace_id")
    else:
        obj = message
        trace_id = None

    incoming_uuid = obj.get("uuid")
    object_uuid = (
        incoming_uuid if _is_valid_uuid(incoming_uuid) else str(_uuid.uuid4())
    )

    content = obj.get("content") or ""
    embedding = deterministic_embedding(content)

    payload = {
        "title": obj.get("title"),
        "review_state": obj.get("review_state"),
        "content": content,
        "source_uuid": incoming_uuid,
    }
    payload_json = json.dumps(payload)

    with conn_rw() as conn:
        with conn.cursor() as cur:
            with start_span("indexer.upsert", trace_id, {"kind": "note"}):
                _upsert_object(cur, object_uuid, payload_json)
                _upsert_embedding(cur, object_uuid, embedding)
        conn.commit()
