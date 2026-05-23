from __future__ import annotations

from typing import Any

import logging

from app.agents.base.audit import audit_log
from app.components.reasoning.facade import ReasoningTaskKind, _heuristic_classify, get_reasoning_facade
from app.memory.store import remember, recall
from app.objects import ObjectStore, DomainObject
from app.stores.decisions import put_decision

logger = logging.getLogger(__name__)


def classify_object(object_id: str, *, trace_id: str) -> dict[str, Any]:
    store = ObjectStore()
    domain_obj: DomainObject | None = store.get_object(object_id)
    if domain_obj is None:
        raise ValueError("object not found")
    payload = domain_obj.payload or {}
    text = payload.get("text") or payload.get("content") or ""

    facade = get_reasoning_facade()
    try:
        result = facade.reason(
            ReasoningTaskKind.CLASSIFY,
            {"text": text, "object_uuid": object_id},
            trace_id=trace_id,
        )
        # result is a ClassifyResult Pydantic model
        value: dict[str, Any] = {
            "type": result.type,
            "tags": result.tags,
            "trust": result.trust,
            "confidence": result.confidence,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "classify_object: LLM/facade failed for object_id=%s trace=%s — using heuristic fallback. error=%s",
            object_id,
            trace_id,
            exc,
        )
        value = _heuristic_classify(text)

    put_decision(
        object_id=object_id,
        key="classification",
        value=value,
        agent="classifier",
        kind="classification",
    )
    remember(
        agent="classifier",
        kind="classified",
        object_id=object_id,
        trace_id=trace_id,
        data={
            "labels": value.get("tags"),
            "confidence": value["confidence"],
        },
    )
    audit_log(object_id=object_id, agent="classifier", action="classify", trace_id=trace_id, details=value)
    audit_log(
        object_id=object_id,
        agent="classifier",
        action="metadata.changed",
        trace_id=trace_id,
        details={"key": "classification"},
    )
    # raw is the last telemetry record's output; expose for callers that rely on it
    raw_content: str | None = None
    if facade.telemetry:
        raw_content = None  # telemetry does not store raw output; keep None as before if LLM succeeded via heuristic
    return {"object_id": object_id, "classification": value, "raw": raw_content}


def run(object_id: str, *, trace_id: str) -> dict[str, Any]:
    recall("classifier", "classified", object_id=None, limit=3)
    return classify_object(object_id, trace_id=trace_id)
