from __future__ import annotations

import logging
import re
import uuid as _uuid
from datetime import datetime, timezone
from typing import Dict

from app.components.embeddings import get_embedding_client, get_embedding_identity
from app.observability.tracer import start_span
from app.outbox.events import DEFAULT_EMBEDDING_VIEW, emit_index_embedding_failed, emit_index_object_embedded
from app.store.object_store import DomainObject, ObjectStore
from app.stores import get_vector_index

logger = logging.getLogger(__name__)


def llm_embed_text(*, text: str, provider: str, model: str, dim: int, normalize: bool) -> list[float]:
    client = get_embedding_client(override_provider=provider, override_model=model)
    vector = client.embed_text(text)
    if len(vector) != dim:
        raise ValueError(f"expected {dim} got {len(vector)}")
    if normalize:
        return list(vector)
    return list(vector)


def _is_valid_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        _uuid.UUID(str(value))
    except Exception:
        return False
    return True


def _infer_dim_from_error(exc: Exception) -> int | None:
    text = str(exc)
    match = re.search(r"got\s+(\d+)", text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def handle_ingest_object_created(obj: Dict[str, object]) -> None:
    incoming_uuid = obj.get("uuid")
    object_uuid = incoming_uuid if _is_valid_uuid(incoming_uuid) else str(_uuid.uuid4())

    content = obj.get("content") or ""
    obj_payload = obj.get("payload") or {}
    payload = {
        "title": obj.get("title"),
        "review_state": obj.get("review_state"),
        "maturity": obj.get("maturity"),
        "content": content,
        "source_uuid": incoming_uuid,
        "raw_text": obj_payload.get("raw_text"),
        "text": content,
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

    client = get_embedding_client()
    identity = get_embedding_identity()
    embedding: list[float] | None = None
    actual_dim: int | None = None

    try:
        embedding = list(
            llm_embed_text(
                text=content,
                provider=identity.provider,
                model=identity.model,
                dim=identity.dim,
                normalize=identity.normalize,
            )
        )
        actual_dim = len(embedding)
    except Exception as exc:
        actual_dim = _infer_dim_from_error(exc)
        emit_index_embedding_failed(
            object_id=object_uuid,
            trace_id=trace_id,
            source_ref=domain.source_ref,
            provider=identity.provider,
            model=identity.model,
            expected_dim=identity.dim,
            actual_dim=actual_dim,
            error=str(exc),
        )
        return

    vector_index = get_vector_index()
    model_name = identity.model

    object_uuid_val = _uuid.UUID(object_uuid)
    with start_span("indexer.upsert", trace_id, {"kind": obj.get("kind") or "note"}):
        try:
            vector_index.purge_vectors(object_uuid_val, view=DEFAULT_EMBEDDING_VIEW)
            vector_index.upsert(
                object_uuid_val,
                kind=domain.kind,
                source_ref=domain.source_ref or "",
                payload=domain.payload,
                embedding=embedding,
                model=model_name,
                identity=identity,
            )
            emit_index_object_embedded(
                object_id=object_uuid,
                trace_id=trace_id,
                source_ref=domain.source_ref,
                provider=identity.provider,
                model=model_name,
                dim=actual_dim,
            )
        except Exception as exc:  # pragma: no cover - best-effort logging path
            logger.exception("Vector index ingest failed for %s", object_uuid)
            emit_index_embedding_failed(
                object_id=object_uuid,
                trace_id=trace_id,
                source_ref=domain.source_ref,
                provider=identity.provider,
                model=model_name,
                expected_dim=identity.dim,
                actual_dim=actual_dim,
                error=str(exc),
            )
