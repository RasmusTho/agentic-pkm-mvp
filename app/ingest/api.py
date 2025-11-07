from __future__ import annotations
from typing import Any, Dict, List, Tuple
from uuid import UUID, uuid4

from app.search.vector_index import get_vector_index

_ALLOWED_TAGS = {"serendipity", "collaboration"}
_EMBED_DIM = 1536
_EMBED_MODEL = "stub-embed/1536d"


def _embed_text(text: str, dim: int = _EMBED_DIM) -> List[float]:
    v = [0.0] * dim
    if not text:
        return v
    for i, ch in enumerate(text):
        v[i % dim] += (ord(ch) % 97) / 97.0
    return v


def normalize_payload(payload: Dict[str, Any], text: str) -> Dict[str, Any]:
    out = dict(payload)
    out.setdefault("object_type", "note")
    out.setdefault("system_intent", "learn")

    tags_in = out.get("emergent_tags", [])
    tags = [t for t in tags_in if t in _ALLOWED_TAGS]
    out["emergent_tags"] = tags  # alltid lista, även tom

    # Synthesis note-specifika fält lämnas som de är om de finns
    return out


def handle_post_ingest(object_id: UUID, payload: Dict[str, Any], text: str) -> None:
    # Hook för analytics/relations — noop i test-baseline
    return None


def ingest_object(
    object_id: UUID | None,
    *,
    kind: str,
    source_ref: str,
    payload: Dict[str, Any],
    text: str,
) -> Tuple[UUID, int]:
    oid = object_id or uuid4()
    emb = _embed_text(text)
    idx = get_vector_index()
    idx.upsert(
        object_id=oid,
        kind=kind,
        source_ref=source_ref,
        payload=payload,
        embedding=emb,
        model=_EMBED_MODEL,
    )
    handle_post_ingest(oid, payload, text)
    return oid, len(emb)
