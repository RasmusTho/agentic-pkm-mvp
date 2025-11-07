from __future__ import annotations
from typing import Any, Dict, Optional, Tuple
from uuid import UUID, uuid4

from app.search import get_vector_index
from app.search.service import _embed_text

# Konfig-fallback: använd värde om det finns, annars stabil default
try:
    from app.config.agent import settings as _cfg  # type: ignore
    EMBED_MODEL: str = getattr(_cfg, "embed_model", "hash-64")
except Exception:
    EMBED_MODEL = "hash-64"

def normalize_payload(payload: Dict[str, Any]) -> tuple[Dict[str, Any], str]:
    text = payload.pop("text", payload.pop("__text__", ""))
    return payload, text

def handle_post_ingest(object_id: UUID, payload: Dict[str, Any], dims: int) -> Dict[str, Any]:
    return {"object_id": object_id, "dims": dims}

def ingest_object(
    object_id: Optional[UUID],
    kind: str,
    source_ref: str,
    payload: Dict[str, Any],
    text: str,
) -> Tuple[UUID, int]:
    oid = object_id or uuid4()
    embedding = _embed_text(text)
    idx = get_vector_index()
    idx.upsert(
        object_id=oid,
        kind=kind,
        source_ref=source_ref,
        payload=payload,
        embedding=embedding,
        model=EMBED_MODEL,
    )
    return oid, len(embedding)
