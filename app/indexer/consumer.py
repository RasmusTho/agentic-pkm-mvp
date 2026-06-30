from __future__ import annotations

import logging
from typing import Any, Dict
from uuid import UUID

from app.components.embeddings import EmbeddingIdentity, get_embedding_identity
from app.components.llm.fabric import get_embeddings_client
from app.components.llm.router import LLMTaskIntent
from app.embedding_config import coerce_floats
from app.index.artifact_metadata import build_indexed_unit_payload
from app.llm.embed_queue import embed_with_retry
from app.llm.embeddings import EMBED_MODEL
from app.outbox import events as outbox_events
from app.objects import ObjectStore
from app.stores import get_vector_index

logger = logging.getLogger(__name__)


def _extract_object_id(evt: Dict[str, Any]) -> str | None:
    payload = evt.get("payload")
    if isinstance(payload, dict):
        obj_id = payload.get("object_id")
        if obj_id:
            return str(obj_id)
    obj_id = evt.get("object_id")
    return str(obj_id) if obj_id else None


def _extract_text(obj_payload: Dict[str, Any]) -> str:
    for key in ("content", "text", "raw_text"):
        val = obj_payload.get(key)
        if val:
            return str(val)
    return ""


def _purge_vectors(idx: object, object_id: UUID) -> int:
    purge = getattr(idx, "purge_vectors", None)
    if purge is None:
        return 0
    try:
        return purge(object_id, view=outbox_events.DEFAULT_EMBEDDING_VIEW)
    except Exception:
        return 0


def process_event(evt: Dict[str, Any]) -> None:
    event_type = str(evt.get("event") or "").strip()

    # Legacy: embedding-in-event records (deprecated).
    if "embedding" in evt and "object_id" in evt:
        object_id = UUID(str(evt["object_id"]))
        kind = str(evt.get("kind") or "")
        source_ref = str(evt.get("source_ref") or "")
        raw_payload = dict(evt.get("payload") or {})
        payload = raw_payload.get("payload", raw_payload) if isinstance(raw_payload.get("payload"), dict) else raw_payload
        embedding = coerce_floats(evt.get("embedding") or [])
        model = str(evt.get("model") or EMBED_MODEL)
        identity = EmbeddingIdentity(provider="legacy-event", model=model, dim=len(embedding))

        idx = get_vector_index()
        _purge_vectors(idx, object_id)
        payload = build_indexed_unit_payload(
            object_id=object_id,
            kind=kind,
            source_ref=source_ref,
            payload=payload,
            embedding_identity=identity,
        )
        idx.upsert(
            object_id=object_id,
            kind=kind,
            source_ref=source_ref,
            payload=payload,
            embedding=embedding,
            model=model,
            identity=identity,
        )
        outbox_events.emit_index_embedding_created(object_id=object_id, trace_id=str(evt.get("trace_id") or "") or None)
        return

    # Current: request event triggers embedding computation in the indexer.
    if event_type != outbox_events.INDEX_EMBEDDING_REQUESTED:
        return

    object_id_raw = _extract_object_id(evt)
    if not object_id_raw:
        raise ValueError("index.embedding.requested missing payload.object_id")

    store = ObjectStore()
    try:
        obj = store.get_object(object_id_raw, strict_backend=True)
    except Exception as exc:
        raise RuntimeError(
            f"transient object-store lookup failure for embedding request: {object_id_raw}"
        ) from exc
    if obj is None:
        trace_id = str(evt.get("trace_id") or "").strip() or None
        logger.warning(
            "index embedding request dropped (missing object) object_id=%s trace_id=%s",
            object_id_raw,
            trace_id or "-",
        )
        outbox_events.emit_index_embedding_failed(
            object_id=object_id_raw,
            trace_id=trace_id,
            error=f"missing object for embedding request: {object_id_raw}",
        )
        return

    obj_uuid = UUID(str(obj.uuid))
    obj_payload = dict(obj.payload or {})
    text = _extract_text(obj_payload)

    embedder = get_embeddings_client(LLMTaskIntent(task_kind="embed", strict_identity_required=True))
    identity = get_embedding_identity(client=embedder)
    trace_id = str(evt.get("trace_id") or "").strip() or None

    # Consumer/worker path: retry the injected embedder for transient blips, but on
    # exhaustion (or any non-transient error) let it propagate to the outbox worker,
    # which keeps the row pending and retries when the provider recovers. Swallowing
    # a transient outage here would permanently drop the object (at-least-once break).
    embedding = embed_with_retry(
        text,
        dim=identity.dim,
        object_id=object_id_raw,
        embed_callable=lambda: embedder.embed_text(text),
        dead_letter_on_exhaustion=False,
    )

    idx = get_vector_index()
    _purge_vectors(idx, obj_uuid)
    idx.upsert(
        object_id=obj_uuid,
        kind=str(obj.kind or "note"),
        source_ref=str(obj.source_ref or ""),
        payload=build_indexed_unit_payload(
            object_id=obj_uuid,
            kind=str(obj.kind or "note"),
            source_ref=str(obj.source_ref or ""),
            payload=obj_payload,
            text=text,
            embedding_identity=identity,
        ),
        embedding=embedding,
        model=identity.model,
        identity=identity,
    )

    outbox_events.emit_index_embedding_created(object_id=obj_uuid, trace_id=trace_id)


__all__ = ["process_event"]
