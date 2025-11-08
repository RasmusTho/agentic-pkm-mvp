from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict
from uuid import UUID

INDEX_OUTBOX_PATH = Path(os.environ.get("INDEX_OUTBOX_PATH", "logs/index-outbox.jsonl"))


def emit_index_object_embedded(event: Dict[str, Any]) -> None:
    required = {"object_id", "kind", "source_ref", "payload", "embedding", "model"}
    missing = sorted(required - set(event.keys()))
    if missing:
        raise ValueError(f"index.object.embedded missing fields: {', '.join(missing)}")

    payload = dict(event)
    obj_id = payload["object_id"]
    if isinstance(obj_id, UUID):
        payload["object_id"] = str(obj_id)
    else:
        payload["object_id"] = str(obj_id)
    payload.setdefault("topic", "index.object.embedded")

    INDEX_OUTBOX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with INDEX_OUTBOX_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


__all__ = ["emit_index_object_embedded", "INDEX_OUTBOX_PATH"]
