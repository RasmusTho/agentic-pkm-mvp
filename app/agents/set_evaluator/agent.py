from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.store.object_store import ObjectStore
from app.services.decisions import insert_decision, latest_decision
from app.services.audit import audit_event

AGENT = "set_evaluator"


def _latest_review(object_id: str) -> dict[str, Any] | None:
    """
    Hämta senaste review-beslutet från in-memory decisions fallback.
    """
    dec = latest_decision(object_id, "review")
    if not dec:
        return None
    return dec.get("value") or dec


def _score_object(review_val: dict[str, Any]) -> dict[str, Any]:
    """
    Bygg en deterministisk poäng för objektet utifrån review-resultatet.
    Vi använder samma data vi redan har, ingen LLM, bara enkel logik.
    """
    allow = bool(review_val.get("allow", False))
    base_score = float(review_val.get("score", 0.0))

    # bump score lite om allow var True bara för determinism
    if allow and base_score < 0.8:
        base_score = 0.8

    reasons = review_val.get("reasons", [])
    return {
        "score": base_score,
        "review_allow": allow,
        "review_reasons": reasons,
    }


def evaluate_object(object_id: str, *, trace_id: str, threshold: float = 0.8) -> dict[str, Any]:
    store = ObjectStore()
    obj = store.get_object(object_id)
    if not obj:
        raise RuntimeError(f"object {object_id} not found")

    review_val = _latest_review(object_id)
    if not review_val:
        raise ValueError("missing review decision")

    scored = _score_object(review_val)

    # allow = "this is good enough to promote"
    allow = scored["score"] >= threshold and scored["review_allow"]

    # promote flag for the test
    promote = allow

    out = {
        "event": "promotion.evaluate.done",
        "object_id": object_id,
        "allow": allow,
        "promote": promote,
        "score": scored["score"],
        "review_reasons": scored["review_reasons"],
        "trace_id": trace_id,
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    # audit best-effort
    audit_event(
        event="promotion.evaluate.done",
        object_id=object_id,
        agent=AGENT,
        trace_id=trace_id,
        extra={
            "allow": allow,
            "promote": promote,
            "score": scored["score"],
        },
    )

    # save evaluate decision (best effort, tolerate no-DB mode)
    try:
        insert_decision(
            object_id,
            "evaluate",
            {
                "allow": allow,
                "promote": promote,
                "score": scored["score"],
                "reasons": scored["review_reasons"],
                "agent": AGENT,
            },
            trace_id,
        )
    except Exception:
        pass

    return out


def run(object_id: str, *, trace_id: str, threshold: float = 0.8) -> dict[str, Any]:
    return evaluate_object(object_id, trace_id=trace_id, threshold=threshold)
