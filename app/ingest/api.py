from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from uuid import UUID, uuid4

from app.embedding_config import get_embed_dim

try:
    from app.config.agent import settings as _agent_settings  # type: ignore

    _EMBED_MODEL = getattr(_agent_settings, "embed_model", "openai/text-embedding-3-large")
except Exception:
    _EMBED_MODEL = "openai/text-embedding-3-large"

_ALLOWED_TAGS = {"serendipity", "collaboration"}


def normalize_payload(payload: Dict[str, Any], text: str) -> Dict[str, Any]:
    out = dict(payload)
    out.setdefault("object_type", "note")
    out.setdefault("system_intent", "learn")
    out["text"] = text
    out["content"] = text
    out.setdefault("title", text)
    tags_in = out.get("emergent_tags", [])
    out["emergent_tags"] = [t for t in tags_in if t in _ALLOWED_TAGS]
    return out


def handle_post_ingest(object_id: UUID, payload: Dict[str, Any], text: str) -> None:
    from app.ingest import lifecycle

    if payload.get("system_intent") == "reflect":
        lifecycle.REFLECT_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "source_object_id": str(object_id),
            "payload": {k: v for k, v in payload.items() if k != "text"},
            "text": text,
        }
        (lifecycle.REFLECT_DIR / f"{object_id}.json").write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")

        lifecycle.REFLECTION_LOG.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(lifecycle.REFLECTION_LOG.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                data = []
        except Exception:
            data = []
        data.append(
            {
                "object_id": str(object_id),
                "source_object_id": str(object_id),
                "system_intent": payload.get("system_intent"),
                "clarity_score": payload.get("clarity_score"),
            }
        )
        lifecycle.REFLECTION_LOG.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        lifecycle.ANALYTICS_LOG.parent.mkdir(parents=True, exist_ok=True)
        try:
            analytics = json.loads(lifecycle.ANALYTICS_LOG.read_text(encoding="utf-8"))
            if not isinstance(analytics, dict):
                analytics = {}
        except Exception:
            analytics = {}
        intent = payload.get("system_intent", "unknown")
        tags = payload.get("emergent_tags", [])
        analytics.setdefault("system_intent", {})
        analytics["system_intent"][intent] = int(analytics["system_intent"].get(intent, 0)) + 1
        intent_bucket = analytics.setdefault(intent, {})
        total_bucket = analytics.setdefault("emergent_tags", {})
        for t in tags:
            intent_bucket[t] = int(intent_bucket.get(t, 0)) + 1
            total_bucket[t] = int(total_bucket.get(t, 0)) + 1
        lifecycle.ANALYTICS_LOG.write_text(json.dumps(analytics, ensure_ascii=False), encoding="utf-8")

    if payload.get("object_type") == "synthesis_note":
        lifecycle.RELATIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "type": "synthesizes",
            "synthesis_id": str(object_id),
            "related_claims": payload.get("related_claim_ids", []),
        }
        with lifecycle.RELATIONS_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def ingest_object(
    object_id: UUID | None,
    *,
    kind: str,
    source_ref: str,
    payload: Dict[str, Any],
    text: str,
) -> Tuple[UUID, int]:
    oid = object_id or uuid4()

    payload_out = dict(payload)
    payload_out.setdefault("title", text)
    payload_out.setdefault("content", text)
    payload_out.setdefault("text", text)
    payload_out.setdefault("object_type", kind or "note")
    payload_out.setdefault("system_intent", "learn")
    payload_out.setdefault("emergent_tags", [])

    # Persist object so the indexer stage can load text by object_id.
    from app.objects import DomainObject, ObjectStore

    store = ObjectStore()
    store.save_object(
        DomainObject(
            uuid=str(oid),
            kind=kind or "note",
            payload=payload_out,
            source_ref=source_ref,
            created_at=datetime.now(timezone.utc),
        ),
        emit_outbox=False,
        trace_id=str(payload_out.get("trace_id") or "").strip() or None,
    )

    handle_post_ingest(oid, payload_out, text)

    # Request embedding/indexing via the index outbox; do not include vectors.
    from app.outbox.events import emit_index_embedding_requested

    emit_index_embedding_requested(
        {
            "object_id": oid,
            "kind": kind,
            "source_ref": source_ref,
            "model": _EMBED_MODEL,
            "trace_id": payload_out.get("trace_id"),
            "source": "ingest",
        }
    )

    return oid, get_embed_dim()
