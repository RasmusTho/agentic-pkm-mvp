from __future__ import annotations

import contextlib

from fastapi import APIRouter, Depends, Query, Request

from app.api.request_active_context import require_scoped_read_context
from app.observability.tracer import start_span
from app.retrieval.capability import RetrievalRequest, retrieve
from app.vault.active_context_v1 import ActiveContextSetV1

router = APIRouter()


@router.get("/search")
async def search(
    request: Request,
    q: str = Query(...),
) -> dict[str, object]:
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


@router.get("/search/scoped")
async def search_scoped(
    request: Request,
    q: str = Query(...),
    context: ActiveContextSetV1 = Depends(require_scoped_read_context),
) -> dict[str, object]:
    """Carrier-bound retrieval for migrated multi-vault clients."""

    trace_id = getattr(request.state, "trace_id", None) or request.headers.get("x-trace-id")
    span_cm = (
        start_span("api.search.scoped", trace_id, {"path": "/search/scoped", "q": q})
        if trace_id
        else contextlib.nullcontext()
    )
    with span_cm:
        response = retrieve(
            RetrievalRequest(
                query=q,
                k=10,
                trace_id=trace_id,
                scope=context.scope,
                active_context=context,
            )
        )
    return {
        "results": [
            {"uuid": hit.doc_id, "title": str(hit.payload.get("title") or "")}
            for hit in response.hits
            if hit.doc_id
        ][:10]
    }
