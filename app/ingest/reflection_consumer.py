from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from app.ingest.lifecycle import REFLECT_DIR
from app.search.service import ingest_object


def consume_reflection_queue() -> list[UUID]:
    """Read queued reflection artifacts, re-ingest them, and remove processed files."""
    processed: list[UUID] = []
    if not REFLECT_DIR.exists():
        return processed

    for entry_path in sorted(REFLECT_DIR.glob("*.json")):
        try:
            payload = _load_entry(entry_path)
        except ValueError:
            entry_path.unlink(missing_ok=True)
            continue

        text = payload.pop("__text__", "")
        kind = payload.get("object_type", "note")
        source_ref = payload.get("source_ref") or f"reflect:{payload.get('source_object_id', '')}"

        new_id, _ = ingest_object(
            object_id=None,
            kind=kind,
            source_ref=source_ref,
            payload=payload,
            text=text,
        )
        processed.append(new_id)
        entry_path.unlink(missing_ok=True)

    return processed


def _load_entry(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Reflection entry must be a JSON object")

    payload = raw.get("payload") or {}
    text = raw.get("text", "")

    if not isinstance(payload, dict):
        raise ValueError("Reflection payload must be an object")

    payload.setdefault("origin", "internal")
    payload["system_intent"] = "learn"
    payload.pop("clarity_score", None)
    payload.pop("new_insight", None)
    source_object_id = raw.get("source_object_id")
    if source_object_id:
        payload.setdefault("source_object_id", source_object_id)

    payload["__text__"] = text
    return payload
