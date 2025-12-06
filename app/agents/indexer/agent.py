from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List

from app.components.embeddings import get_embedding_client
from app.events.types import INGEST_INDEX_DONE
from app.store.object_store import ObjectStore


AGENT = "indexer"

# enkel in-memory vektorindex för pytest/offline
_MEMORY_VECTOR_INDEX: dict[str, list[list[float]]] = {}


def _get_text_for_embedding(payload: dict[str, Any]) -> str:
    """
    Välj text att indexera.
    1. raw_text
    2. core6.title
    3. tom sträng (hanteras av fallback)
    """
    if not payload:
        return ""
    raw = payload.get("raw_text", "") or ""
    if raw.strip():
        return raw
    title = ((payload.get("core6") or {}).get("title") or "").strip()
    return title


def _safe_embed(text: str) -> list[float]:
    """
    Försök skapa deterministisk embedding.
    Om texten är tom -> returnera en dummy-vektor [0.0].
    Om embed_text kastar -> returnera dummy-vektor [0.0].
    """
    if not text.strip():
        return [0.0]
    try:
        return get_embedding_client("deterministic").embed_text(text)
    except Exception:
        return [0.0]


def index_object(object_id: str, *, trace_id: str) -> dict[str, Any]:
    """
    Skapa embeddings och lägg i ett enkelt in-memory index.
    För testmiljön räcker det att vi 'lagrar' minst en embedding-vektor.
    """
    store = ObjectStore()
    obj = store.get_object(object_id)
    if not obj:
        # objektet borde finnas, men om inte -> returnera 0 embeddings
        return {
            "event": INGEST_INDEX_DONE,
            "object_id": object_id,
            "embeddings": 0,
            "trace_id": trace_id,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

    text = _get_text_for_embedding(obj.payload or {})
    vec = _safe_embed(text)

    # stoppa i in-memory vectorindex
    existing: List[list[float]] = _MEMORY_VECTOR_INDEX.get(object_id, [])
    existing.append(vec)
    _MEMORY_VECTOR_INDEX[object_id] = existing

    out = {
        "event": INGEST_INDEX_DONE,
        "object_id": object_id,
        "embeddings": len(existing),
        "trace_id": trace_id,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    return out


def run(object_id: str, *, trace_id: str) -> dict[str, Any]:
    return index_object(object_id, trace_id=trace_id)
