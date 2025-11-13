from __future__ import annotations

import uuid as uuidlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from app.agents.indexer.agent import run as indexer_run
from app.services.audit import audit_event
from app.store.object_store import ObjectStore

AGENT = "capture_indexer"


def _build_domain_object(path: str) -> dict[str, Any]:
    file_path = Path(path)
    raw = file_path.read_text(encoding="utf-8")

    title = ""
    for line in raw.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            title = stripped
            break
    if not title:
        title = file_path.stem

    object_uuid = str(uuidlib.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    core6 = {
        "id": object_uuid,
        "type": "note",
        "title": title,
        "created": now,
        "updated": now,
        "origin": "capture",
        "review_state": "inbox",
    }

    payload: Dict[str, Any] = {
        "core6": core6,
        "raw_text": raw,
        "source_path": str(path),
    }

    return {
        "uuid": object_uuid,
        "kind": "note",
        "payload": payload,
        "source_ref": str(path),
        "created_at": datetime.now(timezone.utc),
    }


def capture_and_index(path: str, *, trace_id: str) -> dict[str, Any]:
    domain = _build_domain_object(path)

    store = ObjectStore()
    store.save_object(domain, emit_outbox=False, trace_id=trace_id)

    idx_result = indexer_run(domain["uuid"], trace_id=trace_id)

    audit_event(
        event="capture.indexed",
        object_id=domain["uuid"],
        agent=AGENT,
        trace_id=trace_id,
        extra={
            "path": path,
            "title": domain["payload"]["core6"]["title"],
            "embeddings": idx_result.get("embeddings", 0),
        },
    )

    return {
        "event": "capture.indexed",
        "object_id": domain["uuid"],
        "embeddings": idx_result.get("embeddings", 0),
        "trace_id": trace_id,
    }
