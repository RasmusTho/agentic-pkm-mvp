from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

VALID_OBJECT_TYPES = {
    "note",
    "claim",
    "concept",
    "source",
    "chunk",
    "table",
    "synthesis_note",
}
VALID_SYSTEM_INTENTS = {"learn", "reflect", "synthesize", "communicate"}
DEFAULT_INTENT_BY_OBJECT_TYPE = {
    "note": "learn",
    "claim": "communicate",
    "concept": "learn",
    "source": "learn",
    "chunk": "learn",
    "table": "communicate",
    "synthesis_note": "synthesize",
}
VALID_EMERGENT_TAGS = {"serendipity", "collaboration", "exploration"}

REFLECT_DIR = Path("storage/reflect")
LOGS_DIR = Path("logs")
REFLECTION_LOG = LOGS_DIR / "reflection.json"
ANALYTICS_LOG = LOGS_DIR / "emergent_analytics.json"
RELATIONS_LOG = LOGS_DIR / "relations.jsonl"


def normalize_payload(payload: dict[str, Any], text: str) -> dict[str, Any]:
    """Ensure ingestion payload contains required derived fields."""
    data = dict(payload)
    if "text" not in data:
        data["text"] = text
    if "content" not in data:
        data["content"] = text
    if "title" not in data:
        first_line = text.strip().splitlines()[0] if text.strip() else ""
        data["title"] = first_line[:120] or "Untitled"

    object_type = str(data.get("object_type", "note")).strip() or "note"
    if object_type not in VALID_OBJECT_TYPES:
        object_type = "note"
    data["object_type"] = object_type

    system_intent = str(data.get("system_intent", "")).strip().lower()
    if system_intent not in VALID_SYSTEM_INTENTS:
        system_intent = DEFAULT_INTENT_BY_OBJECT_TYPE.get(object_type, "learn")
    data["system_intent"] = system_intent

    emergent_tags = data.get("emergent_tags", [])
    if not isinstance(emergent_tags, list):
        emergent_tags = [emergent_tags] if emergent_tags else []
    normalized_tags = []
    for tag in emergent_tags:
        tag_str = str(tag).strip().lower()
        if tag_str in VALID_EMERGENT_TAGS:
            normalized_tags.append(tag_str)
    data["emergent_tags"] = normalized_tags

    # Backwards compatibility: ensure clarity_score numeric if present
    clarity = data.get("clarity_score")
    if clarity is not None:
        try:
            data["clarity_score"] = float(clarity)
        except (TypeError, ValueError):
            data["clarity_score"] = None

    return data


def handle_post_ingest(object_id: UUID, payload: dict[str, Any], text: str) -> None:
    """Trigger lifecycle side-effects (reflection queues, analytics, relations)."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    _maybe_enqueue_reflection(object_id, payload, text)
    _update_emergent_analytics(payload)
    _record_synthesis_relation(object_id, payload)


def _maybe_enqueue_reflection(object_id: UUID, payload: dict[str, Any], text: str) -> None:
    if payload.get("system_intent") != "reflect":
        return

    clarity = payload.get("clarity_score")
    clarity_value = float(clarity) if isinstance(clarity, (int, float)) else None
    new_insight = bool(payload.get("new_insight"))
    should_enqueue = new_insight
    if clarity_value is not None and clarity_value < 0.6:
        should_enqueue = True

    if not should_enqueue:
        return

    REFLECT_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "source_object_id": str(object_id),
        "queued_at": datetime.now(tz=UTC).isoformat(),
        "payload": payload,
        "text": text,
    }
    queue_path = REFLECT_DIR / f"{object_id}.json"
    queue_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")

    _append_json_log(
        REFLECTION_LOG,
        {
            "object_id": str(object_id),
            "status": "queued",
            "reason": "low_clarity" if clarity_value is not None and clarity_value < 0.6 else "new_insight",
            "timestamp": datetime.now(tz=UTC).isoformat(),
        },
    )


def _update_emergent_analytics(payload: dict[str, Any]) -> None:
    snapshot: dict[str, Any]
    if ANALYTICS_LOG.exists():
        try:
            snapshot = json.loads(ANALYTICS_LOG.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            snapshot = {}
    else:
        snapshot = {}

    intent_counts = Counter(snapshot.get("system_intent", {}))
    tag_counts = Counter(snapshot.get("emergent_tags", {}))

    system_intent = payload.get("system_intent")
    if isinstance(system_intent, str) and system_intent in VALID_SYSTEM_INTENTS:
        intent_counts[system_intent] += 1

    for tag in payload.get("emergent_tags", []):
        if isinstance(tag, str) and tag in VALID_EMERGENT_TAGS:
            tag_counts[tag] += 1

    snapshot = {
        "updated_at": datetime.now(tz=UTC).isoformat(),
        "system_intent": dict(intent_counts),
        "emergent_tags": dict(tag_counts),
    }
    ANALYTICS_LOG.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


def _record_synthesis_relation(object_id: UUID, payload: dict[str, Any]) -> None:
    if payload.get("object_type") != "synthesis_note":
        return
    related_claims = payload.get("related_claim_ids") or payload.get("claim_ids") or []
    if not isinstance(related_claims, list):
        related_claims = [related_claims]
    entry = {
        "type": "synthesizes",
        "synthesis_id": str(object_id),
        "related_claims": [str(item) for item in related_claims],
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }
    with RELATIONS_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _append_json_log(path: Path, event: dict[str, Any]) -> None:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                data = []
        except json.JSONDecodeError:
            data = []
    else:
        data = []
    data.append(event)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
