from __future__ import annotations

import json
import uuid
from typing import Any, Dict

from app.db import conn_rw
from app.services.indexer import _upsert_object, _upsert_embedding
from app.tracing import start_span


def _fake_embed(text: str) -> list[float]:
    # placeholder embedding so we can index without pgvector
    # deterministic but useless for semantic search
    h = hash(text)
    return [
        ((h >> 0) & 0xFF) / 255.0,
        ((h >> 8) & 0xFF) / 255.0,
        ((h >> 16) & 0xFF) / 255.0,
        ((h >> 24) & 0xFF) / 255.0,
    ]


def index_capture_bundle(bundle: Dict[str, Any]) -> None:
    """
    Take the structured capture bundle (summary/tasks/decisions/entities/raw),
    write it into Postgres as kind='capture', and generate a dumb embedding.
    """

    # bundle comes from capture_ingest:
    # {
    #   "bundle_id": "cap-20251030-205255",
    #   "summary": "...",
    #   "tasks": [...],
    #   "decisions": [...],
    #   "entities": [...],
    #   "raw": "original text",
    # }

    bundle_id = bundle["bundle_id"]  # human-readable id (cap-...)
    summary = bundle["summary"]
    tasks = bundle["tasks"]
    decisions = bundle["decisions"]
    entities = bundle["entities"]
    raw = bundle["raw"]

    # We'll store a DB UUID as the canonical object id.
    db_uuid = uuid.uuid4()

    # Build a text blob to embed for search
    content_lines: list[str] = []

    if summary.strip():
        content_lines.append("Summary:")
        content_lines.append(summary.strip())
        content_lines.append("")

    if tasks:
        content_lines.append("Tasks:")
        for t in tasks:
            content_lines.append(f"- [ ] {t['text']} @{t['owner']}")
        content_lines.append("")

    if decisions:
        content_lines.append("Decisions:")
        for d in decisions:
            content_lines.append(f"- {d}")
        content_lines.append("")

    if entities:
        content_lines.append("Entities:")
        for e in entities:
            content_lines.append(f"- {e['name']} ({e['type']})")
        content_lines.append("")

    content_lines.append("Raw capture:")
    content_lines.append(raw.strip())

    content_blob = "\n".join(content_lines)

    embedding = _fake_embed(content_blob)

    # This is what we'll persist as `payload` for kind='capture'
    payload: Dict[str, Any] = {
        "title": summary.splitlines()[0][:120] if summary.strip() else "capture",
        "review_state": "inbox",
        "content": content_blob,
        # keep a link back to the human-facing capture note in the vault
        "source_uuid": bundle_id,
        "entities": entities,
        "tasks": tasks,
        "decisions": decisions,
    }

    payload_json = json.dumps(payload)

    # No real trace_id yet; wire later
    trace_id = None

    with conn_rw() as conn:
        with conn.cursor() as cur:
            with start_span("indexer.capture", trace_id, {"kind": "capture"}):
                _upsert_object(cur, db_uuid, payload_json)
                _upsert_embedding(cur, db_uuid, embedding)
        conn.commit()
