from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.store.object_store import ObjectStore
from app.services.audit import audit_event


AGENT = "normalizer"


def _read_file(path: str) -> tuple[str, str]:
    """
    Return (title, body_text) from a markdown-ish file.
    """
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in raw.splitlines()]
    title = ""
    for ln in lines:
        if ln.startswith("#"):
            cand = ln.lstrip("#").strip()
            if cand:
                title = cand
                break
        elif ln:
            title = ln
            break
    if not title:
        title = p.stem
    return title, raw


def normalize_file(path: str, *, trace_id: str) -> dict[str, Any]:
    """
    Build a 'domain object' from a source file:
    - uuid
    - core6 metadata
    - payload with raw_text + source_path
    """
    title, raw_text = _read_file(path)

    object_uuid = str(_uuid.uuid4())

    core6 = {
        "id": object_uuid,
        "title": title,
        "review_state": "reviewed",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    payload: dict[str, Any] = {
        "core6": core6,
        "raw_text": raw_text,
        "source_path": path,
    }

    domain_object = {
        "uuid": object_uuid,
        "kind": "note",
        "payload": payload,
        # carry source_ref as first-class too for DB upsert
        "source_ref": path,
    }

    # best-effort audit
    audit_event(
        event="ingest.normalize.done",
        object_id=object_uuid,
        agent=AGENT,
        trace_id=trace_id,
        extra={"path": path, "title": title},
    )

    return domain_object


@dataclass
class _DomainObjectShim:
    uuid: str
    kind: str
    payload: dict[str, Any]
    created_at: datetime
    source_ref: str | None


def run(path: str, *, trace_id: str) -> dict[str, Any]:
    """
    End-to-end:
    - normalize file into domain_object
    - create shim matching ObjectStore expectations
    - save via ObjectStore (memory + DB if available)
    """
    store = ObjectStore()
    dom = normalize_file(path, trace_id=trace_id)

    shim = _DomainObjectShim(
        uuid=dom["uuid"],
        kind=dom["kind"],
        payload=dom["payload"],
        created_at=datetime.now(timezone.utc),
        source_ref=dom.get("source_ref") or dom["payload"].get("source_path"),
    )

    store.save_object(
        shim,
        emit_outbox=False,
        trace_id=trace_id,
    )

    out = {
        "event": "ingest.normalize.done",
        "object_id": dom["uuid"],
        "core6": dom["payload"]["core6"],
        "trace_id": trace_id,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    return out
