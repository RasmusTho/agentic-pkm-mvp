from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict
from uuid import UUID

from app.events.schema import make_outbox_event

INDEX_OUTBOX_PATH = Path(os.environ.get("INDEX_OUTBOX_PATH", "logs/index-outbox.jsonl"))


def emit_index_object_embedded(event: Dict[str, Any]) -> None:
    required = {"object_id", "kind", "source_ref", "payload", "embedding", "model"}
    missing = sorted(required - set(event.keys()))
    if missing:
        raise ValueError(f"index.object.embedded missing fields: {', '.join(missing)}")

    payload = dict(event)
    obj_id = payload["object_id"]
    payload["object_id"] = str(obj_id) if not isinstance(obj_id, UUID) else str(obj_id)
    payload.setdefault("topic", "index.object.embedded")

    trace_val = payload.get("trace_id") or payload.get("payload", {}).get("trace_id")
    envelope = make_outbox_event(
        "index.object.embedded",
        source=str(payload.get("source") or "indexer"),
        trace_id=str(trace_val) if trace_val else None,
        payload=payload,
    )

    INDEX_OUTBOX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with INDEX_OUTBOX_PATH.open("a", encoding="utf-8") as fh:
        record = dict(payload)
        record.update(envelope.model_dump())
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


__all__ = ["emit_index_object_embedded", "INDEX_OUTBOX_PATH"]
