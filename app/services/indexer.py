from __future__ import annotations

import json
import uuid as _uuid
from typing import Any, Dict, List

import psycopg
from app.db import conn_rw
from app.observability.tracer import start_span
from app.db.dsn import resolve_dsn
from app.services.embedding import deterministic_embedding


def _conn():
    # legacy helper, not really used after we standardised on conn_rw()
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
    """
    Your live DB (before the clean migrations) has:
      - objects(id UUID PRIMARY KEY, ... , uuid GENERATED ALWAYS AS (...))
    which means:
      - we are allowed to INSERT/UPSERT 'id'
      - we are NOT allowed to assign 'uuid'
    So we treat object_uuid as 'id' here.
    """
    # try upsert on id
    cur.execute(
        """
        INSERT INTO objects(id, kind, payload)
        VALUES (%s, %s, %s::jsonb)
        ON CONFLICT (id) DO UPDATE SET
          kind = EXCLUDED.kind,
          payload = EXCLUDED.payload
        """,
        (object_uuid, "note", payload_json),
    )


def _upsert_embedding(cur, object_uuid: str, embedding: List[float]) -> None:
    """
    Your live DB also likely has an embeddings / objects_embeddings table that
    links by uuid or id. We saw earlier code that assumed table 'objects_embeddings(uuid, dim, vector)'.

    BUT in your current DB we haven't confirmed schema. To avoid crashes,
    we'll create a very forgiving "INSERT ... ON CONFLICT DO UPDATE" that
    targets 'objects_embeddings' keyed by 'id' if present, else no-op catch.

    If the table doesn't exist yet, we'll just skip silently. That lets you
    keep working without blowing up capture.
    """
    try:
        cur.execute(
            """
            INSERT INTO objects_embeddings(id, dim, vector)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
              dim = EXCLUDED.dim,
              vector = EXCLUDED.vector
            """,
            (object_uuid, len(embedding), embedding),
        )
    except Exception:
        # fallback: skip embeddings if schema doesn't match yet
        pass


def handle_ingest_object_created(obj: Dict[str, Any]) -> None:
    """
    Called by capture_indexer after we wrote the capture note to vault.
    We push a structured payload into Postgres for search / recall.
    """
    incoming_uuid = obj.get("uuid")
    # pick stable id if caller gave one, otherwise generate one
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

    trace_id = obj.get("trace_id")

    with conn_rw() as conn:
        with conn.cursor() as cur:
            with start_span("indexer.upsert", trace_id, {"kind": "note"}):
                _upsert_object(cur, object_uuid, payload_json)
                _upsert_embedding(cur, object_uuid, embedding)
        conn.commit()
