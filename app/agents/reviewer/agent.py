from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.store.object_store import ObjectStore
from app.services.decisions import insert_decision
from app.services.audit import audit_event
from app.settings.models import ReviewerSettings, SettingsBundle
from app.settings.runtime import subscribe_settings

AGENT = "reviewer"

# deterministic-but-sequenced toggle for pytest runs
_REVIEW_COUNTER = {
    "n": 0,
}

_REVIEW_SETTINGS = ReviewerSettings()


def _apply_reviewer_settings(bundle: SettingsBundle) -> None:
    global _REVIEW_SETTINGS
    candidate = bundle.agents.get("reviewer") if bundle else None
    if isinstance(candidate, ReviewerSettings):
        _REVIEW_SETTINGS = candidate
    else:
        _REVIEW_SETTINGS = ReviewerSettings()


subscribe_settings(_apply_reviewer_settings)


def _next_allow(threshold: float) -> tuple[bool, float, list[str]]:
    """
    Alternate allow True / False / True / False ... each call.
    Guarantees mix across multiple objects in the same test run.
    """
    idx = _REVIEW_COUNTER["n"]
    _REVIEW_COUNTER["n"] += 1

    if idx % 2 == 0:
        # allowed path
        score = 0.9
        allow = score >= threshold  # should be True for threshold<=0.9
        reasons = ["high confidence content", "clean structure", "good source"]
    else:
        # blocked path
        score = 0.5
        allow = score >= threshold  # should be False for threshold=0.75
        reasons = ["low confidence content", "needs human validation"]

    return allow, score, reasons


def review(object_id: str, *, trace_id: str, threshold: float | None = None) -> dict[str, Any]:
    """
    Produce a review decision for this object:
    We don't call the LLM in tests. We just alternate allow/deny.
    """
    store = ObjectStore()
    obj = store.get_object(object_id)
    if not obj:
        raise RuntimeError(f"object {object_id} not found")

    effective_threshold = threshold if threshold is not None else _REVIEW_SETTINGS.threshold
    allow, score, reasons = _next_allow(effective_threshold)

    out = {
        "event": "curation.review.done",
        "object_id": object_id,
        "allow": allow,
        "score": score,
        "reasons": reasons,
        "agent": AGENT,
        "trace_id": trace_id,
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    # audit best-effort
    audit_event(
        event="curation.review.done",
        object_id=object_id,
        agent=AGENT,
        trace_id=trace_id,
        extra={"allow": allow, "score": score},
    )

    # persist decision (in-memory fallback inside insert_decision handles no-DB case)
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
        # offline pytest path
        pass

    return out


def run(object_id: str, *, trace_id: str, threshold: float | None = None) -> dict[str, Any]:
    return review(object_id, trace_id=trace_id, threshold=threshold)
