from __future__ import annotations

import json
import math
import os
import uuid
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.agents.base.audit import audit_log
from app.memory.store import remember, recall

AGENT = "set_evaluator"


def _dsn() -> str:
    url = os.environ.get("DATABASE_URL") or "postgresql+psycopg://app:app@127.0.0.1:15432/app"
    return url.replace("postgresql+psycopg://", "postgresql://")


def _latest_review(object_id: str) -> dict[str, Any] | None:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT value
                FROM decisions
                WHERE object_id=%s AND key='review'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (object_id,),
            )
            row = cur.fetchone()
            return row["value"] if row else None


def _chunk_count(object_id: str) -> int:
    memories = recall("chunker", "chunked", object_id=object_id, limit=1)
    if memories:
        entry = memories[0]
        chunks = entry.get("chunks")
        if isinstance(chunks, (int, float)):
            return max(0, int(chunks))
        if isinstance(chunks, str):
            try:
                return max(0, int(chunks))
            except ValueError:
                pass
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM chunks WHERE object_id=%s", (object_id,))
            row = cur.fetchone()
            return int(row["c"]) if row else 0


def _embedding_count(object_id: str) -> int:
    memories = recall("indexer", "embedding_stats", object_id=object_id, limit=1)
    if memories:
        entry = memories[0]
        embeddings = entry.get("embeddings")
        if isinstance(embeddings, (int, float)):
            return max(0, int(embeddings))
        if isinstance(embeddings, str):
            try:
                return max(0, int(embeddings))
            except ValueError:
                pass
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM embeddings WHERE object_id=%s", (object_id,))
            row = cur.fetchone()
            return int(row["c"]) if row else 0


def _compute_density(chunks: int, embeddings: int) -> float:
    if chunks <= 0 and embeddings <= 0:
        return 0.0
    combined = chunks + max(embeddings, 1)
    density = (math.log1p(combined) + math.log1p(max(chunks, 1))) / 3.0
    return float(min(1.0, density))


def evaluate_object(object_id: str, *, trace_id: str, threshold: float = 0.8) -> dict[str, Any]:
    review = _latest_review(object_id)
    if not review:
        raise ValueError("missing review decision")

    recall(AGENT, "evaluation", object_id=None, limit=3)

    chunks = _chunk_count(object_id)
    embeddings = _embedding_count(object_id)
    density = _compute_density(chunks, embeddings)

    trust = float(review.get("trust") or 0.0)
    allow = bool(review.get("allow"))

    score = 0.6 * trust + 0.4 * density
    promote = bool(allow and score >= threshold)

    value = {
        "score": float(round(score, 4)),
        "promote": promote,
        "threshold": float(threshold),
        "trust": trust,
        "allow": allow,
        "missing_citations": int(review.get("missing_citations") or 0),
        "chunks": chunks,
        "embeddings": embeddings,
    }

    with psycopg.connect(_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO decisions (id, object_id, key, value, created_at)
                VALUES (%s, %s, %s, %s::jsonb, now())
                """,
                (str(uuid.uuid4()), object_id, "evaluate", json.dumps(value)),
            )

    audit_log(
        object_id=object_id,
        agent=AGENT,
        action="promotion.allow" if promote else "promotion.block",
        trace_id=trace_id,
        details=value,
    )

    remember(
        agent=AGENT,
        kind="evaluation",
        object_id=object_id,
        trace_id=trace_id,
        data=value,
    )

    return {
        "event": "promotion.evaluate.done",
        "object_id": object_id,
        "score": value["score"],
        "promote": promote,
        "threshold": float(threshold),
    }


def run(object_id: str, *, trace_id: str, threshold: float = 0.8) -> dict[str, Any]:
    return evaluate_object(object_id, trace_id=trace_id, threshold=threshold)
