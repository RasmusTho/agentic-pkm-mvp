from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.events.types import INGEST_CHUNK_DONE
from app.store.object_store import ObjectStore
from app.services.audit import audit_event

AGENT = "chunker"


def _fallback_chunk(text: str) -> list[dict[str, Any]]:
    # Minimal chunk: hela texten i ett block
    return [{
        "text": text,
        "meta": {
            "strategy": "fallback_single",
        },
    }]


def _do_chunk(raw_text: str,
              max_tokens: int,
              overlap: int,
              strategy: str) -> list[dict[str, Any]]:
    """
    Riktig version skulle splitta på rubriker/token-budget.
    Nu: om text finns -> 1 chunk, annars 0.
    """
    raw_text = raw_text.strip()
    if not raw_text:
        return []
    return _fallback_chunk(raw_text)


def chunk_object(object_id: str,
                 *,
                 trace_id: str,
                 max_tokens: int,
                 overlap: int,
                 strategy: str) -> dict[str, Any]:
    store = ObjectStore()
    obj = store.get_object(object_id)
    if not obj:
        raise RuntimeError(f"object {object_id} not found for chunking")

    raw_text = obj.payload.get("raw_text", "") if obj.payload else ""
    chunks = _do_chunk(raw_text, max_tokens, overlap, strategy)

    # audit best-effort
    audit_event(
        event=INGEST_CHUNK_DONE,
        object_id=object_id,
        agent=AGENT,
        trace_id=trace_id,
        extra={
            "num_chunks": len(chunks),
            "strategy": strategy,
            "max_tokens": max_tokens,
            "overlap": overlap,
        },
    )

    out = {
        "event": INGEST_CHUNK_DONE,
        "object_id": object_id,
        "chunks": len(chunks),
        "trace_id": trace_id,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    return out


def run(object_id: str,
        *,
        trace_id: str,
        max_tokens: int,
        overlap: int,
        strategy: str = "heading_first") -> dict[str, Any]:
    return chunk_object(
        object_id,
        trace_id=trace_id,
        max_tokens=max_tokens,
        overlap=overlap,
        strategy=strategy,
    )
