from __future__ import annotations

from typing import Any, Dict, Iterable
from uuid import UUID

from app.stores import get_vector_index

REQUIRED_FIELDS = {"object_id", "kind", "source_ref", "payload", "embedding", "model"}


def _coerce_embedding(values: Iterable[Any]) -> list[float]:
    return [float(v) for v in values]


def process_event(evt: Dict[str, Any]) -> None:
    missing = sorted(REQUIRED_FIELDS - set(evt.keys()))
    if missing:
        raise ValueError(f"index event missing fields: {', '.join(missing)}")

    object_id = UUID(str(evt["object_id"]))
    kind = str(evt["kind"])
    source_ref = str(evt["source_ref"])
    raw_payload = dict(evt["payload"])
    # Envelope-compatible: unwrap nested payload if present
    payload = raw_payload.get("payload", raw_payload) if isinstance(raw_payload.get("payload"), dict) else raw_payload
    embedding = _coerce_embedding(evt["embedding"])
    model = str(evt["model"])

    idx = get_vector_index()
    idx.upsert(
        object_id=object_id,
        kind=kind,
        source_ref=source_ref,
        payload=payload,
        embedding=embedding,
        model=model,
    )


__all__ = ["process_event"]
