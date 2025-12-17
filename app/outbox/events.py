from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict
from uuid import UUID

from app.embedding_config import get_embed_dim
from app.events.schema import make_outbox_event
from app.llm.embeddings import EMBED_MODEL

INDEX_OUTBOX_PATH = Path(os.environ.get("INDEX_OUTBOX_PATH", "logs/index-outbox.jsonl"))

INDEX_EMBEDDING_REQUESTED = "index.embedding.requested"
INDEX_EMBEDDING_CREATED = "index.embedding.created"


def _coerce_uuid(value: object) -> str:
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def _append_record(record: Dict[str, Any]) -> None:
    INDEX_OUTBOX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with INDEX_OUTBOX_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def emit_index_embedding_requested(event: Dict[str, Any]) -> None:
    """Request that the indexer compute and upsert an embedding for an object.

    Contract:
    - MUST include `object_id`.
    - MUST NOT include an embedding vector.
    """

    if "object_id" not in event:
        raise ValueError("index.embedding.requested missing field: object_id")

    payload = dict(event)
    payload["object_id"] = _coerce_uuid(payload["object_id"])
    payload.pop("embedding", None)

    trace_val = payload.get("trace_id")
    envelope = make_outbox_event(
        INDEX_EMBEDDING_REQUESTED,
        source=str(payload.get("source") or "ingest"),
        trace_id=str(trace_val) if trace_val else None,
        payload={"object_id": payload["object_id"]},
        meta={k: v for k, v in payload.items() if k not in {"object_id", "trace_id", "source"}},
    )

    record: Dict[str, Any] = dict(envelope.model_dump())
    _append_record(record)


def emit_index_embedding_created(*, object_id: UUID, trace_id: str | None = None, source: str = "indexer") -> None:
    """Emit an index.embedding.created record without embedding vectors."""

    envelope = make_outbox_event(
        INDEX_EMBEDDING_CREATED,
        source=source,
        trace_id=trace_id,
        payload={"object_id": str(object_id)},
        meta={},
    )

    record: Dict[str, Any] = {
        "event": INDEX_EMBEDDING_CREATED,
        "trace_id": envelope.trace_id,
        "uuid": str(object_id),
        "metrics": {"vectors": 1, "dim": get_embed_dim(), "view": "markdown.semantic"},
        "provenance": {"model": EMBED_MODEL, "version": "1.0"},
    }
    record.update(envelope.model_dump())
    _append_record(record)


def emit_index_object_embedded(event: Dict[str, Any]) -> None:
    """Deprecated compatibility shim.

    Historically this event carried an embedding vector (legacy). The embeddings pipeline
    is now indexer-computed, and outbox records must not carry vectors.

    Use `emit_index_embedding_requested` instead.
    """

    emit_index_embedding_requested(event)


__all__ = [
    "emit_index_embedding_requested",
    "emit_index_embedding_created",
    "emit_index_object_embedded",
    "INDEX_OUTBOX_PATH",
    "INDEX_EMBEDDING_REQUESTED",
    "INDEX_EMBEDDING_CREATED",
]
