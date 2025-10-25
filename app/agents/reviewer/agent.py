from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import psycopg
from psycopg.rows import dict_row

from app.agents.base.audit import audit_log
from app.memory.store import remember, recall

AGENT = "reviewer"


def _dsn() -> str:
    url = os.environ.get("DATABASE_URL") or "postgresql+psycopg://app:app@127.0.0.1:15432/app"
    return url.replace("postgresql+psycopg://", "postgresql://")


def _fetch_decision_values(object_id: str, key: str, limit: int = 5) -> list[dict[str, Any]]:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT value
                FROM decisions
                WHERE object_id = %s AND key = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (object_id, key, limit),
            )
            rows = cur.fetchall()
            return [r["value"] or {} for r in rows]


def _sum_missing_citations(object_id: str) -> int:
    memories = recall("citation_checker", "citation_check", object_id=object_id, limit=5)
    total = 0
    for entry in memories:
        raw = entry.get("missing")
        if raw is None:
            raw = entry.get("missing_citations")
        if isinstance(raw, bool):
            total += int(raw)
        elif isinstance(raw, (int, float)):
            total += int(raw)
    if total > 0:
        return total

    decisions = _fetch_decision_values(object_id, "missing_citations", limit=5)
    for val in decisions:
        raw = val.get("value")
        if isinstance(raw, bool):
            total += int(raw)
        elif isinstance(raw, (int, float)):
            total += int(raw)
    return total


def _latest_duplicate_of(object_id: str) -> Optional[str]:
    decisions = _fetch_decision_values(object_id, "duplicate_of", limit=1)
    if not decisions:
        return None
    value = decisions[0]
    canonical = value.get("canonical_id") or value.get("canonical")
    if isinstance(canonical, uuid.UUID):
        return str(canonical)
    if canonical is None:
        return None
    return str(canonical)


def _latest_classification(object_id: str) -> dict[str, Any]:
    decisions = _fetch_decision_values(object_id, "classification", limit=1)
    return decisions[0] if decisions else {}


def _chunks_summary(object_id: str) -> Optional[int]:
    memories = recall("chunker", "chunked", object_id=object_id, limit=1)
    if not memories:
        return None
    entry = memories[0]
    chunks = entry.get("chunks")
    if isinstance(chunks, int):
        return chunks
    if isinstance(chunks, (float, str)):
        try:
            return int(chunks)
        except (ValueError, TypeError):
            return None
    return None


@dataclass
class ReviewContext:
    missing_citations: int
    duplicate_of: Optional[str]
    classification: dict[str, Any]
    chunks: Optional[int]


def _load_context(object_id: str) -> ReviewContext:
    missing = _sum_missing_citations(object_id)
    duplicate_of = _latest_duplicate_of(object_id)
    classification = _latest_classification(object_id)
    chunks = _chunks_summary(object_id)
    return ReviewContext(
        missing_citations=missing,
        duplicate_of=duplicate_of,
        classification=classification,
        chunks=chunks,
    )


def review_object(object_id: str, *, trace_id: str, threshold: float = 0.75) -> dict[str, Any]:
    review_mem = recall(AGENT, "review", object_id=None, limit=3)
    _ = review_mem  # placeholder for future reflective logic

    normalized = recall("normalizer", "normalized", object_id=object_id, limit=1)
    chunked = recall("chunker", "chunked", object_id=object_id, limit=1)
    citation_checks = recall("citation_checker", "citation_check", object_id=object_id, limit=5)
    _ = (normalized, chunked, citation_checks)  # appease linter; ensures side-effects remain deterministic

    ctx = _load_context(object_id)

    trust = 1.0
    if ctx.missing_citations > 0:
        trust = min(trust, 0.6)
    if ctx.duplicate_of:
        trust = min(trust, 0.5)

    allow = ctx.missing_citations == 0 and trust >= threshold

    reasons: list[str] = []
    if ctx.missing_citations > 0:
        reasons.append(f"{ctx.missing_citations} missing citation(s)")
    if ctx.duplicate_of:
        reasons.append(f"duplicate of {ctx.duplicate_of}")
    if not reasons and allow:
        reasons.append("meets promotion policy")
    if not allow and not reasons:
        reasons.append(f"trust {trust:.2f} below threshold {threshold:.2f}")

    rationale = "; ".join(reasons)

    value = {
        "allow": allow,
        "trust": float(trust),
        "missing_citations": int(ctx.missing_citations),
        "duplicate_of": ctx.duplicate_of,
        "rationale": rationale,
    }

    with psycopg.connect(_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO decisions (id, object_id, key, value, created_at)
                VALUES (%s, %s, %s, %s::jsonb, now())
                """,
                (str(uuid.uuid4()), object_id, "review", json.dumps(value)),
            )

    action = "gate.allow" if allow else "gate.block"
    audit_log(
        object_id=object_id,
        agent=AGENT,
        action=action,
        trace_id=trace_id,
        details=value,
    )

    remember(
        agent=AGENT,
        kind="review",
        object_id=object_id,
        trace_id=trace_id,
        data=value,
    )

    return {
        "event": "curation.review.done",
        "object_id": object_id,
        "allow": allow,
        "trust": float(trust),
        "missing_citations": int(ctx.missing_citations),
        "duplicate_of": ctx.duplicate_of,
    }


def run(object_id: str, *, trace_id: str, threshold: float = 0.75) -> dict[str, Any]:
    return review_object(object_id, trace_id=trace_id, threshold=threshold)
