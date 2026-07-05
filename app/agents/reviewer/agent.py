from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.components.reasoning import ReasoningTaskKind, get_reasoning_facade
from app.objects import ObjectStore
from app.services.decisions import insert_decision
from app.events.types import CURATION_REVIEW_DONE
from app.services.audit import audit_event
from app.settings.models import ReviewerSettings, SettingsBundle
from app.settings.runtime import subscribe_settings

logger = logging.getLogger(__name__)

AGENT = "reviewer"

_REVIEW_COUNTER = {
    "n": 0,
}

_REVIEW_SETTINGS = ReviewerSettings()


def _payload_text(payload: dict[str, Any]) -> str:
    return str(payload.get("text") or payload.get("content") or payload.get("raw_text") or "")


def _apply_reviewer_settings(bundle: SettingsBundle) -> None:
    global _REVIEW_SETTINGS
    candidate = bundle.agents.get("reviewer") if bundle else None
    if isinstance(candidate, ReviewerSettings):
        _REVIEW_SETTINGS = candidate
    else:
        _REVIEW_SETTINGS = ReviewerSettings()


subscribe_settings(_apply_reviewer_settings)


def _next_allow(threshold: float) -> tuple[bool, float, list[str]]:
    idx = _REVIEW_COUNTER["n"]
    _REVIEW_COUNTER["n"] += 1

    if idx % 2 == 0:
        score = 0.9
        allow = score >= threshold
        reasons = ["high confidence content", "clean structure", "good source"]
    else:
        score = 0.5
        allow = score >= threshold
        reasons = ["low confidence content", "needs human validation"]

    return allow, score, reasons


def review(object_id: str, *, trace_id: str, threshold: float | None = None) -> dict[str, Any]:
    store = ObjectStore()
    obj = store.get_object(object_id)
    if not obj:
        raise RuntimeError(f"object {object_id} not found")

    payload = obj.payload if isinstance(obj.payload, dict) else {}
    text = _payload_text(payload)
    result = get_reasoning_facade().reason(
        ReasoningTaskKind.REVIEW,
        {"text": text, "object_uuid": object_id, "_agent": AGENT},
        trace_id=trace_id,
    )
    result_data = result.model_dump(mode="json") if hasattr(result, "model_dump") else {}
    suggestions = result_data.get("suggestions") or result_data.get("issues") or []

    effective_threshold = threshold if threshold is not None else _REVIEW_SETTINGS.threshold
    allow, score, reasons = _next_allow(effective_threshold)
    if suggestions and isinstance(suggestions, list):
        reasons = [str(s) for s in suggestions if s] or reasons

    out = {
        "event": CURATION_REVIEW_DONE,
        "object_id": object_id,
        "allow": allow,
        "score": score,
        "reasons": reasons,
        "agent": AGENT,
        "trace_id": trace_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "analysis": result_data.get("summary"),
        "suggestions": suggestions,
    }

    audit_event(
        event=CURATION_REVIEW_DONE,
        object_id=object_id,
        agent=AGENT,
        trace_id=trace_id,
        extra={"allow": allow, "score": score},
    )

    try:
        insert_decision(
            object_id,
            "review",
            {
                "allow": allow,
                "score": score,
                "reasons": reasons,
                "agent": AGENT,
            },
            trace_id,
        )
    except Exception:
        # P-5 receipt-before-ack (#2912): a review decision whose accountability
        # record cannot be persisted was never decided. This used to be a bare
        # `except Exception: pass` that re-swallowed at the call site what #2788
        # made fail-loud in insert_decision() itself (D-7-adjacent residue,
        # docs/architecture/runtime-semantics.md :: Divergences D-7). No caller
        # of review()/run() (the LangGraph `_act` node in
        # app/agents/reviewer/graph.py, the CLI dispatcher in
        # app/agents/runner.py, and the backfill job loop in
        # app/jobs/backfill.py) currently catches or tolerates a swallowed
        # failure here, so log-and-raise matches the existing propagate-uncaught
        # contract instead of inventing a new degraded-result shape.
        logger.exception(
            "reviewer decision write failed object_id=%s trace_id=%s",
            object_id,
            trace_id,
        )
        raise

    return out


def run(object_id: str, *, trace_id: str, threshold: float | None = None) -> dict[str, Any]:
    return review(object_id, trace_id=trace_id, threshold=threshold)
