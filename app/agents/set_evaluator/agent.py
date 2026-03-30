from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional, Sequence
from uuid import UUID

from pydantic import BaseModel, Field

from app.components.reasoning import ReasoningTaskKind, get_reasoning_facade
from app.events.types import PROMOTION_EVALUATE_DONE
from app.stores import get_object_store
from app.store.object_store import ObjectStore
from app.services.decisions import insert_decision, latest_decision
from app.services.audit import audit_event
from app.services import llm as llm_service

AGENT = "set_evaluator"


def _payload_text(payload: dict[str, Any]) -> str:
    return str(payload.get("text") or payload.get("content") or payload.get("raw_text") or "")


def _latest_review(object_id: str) -> dict[str, Any] | None:
    dec = latest_decision(object_id, "review")
    if not dec:
        return None
    return dec.get("value") or dec


def _score_object(review_val: dict[str, Any]) -> dict[str, Any]:
    allow = bool(review_val.get("allow", False))
    base_score = float(review_val.get("score", 0.0))

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
    allow = scored["score"] >= threshold and scored["review_allow"]
    promote = allow

    out = {
        "event": PROMOTION_EVALUATE_DONE,
        "object_id": object_id,
        "allow": allow,
        "promote": promote,
        "score": scored["score"],
        "review_reasons": scored["review_reasons"],
        "trace_id": trace_id,
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    audit_event(
        event=PROMOTION_EVALUATE_DONE,
        object_id=object_id,
        agent=AGENT,
        trace_id=trace_id,
        extra={
            "allow": allow,
            "promote": promote,
            "score": scored["score"],
        },
    )

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


class RankedCandidate(BaseModel):
    object_id: str
    score: float
    reasons: list[str] = Field(default_factory=list)


class SetEvaluationResult(BaseModel):
    question: str
    ranking: list[RankedCandidate] = Field(default_factory=list)


def _candidate_payload(object_id: str, *, store: ObjectStore, fallback_store: Any) -> dict[str, Any]:
    obj = store.get_object(object_id)
    payload = obj.payload if obj else {}
    if not payload:
        try:
            alt = fallback_store.get(UUID(str(object_id)))
        except Exception:
            alt = None
        if alt and isinstance(alt, dict):
            payload = alt.get("payload") or {}
    text = _payload_text(payload) if isinstance(payload, dict) else ""
    return {"object_uuid": str(object_id), "text": text}


def _ranking_messages(question: str, candidates: list[dict[str, Any]]) -> list[dict[str, str]]:
    lines = ["You rank candidate notes for the given question."]
    if question:
        lines.append(f"Question: {question}")
    lines.append("Candidates:")
    for candidate in candidates:
        lines.append(f"- {candidate['object_uuid']}: {(candidate.get('text') or '')[:180]}")
    return [{"role": "user", "content": "\n".join(lines)}]


def run_set_evaluator(object_ids: Sequence[str], *, question: str, trace_id: str | None = None) -> SetEvaluationResult:
    store = ObjectStore()
    fallback_store = get_object_store()
    ranking: list[RankedCandidate] = []
    candidates = [
        _candidate_payload(str(object_id), store=store, fallback_store=fallback_store)
        for object_id in object_ids
    ]
    facade = get_reasoning_facade()
    result_data: dict[str, Any] = {}
    try:
        result = facade.reason(
            ReasoningTaskKind.RANKING,
            {"question": question, "candidates": candidates},
            trace_id=trace_id,
        )
        result_data = result.model_dump(mode="json") if hasattr(result, "model_dump") else {}
    except Exception:
        result_data = {}

    items = result_data.get("ranking") or []
    candidate_ids = {str(object_id) for object_id in object_ids}
    if isinstance(items, list):
        for idx, entry in enumerate(items):
            oid = str(entry.get("object_uuid") or object_ids[idx] if idx < len(object_ids) else "")
            if oid not in candidate_ids:
                continue
            score = float(entry.get("score") or max(0.0, 1.0 - 0.05 * idx))
            reason_text = str(entry.get("reason") or "").strip()
            reasons = [reason_text] if reason_text else []
            if not reasons:
                reasons.append("No reasoning available")
            ranking.append(RankedCandidate(object_id=oid, score=score, reasons=reasons))

    telemetry = list(getattr(facade, "telemetry", []))
    if telemetry:
        last = telemetry[-1]
        llm_service.log_llm_call(
            provider=last.provider,
            model=last.model,
            agent=AGENT,
            kind="reasoning.ranking",
            messages=_ranking_messages(question, candidates),
            response=result_data,
            response_text=json.dumps(result_data, ensure_ascii=False),
            trace_id=trace_id,
            status="ok" if ranking else "failed",
        )

    if not ranking:
        for idx, object_id in enumerate(object_ids):
            text = _candidate_payload(str(object_id), store=store, fallback_store=fallback_store).get("text") or ""
            snippet = text.strip()
            reasons = [snippet[:160]] if snippet else ["No reasoning available"]
            score = max(0.0, 1.0 - 0.05 * idx)
            ranking.append(RankedCandidate(object_id=str(object_id), score=score, reasons=reasons))
    elif len(ranking) < len(object_ids):
        ranked_ids = {item.object_id for item in ranking}
        for idx, object_id in enumerate(object_ids):
            object_id = str(object_id)
            if object_id in ranked_ids:
                continue
            text = _candidate_payload(object_id, store=store, fallback_store=fallback_store).get("text") or ""
            snippet = text.strip()
            reasons = [snippet[:160]] if snippet else ["No reasoning available"]
            score = max(0.0, 1.0 - 0.05 * (len(ranking) + idx))
            ranking.append(RankedCandidate(object_id=object_id, score=score, reasons=reasons))

    return SetEvaluationResult(question=question, ranking=ranking)
