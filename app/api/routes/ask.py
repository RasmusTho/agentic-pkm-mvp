from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.observability.status_service import record_ask_query
from app.retrieval.hybrid import hybrid_search

router = APIRouter()


class AskRequest(BaseModel):
    question: str
    zone_strategy: str | None = "default"


class AskSource(BaseModel):
    uuid: str
    title: str
    origin: str
    zone: str | None = None
    path: str | None = None


class AskResponse(BaseModel):
    answer: str
    sources: list[AskSource]
    latency_ms: int


def _to_source(hit: dict[str, Any]) -> AskSource:
    payload = hit.get("payload") or {}
    origin = str(payload.get("origin") or "vault")
    path = hit.get("source_ref") or payload.get("source_ref")
    title = payload.get("title") or hit.get("title") or ""
    return AskSource(
        uuid=str(hit.get("id") or hit.get("doc_id") or payload.get("uuid") or ""),
        title=str(title),
        origin=origin,
        zone=None,
        path=str(path) if path else None,
    )


@router.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    start = time.perf_counter()
    hits = hybrid_search(req.question, k=4)
    if hits:
        answer_text = hits[0].get("snippet") or hits[0].get("text") or ""
    else:
        answer_text = "No results found."
    latency_ms = int((time.perf_counter() - start) * 1000)
    record_ask_query(float(latency_ms))
    sources = [_to_source(hit) for hit in hits]
    return AskResponse(answer=answer_text, sources=sources, latency_ms=latency_ms)


__all__ = ["router", "AskRequest", "AskResponse"]
