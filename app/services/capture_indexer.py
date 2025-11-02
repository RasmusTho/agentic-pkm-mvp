from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from app.store.object_store import ObjectStore
from app.agents.indexer.agent import run as indexer_run
from app.services.audit import audit_event

AGENT = "capture_indexer"

def _build_domain_object(path: str) -> dict[str, Any]:
    """
    Best-effort mirror of what normalizer does, but inline so we can
    still handle raw capture notes until everything uses normalizer.agent.
    """
    p = Path(path)
    raw = p.read_text(encoding="utf-8")

    # title = first non-empty line or file stem
    title = ""
    for ln in raw.splitlines():
        stripped = ln.strip().lstrip("#").strip()
        if stripped:
            title = stripped
            break
    if not title:
        title = p.stem

    object_uuid = str(_uuid.uuid4())
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
    """
    1. Read captured note from disk
    2. Save into ObjectStore (so it's queryable)
    3. Run indexer on it (so it's searchable)
    4. Emit audit
    """
    dom = _build_domain_object(path)

    store = ObjectStore()
    store.save_object(
        dom,
        emit_outbox=False,
        trace_id=trace_id,
    )

    idx = indexer_run(dom["uuid"], trace_id=trace_id)

    audit_event(
        event="capture.indexed",
        object_id=dom["uuid"],
        agent=AGENT,
        trace_id=trace_id,
        extra={
            "path": path,
            "title": dom["payload"]["core6"]["title"],
            "embeddings": idx.get("embeddings", 0),
        },
    )

    return {
        "event": "capture.indexed",
        "object_id": dom["uuid"],
        "embeddings": idx.get("embeddings", 0),
        "trace_id": trace_id,
    }
