from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone
from typing import Any, Dict

from app.observability.tracer import start_span
from app.services.embedding import deterministic_embedding
from app.store.object_store import DomainObject, ObjectStore
from app.store.vector_store import VectorIndex


def _is_valid_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        _uuid.UUID(str(value))
    except Exception:
        return False
    return True

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
    trace_id = obj.get("trace_id")
    store = ObjectStore()
    existing = store.get_object(object_uuid)

    if existing is None:
        domain = DomainObject(
            uuid=object_uuid,
            kind=obj.get("kind") or "note",
            payload=payload,
            source_ref=obj.get("source_ref"),
            created_at=datetime.now(timezone.utc),
        )
        store.save_object(domain, emit_outbox=False, trace_id=trace_id)
    else:
        updated_payload = dict(existing.payload or {})
        updated_payload.update({k: v for k, v in payload.items() if v is not None})
        domain = DomainObject(
            uuid=existing.uuid,
            kind=existing.kind,
            payload=updated_payload,
            source_ref=existing.source_ref,
            created_at=existing.created_at,
        )
        store.save_object(domain, emit_outbox=False, trace_id=trace_id)

    with start_span("indexer.upsert", trace_id, {"kind": "note"}):
        VectorIndex().upsert_embedding(object_uuid, embedding)
