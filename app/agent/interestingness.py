from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterable, Sequence
from uuid import UUID

from app.plugins.base import ToolResult


@dataclass(slots=True)
class InterestingnessCandidate:
    object_id: UUID
    payload: dict[str, Any]
    source_tool: str = "retriever"


@dataclass(slots=True)
class InterestingnessResult:
    object_id: UUID
    novelty: float
    anomaly: float
    uncertainty: float
    value: float
    score: float
    reason: str
    payload: dict[str, Any]
    source_tool: str = "retriever"


def extract_candidates(results: Sequence[ToolResult]) -> list[InterestingnessCandidate]:
    candidates: list[InterestingnessCandidate] = []
    for result in results:
        if result.name != "retriever":
            continue
        if not isinstance(result.output, list):
            continue
        for item in result.output:
            try:
                object_id = UUID(str(item["object_id"]))
            except (KeyError, ValueError):
                continue
            payload = item.get("payload") or {}
            candidates.append(
                InterestingnessCandidate(
                    object_id=object_id,
                    payload=payload,
                    source_tool=result.name,
                )
            )
    return candidates


def score_candidates(
    candidates: Iterable[InterestingnessCandidate],
    weights: dict[str, float],
) -> list[InterestingnessResult]:
    scored: list[InterestingnessResult] = []
    for candidate in candidates:
        digest = hashlib.sha256(candidate.object_id.bytes).digest()
        novelty = int.from_bytes(digest[0:2], "big") / 65535
        anomaly = int.from_bytes(digest[2:4], "big") / 65535
        uncertainty = int.from_bytes(digest[4:6], "big") / 65535
        value = int.from_bytes(digest[6:8], "big") / 65535
        score = (
            novelty * weights["novelty"]
            + anomaly * weights["anomaly"]
            + uncertainty * weights["uncertainty"]
            + value * weights["value"]
        )
        reason = candidate.payload.get("title") or str(candidate.object_id)
        scored.append(
            InterestingnessResult(
                object_id=candidate.object_id,
                novelty=novelty,
                anomaly=anomaly,
                uncertainty=uncertainty,
                value=value,
                score=score,
                reason=reason,
                payload=candidate.payload,
                source_tool=candidate.source_tool,
            )
        )
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored
