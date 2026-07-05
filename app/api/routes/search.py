from __future__ import annotations

import contextlib

from fastapi import APIRouter, Query, Request

from app.observability.tracer import start_span
from app.retrieval.capability import RetrievalRequest, retrieve

router = APIRouter()


@router.get("/search")
async def search(request: Request, q: str = Query(...)) -> dict[str, object]:
    """Query the canonical retrieval substrate (durable-index-backed hybrid
    search) — the same capability `/api/ask` reads (KERNEL-05, I-D3).

    No legacy-table reads and no silent fallback: a retrieval failure
    propagates as an error instead of returning query-independent filler
    results (#2989).
    """
    trace_id = getattr(request.state, "trace_id", None) or request.headers.get("x-trace-id")
    span_cm = start_span("api.search", trace_id, {"path": "/search", "q": q}) if trace_id else contextlib.nullcontext()

    with span_cm:
        response = retrieve(RetrievalRequest(query=q, k=10, trace_id=trace_id))

    results = [
        {
            "uuid": hit.doc_id,
            "title": str(hit.payload.get("title") or ""),
        }
        for hit in response.hits
        if hit.doc_id
    ]
    return {"results": results[:10]}
