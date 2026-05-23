from __future__ import annotations

from typing import Any
from datetime import datetime, timezone

from app.events.types import CURATION_CITATION_CHECK_DONE
from app.memory.store import remember
from app.services.decisions import latest_decision
from app.objects import ObjectStore

AGENT = "citation_checker"

def _latest_classification(oid: str) -> dict[str, Any] | None:
    """
    Fetch the latest classification decision via the decisions service (memory-backed by default).
    """
    decision = latest_decision(oid, "classification")
    if not decision:
        return None
    value = decision.get("value")
    return value if isinstance(value, dict) else None


def _has_sources(text: str) -> bool:
    """Simple heuristic: does the text contain a URL?"""
    t = text.lower()
    return "http://" in t or "https://" in t


def check_citations(object_id: str, *, trace_id: str) -> dict[str, Any]:
    """
    Validate that external claims have sources; writes memory and returns an event-shaped dict.
    """
    store = ObjectStore()
    obj = store.get_object(object_id)
    if not obj:
        raise RuntimeError(f"object {object_id} not found")

    body_text = obj.payload.get("body", "") or ""

    cls = _latest_classification(object_id) or {}
    trust = cls.get("trust", "own")

    if trust in ("external", "web", "imported", "other") and not _has_sources(body_text):
        status = "blocked"
        reason = "external_claims_without_sources"
    else:
        status = "ok"
        reason = "ok_or_internal"

    out = {
        "event": CURATION_CITATION_CHECK_DONE,
        "object_id": object_id,
        "status": status,
        "reason": reason,
        "trace_id": trace_id,
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    remember(
        AGENT,
        "citation_check",
        object_id=object_id,
        trace_id=trace_id,
        data={
            "status": status,
            "reason": reason,
        },
    )

    return out


def run(object_id: str, *, trace_id: str) -> dict[str, Any]:
    """Public entrypoint mirroring other agents."""
    return check_citations(object_id, trace_id=trace_id)
